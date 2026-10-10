"""A2A authorization + run-identity gate (v2.7 release blockers B1 / B2).

B1: A2A authenticates (behind AuthMiddleware, see test_a2a_auth.py) but historically
enforced *no* authorization scopes -- a ``config:read``-only token could fully execute
agents/teams/workflows over ``/a2a/*``. These tests assert every A2A route is gated: the
Agent Cards by the scope map, and each entity's A2A endpoint per A2A method (all methods
share one route, so the scope map cannot tell reading a task from running the entity).

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
from agno.run.agent import RunCompletedEvent, RunOutput
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


def _message_body(method="message/send"):
    return {
        "jsonrpc": "2.0",
        "method": method,
        "id": "request-123",
        "params": {
            "message": {
                "messageId": "msg-123",
                "role": "user",
                "parts": [{"kind": "text", "text": "Hello!"}],
            }
        },
    }


def _task_body(method, task_id="task-1"):
    return {"jsonrpc": "2.0", "method": method, "id": "r1", "params": {"id": task_id}}


async def _run_stream():
    yield RunCompletedEvent(run_id="r", session_id="ctx", agent_id=AGENT_ID, content="ok")


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
            f"/a2a/agents/{AGENT_ID}",
            json=_message_body(),
            headers={"Authorization": f"Bearer {_token(['config:read'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_message_stream_blocked_without_run_scope(self, authz_client):
        resp = authz_client.post(
            f"/a2a/agents/{AGENT_ID}",
            json=_message_body("message/stream"),
            headers={"Authorization": f"Bearer {_token(['config:read'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_card_declares_bearer_auth(self, authz_client):
        resp = authz_client.get(
            f"/a2a/agents/{AGENT_ID}/.well-known/agent-card.json",
            headers={"Authorization": f"Bearer {_token(['agents:read'])}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["securitySchemes"]["bearerAuth"]["httpAuthSecurityScheme"]["scheme"] == "bearer"

    def test_card_blocked_without_read_scope(self, authz_client):
        # A run-only token must not read the agent card (requires agents:read).
        resp = authz_client.get(
            f"/a2a/agents/{AGENT_ID}/.well-known/agent-card.json",
            headers={"Authorization": f"Bearer {_token(['agents:run'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_tasks_get_blocked_without_read_scope(self, authz_client):
        resp = authz_client.post(
            f"/a2a/agents/{AGENT_ID}",
            json=_task_body("tasks/get"),
            headers={"Authorization": f"Bearer {_token(['agents:run'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_tasks_cancel_blocked_without_run_scope(self, authz_client):
        resp = authz_client.post(
            f"/a2a/agents/{AGENT_ID}",
            json=_task_body("tasks/cancel"),
            headers={"Authorization": f"Bearer {_token(['agents:read'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_tasks_get_blocked_without_read_scope_v1(self, authz_client):
        # The A2A v1.0 method names are gated the same way
        resp = authz_client.post(
            f"/a2a/agents/{AGENT_ID}",
            json=_task_body("GetTask"),
            headers={"Authorization": f"Bearer {_token(['agents:run'])}", "A2A-Version": "1.0"},
        )
        assert resp.status_code == 403, resp.text

    def test_message_send_blocked_without_run_scope_v1(self, authz_client):
        body = _message_body("SendMessage")
        body["params"]["message"] = {"messageId": "msg-123", "role": "ROLE_USER", "parts": [{"text": "Hello!"}]}
        resp = authz_client.post(
            f"/a2a/agents/{AGENT_ID}",
            json=body,
            headers={"Authorization": f"Bearer {_token(['agents:read'])}", "A2A-Version": "1.0"},
        )
        assert resp.status_code == 403, resp.text

    def test_message_send_allowed_with_run_scope(self, agent, authz_client):
        # A run-scoped token clears authorization and the agent actually runs
        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = _run_stream()
            resp = authz_client.post(
                f"/a2a/agents/{AGENT_ID}",
                json=_message_body(),
                headers={"Authorization": f"Bearer {_token(['agents:run'])}"},
            )
            assert resp.status_code == 200
            mock_arun.assert_called_once()


# --------------------------------------------------------------------------- B2


class TestA2AIdentity:
    def test_client_user_id_ignored_for_scoped_caller(self, agent, authz_client):
        # Authenticated user-1 sends X-User-ID: victim -> run must be attributed to user-1.
        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = _run_stream()
            resp = authz_client.post(
                f"/a2a/agents/{AGENT_ID}",
                json=_message_body(),
                headers={"Authorization": f"Bearer {_token(['agents:run'])}", "X-User-ID": "victim"},
            )
            assert resp.status_code == 200, resp.text
            mock_arun.assert_called_once()
            assert mock_arun.call_args.kwargs["user_id"] == "user-1"

    def test_reserved_principal_header_rejected(self, anon_client):
        resp = anon_client.post(
            f"/a2a/agents/{AGENT_ID}",
            json=_message_body(),
            headers={"X-User-ID": "sa:evil"},
        )
        assert resp.status_code == 403, resp.text

    def test_scheduler_principal_header_rejected(self, anon_client):
        resp = anon_client.post(
            f"/a2a/agents/{AGENT_ID}",
            json=_message_body(),
            headers={"X-User-ID": "__scheduler__"},
        )
        assert resp.status_code == 403, resp.text

    def test_reserved_principal_metadata_rejected(self, anon_client):
        body = _message_body()
        body["params"]["message"]["metadata"] = {"userId": "sa:evil"}
        resp = anon_client.post(f"/a2a/agents/{AGENT_ID}", json=body)
        assert resp.status_code == 403, resp.text

    def test_plain_client_user_id_still_honored_when_anonymous(self, agent, anon_client):
        # Backward-compat: with no auth, a non-reserved X-User-ID is still used for attribution.
        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = _run_stream()
            resp = anon_client.post(
                f"/a2a/agents/{AGENT_ID}",
                json=_message_body(),
                headers={"X-User-ID": "user-456"},
            )
            assert resp.status_code == 200, resp.text
            assert mock_arun.call_args.kwargs["user_id"] == "user-456"


# ------------------------------------------------------- session guard


class TestA2ASessionGuard:
    """contextId is client-supplied and becomes the session id. The ownership guard must see
    the id the run will use, however the client spells the field."""

    @pytest.mark.parametrize("field", ["contextId", "context_id"])
    def test_context_id_is_guarded_in_both_spellings(self, agent, authz_client, field):
        body = _message_body()
        body["params"]["message"][field] = "someone-elses-session"
        with (
            patch("agno.os.interfaces.a2a.auth.assert_session_writable", new_callable=AsyncMock) as mock_guard,
            patch.object(agent, "arun") as mock_arun,
        ):
            mock_arun.return_value = _run_stream()
            resp = authz_client.post(
                f"/a2a/agents/{AGENT_ID}",
                json=body,
                headers={"Authorization": f"Bearer {_token(['agents:run'])}"},
            )
            assert resp.status_code == 200, resp.text
            assert mock_guard.call_args.args[1] == "someone-elses-session"


# ------------------------------------------------------- B1 root-cause guard


def test_every_a2a_route_is_gated():
    """Regression guard for the root cause of B1: the unmapped-route default is *allow*,
    so any A2A route added without a gate would silently ship ungated.

    A2A routes are not in a scope map: they are authorized in the route, so the gate holds
    under any prefix. Every A2A route must either be an Agent Card route, gated by
    authorize_a2a_access, or an entity's A2A endpoint -- gated per A2A method by
    authorize_a2a_request, because all A2A methods share that one route.
    """
    agent = Agent(id=AGENT_ID, name="Authz Agent", db=InMemoryDb())
    team = Team(id="authz-team", name="Authz Team", members=[agent], db=InMemoryDb())
    workflow = Workflow(id="authz-wf", name="Authz WF", steps=[Step(name="s", agent=agent)], db=InMemoryDb())
    agent_os = AgentOS(id="a2a-guard-os", agents=[agent], teams=[team], workflows=[workflow], a2a_interface=True)

    ungated = []
    endpoints = []
    for route in agent_os.get_routes():
        path = getattr(route, "path", "")
        if not path.startswith("/a2a/"):
            continue
        for method in getattr(route, "methods", set()) or set():
            if method in ("HEAD", "OPTIONS"):
                continue
            if getattr(route.endpoint, "__name__", "") in ("get_agent_card", "get_team_card", "get_workflow_card"):
                continue
            if getattr(route.endpoint, "__name__", "") == "a2a_endpoint":
                endpoints.append(f"{method} {path}")
                continue
            ungated.append(f"{method} {path}")

    assert not ungated, f"A2A routes missing a gate: {ungated}"
    assert sorted(endpoints) == [
        f"POST /a2a/agents/{AGENT_ID}",
        "POST /a2a/teams/authz-team",
        "POST /a2a/workflows/authz-wf",
    ]


# ------------------------------------------------------- provider route decision


class TestA2AProviderRouteDecision:
    """The A2A endpoint is not in the scope map, so the route gate never asks the
    authorization provider about it. A provider whose route decision denies must still
    block the run, as it does on the REST run route."""

    @pytest.mark.parametrize("method", ["message/send", "message/stream"])
    def test_send_blocked_when_provider_denies_the_route(self, agent, method):
        from agno.os.authz import Authorization, AuthorizationContext, AuthorizationProvider

        class _RouteDeny(AuthorizationProvider):
            def check(self, ctx: AuthorizationContext) -> bool:
                return True

            def accessible_resource_ids(self, ctx: AuthorizationContext):
                return {"*"}

            def authorize_route(self, ctx: AuthorizationContext, required_scopes) -> bool:
                return False

        authz = Authorization(verification_keys=[JWT_SECRET], algorithm="HS256", authorization_provider=_RouteDeny())
        agent_os = AgentOS(id="a2a-route-deny-os", agents=[agent], a2a_interface=True, authorization=authz)
        client = TestClient(agent_os.get_app())

        with patch.object(agent, "arun") as mock_arun:
            resp = client.post(
                f"/a2a/agents/{AGENT_ID}",
                json=_message_body(method),
                headers={"Authorization": f"Bearer {_token(['agents:run'])}"},
            )
            assert resp.status_code == 403, resp.text
            mock_arun.assert_not_called()


# ------------------------------------------------------- custom-prefix gating


class TestA2ACustomPrefix:
    """A2A(prefix=...) is operator-configurable; a custom prefix must be gated too,
    not fall through to the unmapped-route default-allow."""

    def test_custom_prefix_blocked_without_run_scope(self, custom_prefix_authz_client):
        resp = custom_prefix_authz_client.post(
            f"/protocol/agents/{AGENT_ID}",
            json=_message_body(),
            headers={"Authorization": f"Bearer {_token(['config:read'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_custom_prefix_allowed_with_run_scope(self, agent, custom_prefix_authz_client):
        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = _run_stream()
            resp = custom_prefix_authz_client.post(
                f"/protocol/agents/{AGENT_ID}",
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
            f"/agents/{AGENT_ID}",
            json=_message_body(),
            headers={"Authorization": f"Bearer {_token(['config:read'])}"},
        )
        assert resp.status_code == 403, resp.text

    def test_root_prefix_allowed_with_run_scope(self, agent, root_prefix_authz_client):
        with patch.object(agent, "arun") as mock_arun:
            mock_arun.return_value = _run_stream()
            resp = root_prefix_authz_client.post(
                f"/agents/{AGENT_ID}",
                json=_message_body(),
                headers={"Authorization": f"Bearer {_token(['agents:run'])}"},
            )
            assert resp.status_code == 200
            mock_arun.assert_called_once()


# ----------------------------------------------------------- GetTask read scoping


class TestA2ATasksGetScoping:
    """A task this process no longer holds is read back from the run the entity stored.
    The read is pinned to the caller and to the entity the request targets."""

    @staticmethod
    def _stored_run(user_id="user-1", agent_id=AGENT_ID):
        return RunOutput(run_id="task-1", session_id="ctx-1", agent_id=agent_id, user_id=user_id, content="x")

    def test_admin_can_poll_another_users_task(self, agent, authz_client):
        # Admin read must be unfiltered, matching REST.
        with patch.object(agent.db, "get_run", return_value=self._stored_run()):
            resp = authz_client.post(
                f"/a2a/agents/{AGENT_ID}",
                json=_task_body("tasks/get"),
                headers={"Authorization": f"Bearer {_token(['agent_os:admin'], sub='admin-1')}"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["result"]["id"] == "task-1"

    def test_scoped_caller_reads_own_task(self, agent, authz_client):
        with patch.object(agent.db, "get_run", return_value=self._stored_run()):
            resp = authz_client.post(
                f"/a2a/agents/{AGENT_ID}",
                json=_task_body("tasks/get"),
                headers={"Authorization": f"Bearer {_token(['agents:read', 'agents:run'], sub='user-1')}"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["result"]["id"] == "task-1"

    def test_scoped_caller_cannot_poll_cross_component_run(self, agent, authz_client):
        # A run the caller owns but that belongs to ANOTHER agent must not be found through
        # this agent's endpoint -- otherwise agents:<id>:read on one agent reads runs
        # of any component the caller ever talked to (per-resource RBAC bypass).
        with patch.object(agent.db, "get_run", return_value=self._stored_run(agent_id="other-agent")):
            resp = authz_client.post(
                f"/a2a/agents/{AGENT_ID}",
                json=_task_body("GetTask"),
                headers={"Authorization": f"Bearer {_token(['agents:read'], sub='user-1')}", "A2A-Version": "1.0"},
            )
            assert resp.json()["error"]["code"] == -32001, resp.text

    def test_scoped_caller_cannot_poll_another_users_task(self, agent, authz_client):
        with patch.object(agent.db, "get_run", return_value=self._stored_run(user_id="user-2")):
            resp = authz_client.post(
                f"/a2a/agents/{AGENT_ID}",
                json=_task_body("GetTask"),
                headers={"Authorization": f"Bearer {_token(['agents:read'], sub='user-1')}", "A2A-Version": "1.0"},
            )
            assert resp.json()["error"]["code"] == -32001, resp.text

    def test_unknown_task_returns_task_not_found_not_500(self, authz_client):
        resp = authz_client.post(
            f"/a2a/agents/{AGENT_ID}",
            json=_task_body("GetTask"),
            headers={"Authorization": f"Bearer {_token(['agents:read'])}", "A2A-Version": "1.0"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["error"]["code"] == -32001
