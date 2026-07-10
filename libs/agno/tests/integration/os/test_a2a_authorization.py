"""A2A authorization + run-identity gate (v2.7 release blockers B1 / B2).

B1: A2A authenticates (behind AuthMiddleware, see test_a2a_auth.py) but historically
enforced *no* authorization scopes -- a ``config:read``-only token could fully execute
agents/teams/workflows over ``/a2a/*``. These tests assert the scope map now gates every
A2A route.

B2: A2A took run identity from the client ``X-User-ID`` header / ``metadata.userId``,
allowing impersonation and reserved-principal spoofing. These tests assert identity is
pinned to the authenticated principal and that reserved principals are rejected.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.run.agent import RunOutput
from agno.session.agent import AgentSession
from agno.team import Team
from agno.workflow import Step, Workflow

JWT_SECRET = "test-secret-for-a2a-authz"
AGENT_ID = "authz-agent"


def _token(scopes, sub="user-1"):
    payload = {
        "sub": sub,
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _message_body():
    return {
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": "request-123",
        "params": {
            "message": {
                "messageId": "msg-123",
                "role": "user",
                "parts": [{"kind": "text", "text": "Hello!"}],
            }
        },
    }


@pytest.fixture
def agent():
    agent = Agent(id=AGENT_ID, name="Authz Agent", db=InMemoryDb())
    # Return same instance from deep_copy so arun patches work
    agent.deep_copy = lambda **kwargs: agent
    return agent


@pytest.fixture
def authz_client(agent):
    """A2A behind authorization=True with JWT verification."""
    agent_os = AgentOS(
        id="a2a-authz-os",
        agents=[agent],
        a2a_interface=True,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET], algorithm="HS256", user_isolation=True
        ),
    )
    return TestClient(agent_os.get_app())


@pytest.fixture
def anon_client(agent):
    """A2A with no authorization -- anonymous callers allowed (attribution only)."""
    agent_os = AgentOS(id="a2a-anon-os", agents=[agent], a2a_interface=True)
    return TestClient(agent_os.get_app())


@pytest.fixture
def multi_entity_authz_client():
    """A2A with agent + team + workflow behind authorization=True (for dynamic dispatch)."""
    agent = Agent(id=AGENT_ID, name="Authz Agent", db=InMemoryDb())
    team = Team(id="authz-team", name="Authz Team", members=[agent], db=InMemoryDb())
    workflow = Workflow(id="authz-wf", name="Authz WF", steps=[Step(name="s", agent=agent)], db=InMemoryDb())
    # Return same instance from deep_copy so arun patches work
    agent.deep_copy = lambda **kwargs: agent
    team.deep_copy = lambda **kwargs: team
    workflow.deep_copy = lambda **kwargs: workflow
    agent_os = AgentOS(
        id="a2a-multi-os",
        agents=[agent],
        teams=[team],
        workflows=[workflow],
        a2a_interface=True,
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    return agent, team, workflow, TestClient(agent_os.get_app())


@pytest.fixture
def custom_prefix_authz_client(agent):
    """A2A mounted under a NON-default prefix, behind authorization=True."""
    from agno.os.interfaces.a2a import A2A

    agent_os = AgentOS(
        id="a2a-custom-prefix-os",
        agents=[agent],
        interfaces=[A2A(prefix="/protocol", agents=[agent])],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    return TestClient(agent_os.get_app())


# --------------------------------------------------------------------------- B1


class TestA2AAuthorization:
    def test_message_send_blocked_without_run_scope(self, authz_client):
        resp = authz_client.post(
            f"/a2a/agents/{AGENT_ID}/v1/message:send",
            json=_message_body(),
            headers={"Authorization": f"Bearer {_token(['config:read'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_message_stream_blocked_without_run_scope(self, authz_client):
        resp = authz_client.post(
            f"/a2a/agents/{AGENT_ID}/v1/message:stream",
            json=_message_body(),
            headers={"Authorization": f"Bearer {_token(['config:read'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_card_blocked_without_read_scope(self, authz_client):
        # A run-only token must not read the agent card (requires agents:read).
        resp = authz_client.get(
            f"/a2a/agents/{AGENT_ID}/.well-known/agent-card.json",
            headers={"Authorization": f"Bearer {_token(['agents:run'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_tasks_get_blocked_without_read_scope(self, authz_client):
        resp = authz_client.post(
            f"/a2a/agents/{AGENT_ID}/v1/tasks:get",
            json={"id": "r1", "params": {"id": "task-1", "contextId": "ctx-1"}},
            headers={"Authorization": f"Bearer {_token(['agents:run'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_tasks_cancel_blocked_without_run_scope(self, authz_client):
        resp = authz_client.post(
            f"/a2a/agents/{AGENT_ID}/v1/tasks:cancel",
            json={"id": "r1", "params": {"id": "task-1", "contextId": "ctx-1"}},
            headers={"Authorization": f"Bearer {_token(['agents:read'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_deprecated_send_blocked_without_run_scope(self, authz_client):
        resp = authz_client.post(
            "/a2a/message/send",
            json=_message_body(),
            headers={"X-Agent-ID": AGENT_ID, "Authorization": f"Bearer {_token(['config:read'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_message_send_allowed_with_run_scope(self, agent, authz_client):
        # A run-scoped token clears authorization and the agent actually runs
        with patch.object(agent, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = RunOutput(run_id="r", session_id="ctx", agent_id=AGENT_ID, content="ok")
            resp = authz_client.post(
                f"/a2a/agents/{AGENT_ID}/v1/message:send",
                json=_message_body(),
                headers={"Authorization": f"Bearer {_token(['agents:run'])}"},
            )
            assert resp.status_code == 200
            mock_arun.assert_called_once()


# --------------------------------------------------------------------------- B2


class TestA2AIdentity:
    def test_client_user_id_ignored_for_scoped_caller(self, agent, authz_client):
        # Authenticated user-1 sends X-User-ID: victim -> run must be attributed to user-1.
        with patch.object(agent, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = RunOutput(run_id="r", session_id="ctx", agent_id=AGENT_ID, content="ok")
            resp = authz_client.post(
                f"/a2a/agents/{AGENT_ID}/v1/message:send",
                json=_message_body(),
                headers={"Authorization": f"Bearer {_token(['agents:run'])}", "X-User-ID": "victim"},
            )
            assert resp.status_code == 200, resp.text
            mock_arun.assert_called_once()
            assert mock_arun.call_args.kwargs["user_id"] == "user-1"

    def test_reserved_principal_header_rejected(self, anon_client):
        resp = anon_client.post(
            f"/a2a/agents/{AGENT_ID}/v1/message:send",
            json=_message_body(),
            headers={"X-User-ID": "sa:evil"},
        )
        assert resp.status_code == 403, resp.text

    def test_scheduler_principal_header_rejected(self, anon_client):
        resp = anon_client.post(
            f"/a2a/agents/{AGENT_ID}/v1/message:send",
            json=_message_body(),
            headers={"X-User-ID": "__scheduler__"},
        )
        assert resp.status_code == 403, resp.text

    def test_reserved_principal_metadata_rejected(self, anon_client):
        body = _message_body()
        body["params"]["message"]["metadata"] = {"userId": "sa:evil"}
        resp = anon_client.post(f"/a2a/agents/{AGENT_ID}/v1/message:send", json=body)
        assert resp.status_code == 403, resp.text

    def test_plain_client_user_id_still_honored_when_anonymous(self, agent, anon_client):
        # Backward-compat: with no auth, a non-reserved X-User-ID is still used for attribution.
        with patch.object(agent, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = RunOutput(run_id="r", session_id="ctx", agent_id=AGENT_ID, content="ok")
            resp = anon_client.post(
                f"/a2a/agents/{AGENT_ID}/v1/message:send",
                json=_message_body(),
                headers={"X-User-ID": "user-456"},
            )
            assert resp.status_code == 200, resp.text
            assert mock_arun.call_args.kwargs["user_id"] == "user-456"


# ------------------------------------------------------- B1 root-cause guard


def test_every_a2a_route_has_a_scope_mapping():
    """Regression guard for the root cause of B1: the unmapped-route default is *allow*,
    so any A2A route added without a scope-map entry would silently ship ungated.

    A2A scope mappings live in the interface (A2A.get_scope_mappings()), not in the
    central get_default_scope_mappings(). This test verifies that the A2A interface
    declares scope mappings for all its routes.
    """
    from agno.os.interfaces.a2a.scopes import get_a2a_scope_mappings
    from agno.os.scopes import get_required_scopes_for_route

    agent = Agent(id=AGENT_ID, name="Authz Agent", db=InMemoryDb())
    team = Team(id="authz-team", name="Authz Team", members=[agent], db=InMemoryDb())
    workflow = Workflow(id="authz-wf", name="Authz WF", steps=[Step(name="s", agent=agent)], db=InMemoryDb())
    agent_os = AgentOS(id="a2a-guard-os", agents=[agent], teams=[team], workflows=[workflow], a2a_interface=True)

    # A2A interface scope mappings for the default /a2a prefix
    mappings = get_a2a_scope_mappings("/a2a")
    unmapped = []
    for route in agent_os.get_routes():
        path = getattr(route, "path", "")
        if not path.startswith("/a2a/"):
            continue
        for method in getattr(route, "methods", set()) or set():
            if method in ("HEAD", "OPTIONS"):
                continue
            if not get_required_scopes_for_route(mappings, method, path):
                unmapped.append(f"{method} {path}")

    assert not unmapped, f"A2A routes missing scope mappings: {unmapped}"


# ------------------------------------------------------- custom-prefix gating


class TestA2ACustomPrefix:
    """A2A(prefix=...) is operator-configurable; a custom prefix must be gated too,
    not fall through to the unmapped-route default-allow."""

    def test_custom_prefix_blocked_without_run_scope(self, custom_prefix_authz_client):
        resp = custom_prefix_authz_client.post(
            f"/protocol/agents/{AGENT_ID}/v1/message:send",
            json=_message_body(),
            headers={"Authorization": f"Bearer {_token(['config:read'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_custom_prefix_allowed_with_run_scope(self, agent, custom_prefix_authz_client):
        with patch.object(agent, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = RunOutput(run_id="r", session_id="ctx", agent_id=AGENT_ID, content="ok")
            resp = custom_prefix_authz_client.post(
                f"/protocol/agents/{AGENT_ID}/v1/message:send",
                json=_message_body(),
                headers={"Authorization": f"Bearer {_token(['agents:run'])}"},
            )
            assert resp.status_code == 200
            mock_arun.assert_called_once()


class TestA2ARootPrefix:
    """A2A(prefix="") mounts routes at the app root. The scope map must be built from the
    verbatim prefix -- a fallback (e.g. `prefix or "/a2a"`) would key the map under /a2a
    while the routes live at the root, leaving every route unmapped -> default-allow."""

    @pytest.fixture
    def root_prefix_authz_client(self, agent):
        from agno.os.interfaces.a2a import A2A

        agent_os = AgentOS(
            id="a2a-root-prefix-os",
            agents=[agent],
            interfaces=[A2A(prefix="", agents=[agent])],
            authorization=True,
            authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
        )
        return TestClient(agent_os.get_app())

    def test_root_prefix_blocked_without_run_scope(self, root_prefix_authz_client):
        resp = root_prefix_authz_client.post(
            f"/agents/{AGENT_ID}/v1/message:send",
            json=_message_body(),
            headers={"Authorization": f"Bearer {_token(['config:read'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_root_prefix_allowed_with_run_scope(self, agent, root_prefix_authz_client):
        with patch.object(agent, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = RunOutput(run_id="r", session_id="ctx", agent_id=AGENT_ID, content="ok")
            resp = root_prefix_authz_client.post(
                f"/agents/{AGENT_ID}/v1/message:send",
                json=_message_body(),
                headers={"Authorization": f"Bearer {_token(['agents:run'])}"},
            )
            assert resp.status_code == 200
            mock_arun.assert_called_once()


# ------------------------------------------- deprecated dynamic-dispatch family gate


class TestA2ADeprecatedDispatchFamilyScope:
    """The deprecated /a2a/message/send route dispatches to agent/team/workflow at
    runtime; the resolved family's run scope must be enforced in the handler, not just
    the coarse agents:run route gate."""

    def test_agents_run_cannot_execute_workflow(self, multi_entity_authz_client):
        _agent, _team, workflow, client = multi_entity_authz_client
        resp = client.post(
            "/a2a/message/send",
            json=_message_body(),
            headers={"X-Agent-ID": workflow.id, "Authorization": f"Bearer {_token(['agents:run'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_agents_run_cannot_execute_team(self, multi_entity_authz_client):
        _agent, team, _workflow, client = multi_entity_authz_client
        resp = client.post(
            "/a2a/message/send",
            json=_message_body(),
            headers={"X-Agent-ID": team.id, "Authorization": f"Bearer {_token(['agents:run'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_matching_family_scope_allowed(self, multi_entity_authz_client):
        # The deprecated route's coarse gate requires agents:run; to run a team through it a
        # token needs agents:run (gate) AND teams:run (resolved-family handler check). Teams-
        # only tokens should use the typed /a2a/teams/... route instead.
        _agent, team, _workflow, client = multi_entity_authz_client
        with patch.object(team, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = RunOutput(run_id="r", session_id="ctx", content="ok")
            resp = client.post(
                "/a2a/message/send",
                json=_message_body(),
                headers={"X-Agent-ID": team.id, "Authorization": f"Bearer {_token(['agents:run', 'teams:run'])}"},
            )
            assert resp.status_code == 200
            mock_arun.assert_called_once()


# ----------------------------------------------------------- tasks:get read scoping


class TestA2ATasksGetScoping:
    def test_admin_can_poll_another_users_task(self, agent, authz_client):
        # Admin read must be unfiltered (user_id=None passed to aget_run_output), matching REST.
        with patch.object(agent, "aget_run_output", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = RunOutput(run_id="task-1", session_id="ctx-1", agent_id=AGENT_ID, content="x")
            resp = authz_client.post(
                f"/a2a/agents/{AGENT_ID}/v1/tasks:get",
                json={"id": "r1", "params": {"id": "task-1", "contextId": "ctx-1"}},
                headers={"Authorization": f"Bearer {_token(['agent_os:admin'], sub='admin-1')}"},
            )
            assert resp.status_code == 200, resp.text
            assert mock_get.call_args.kwargs["user_id"] is None

    def test_scoped_caller_pins_own_user_id(self, agent, authz_client):
        # The scoped path first verifies ownership (aget_session), then reads the run.
        owned_session = AgentSession(
            session_id="ctx-1",
            agent_id=AGENT_ID,
            user_id="user-1",
            runs=[RunOutput(run_id="task-1", agent_id=AGENT_ID)],
        )
        with (
            patch.object(agent, "aget_session", new_callable=AsyncMock, return_value=owned_session),
            patch.object(agent, "aget_run_output", new_callable=AsyncMock) as mock_get,
        ):
            mock_get.return_value = RunOutput(run_id="task-1", session_id="ctx-1", agent_id=AGENT_ID, content="x")
            resp = authz_client.post(
                f"/a2a/agents/{AGENT_ID}/v1/tasks:get",
                json={"id": "r1", "params": {"id": "task-1", "contextId": "ctx-1"}},
                headers={"Authorization": f"Bearer {_token(['agents:read', 'agents:run'], sub='user-1')}"},
            )
            assert resp.status_code == 200, resp.text
            assert mock_get.call_args.kwargs["user_id"] == "user-1"

    def test_scoped_caller_cannot_poll_cross_component_run(self, agent, authz_client):
        # A session the caller owns but that belongs to ANOTHER agent must 404 through
        # this agent's tasks:get -- otherwise agents:<id>:read on one agent reads runs
        # of any component the caller ever talked to (per-resource RBAC bypass).
        foreign_session = AgentSession(
            session_id="ctx-1",
            agent_id="other-agent",
            user_id="user-1",
            runs=[RunOutput(run_id="task-1", agent_id="other-agent")],
        )
        with (
            patch.object(agent, "aget_session", new_callable=AsyncMock, return_value=foreign_session),
            patch.object(agent, "aget_run_output", new_callable=AsyncMock) as mock_get,
        ):
            resp = authz_client.post(
                f"/a2a/agents/{AGENT_ID}/v1/tasks:get",
                json={"id": "r1", "params": {"id": "task-1", "contextId": "ctx-1"}},
                headers={"Authorization": f"Bearer {_token(['agents:read'], sub='user-1')}"},
            )
            assert resp.status_code == 404, resp.text
            mock_get.assert_not_called()

    def test_scoped_caller_cannot_poll_unowned_session(self, agent, authz_client):
        # aget_session filters by user_id, so a session owned by someone else resolves to
        # None for the caller -> 404 before any run content is read.
        with (
            patch.object(agent, "aget_session", new_callable=AsyncMock, return_value=None),
            patch.object(agent, "aget_run_output", new_callable=AsyncMock) as mock_get,
        ):
            resp = authz_client.post(
                f"/a2a/agents/{AGENT_ID}/v1/tasks:get",
                json={"id": "r1", "params": {"id": "task-1", "contextId": "ctx-1"}},
                headers={"Authorization": f"Bearer {_token(['agents:read'], sub='user-1')}"},
            )
            assert resp.status_code == 404, resp.text
            mock_get.assert_not_called()

    def test_missing_context_id_returns_400_not_500(self, authz_client):
        resp = authz_client.post(
            f"/a2a/agents/{AGENT_ID}/v1/tasks:get",
            json={"id": "r1", "params": {"id": "task-1"}},
            headers={"Authorization": f"Bearer {_token(['agents:read'])}"},
        )
        assert resp.status_code == 400, resp.text
