"""Integration tests for per-user data isolation.

Validates that:
- Regular users only see their own sessions, traces, and memories
- Admin users (agent_os:admin scope) see all data
- User_id from the JWT cannot be spoofed via query parameters
- Endpoints without auth return unfiltered data
- Review-identified gaps stay closed (run listing, SSE resume, custom
  admin_scope propagation, memory act-on-behalf, factory cancel,
  continue-run ownership, cross-component RBAC, WS reconnect, etc.)

The "review gap" classes live alongside the original isolation tests so
there's one canonical place to add new isolation regressions.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.team.team import Team
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

JWT_SECRET = "test-secret-for-isolation"
TEST_OS_ID = "test-isolation-os"
CUSTOM_ADMIN_SCOPE = "custom:admin"


def create_token(user_id: str, scopes: list[str] | None = None) -> str:
    """Create a JWT token for the given user.

    Default scopes cover agents / teams / workflows / sessions / memories /
    traces — the union needed by the test classes in this file. Pass
    ``scopes=[...]`` explicitly to test narrower-scope behaviour.
    """
    payload = {
        "sub": user_id,
        "aud": TEST_OS_ID,
        "scopes": scopes
        or [
            "agents:read",
            "agents:run",
            "teams:read",
            "teams:run",
            "workflows:read",
            "workflows:run",
            "sessions:read",
            "sessions:write",
            "memories:read",
            "memories:write",
            "traces:read",
        ],
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def create_admin_token(user_id: str = "admin-user") -> str:
    """Create a JWT token with admin scope."""
    return create_token(user_id, scopes=["agent_os:admin"])


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def test_agent(shared_db):
    return Agent(
        name="test-agent",
        id="test-agent",
        db=shared_db,
        instructions="You are a test agent.",
    )


@pytest.fixture
def test_team(shared_db, test_agent: Agent):
    return Team(name="test-team", id="test-team", members=[test_agent], db=shared_db)


@pytest.fixture
def test_workflow(shared_db, test_agent: Agent):
    return Workflow(
        name="test-workflow",
        id="test-workflow",
        steps=[Step(name="step1", description="noop", agent=test_agent)],
        db=shared_db,
    )


@pytest.fixture
def client(test_agent, test_team, test_workflow):
    """Default isolation-enabled client with one agent, team, and workflow.

    The team and workflow are registered so the review-gap tests (workflow
    run listing, continue-run, factory cancel, etc.) can exercise their
    endpoints. The original session / trace / memory tests are unaffected.
    """
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        teams=[test_team],
        workflows=[test_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
            user_isolation=True,
        ),
    )
    app = agent_os.get_app()
    return TestClient(app)


@pytest.fixture
def custom_admin_client(test_agent):
    """Client with ``admin_scope`` configured to a non-default value.

    Used by the custom-admin-scope propagation tests below — they need the
    middleware to recognise ``custom:admin`` (rather than the framework
    default ``agent_os:admin``) as the bypass scope.
    """
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
            admin_scope=CUSTOM_ADMIN_SCOPE,
            user_isolation=True,
        ),
    )
    return TestClient(agent_os.get_app())


# --- Session isolation ---


class TestSessionIsolation:
    """Verify that session endpoints are scoped to the JWT user_id."""

    def test_user_sees_only_own_sessions(self, client):
        """User A creates a session, User B should not see it."""
        token_a = create_token("user-a", scopes=["agent_os:admin"])
        token_b = create_token("user-b")

        # User A creates a session
        resp = client.post(
            "/sessions?type=agent",
            json={"agent_id": "test-agent", "user_id": "user-a"},
            headers=auth_header(token_a),
        )
        assert resp.status_code == 201, resp.text
        session_id = resp.json().get("session_id") or resp.json().get("agent_session_id")
        assert session_id

        # User B lists sessions — should not see User A's session
        resp = client.get(
            "/sessions?type=agent",
            headers=auth_header(token_b),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        session_ids = [s["session_id"] for s in data]
        assert session_id not in session_ids

    def test_admin_sees_all_sessions(self, client):
        """Admin should see sessions from all users."""
        token_a = create_token("user-a", scopes=["agent_os:admin"])
        admin_token = create_admin_token("admin-1")

        # User A creates a session
        resp = client.post(
            "/sessions?type=agent",
            json={"agent_id": "test-agent", "user_id": "user-a"},
            headers=auth_header(token_a),
        )
        assert resp.status_code == 201
        session_id = resp.json().get("session_id") or resp.json().get("agent_session_id")

        # Admin lists sessions — should see it
        resp = client.get(
            "/sessions?type=agent",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        session_ids = [s["session_id"] for s in data]
        assert session_id in session_ids

    def test_user_cannot_spoof_user_id_on_session_list(self, client):
        """Passing user_id as query param should be overridden by JWT."""
        token_a = create_token("user-a", scopes=["agent_os:admin"])
        token_b = create_token("user-b")

        # User A creates a session
        resp = client.post(
            "/sessions?type=agent",
            json={"agent_id": "test-agent", "user_id": "user-a"},
            headers=auth_header(token_a),
        )
        assert resp.status_code == 201
        session_id = resp.json().get("session_id") or resp.json().get("agent_session_id")

        # User B tries to list with user_id=user-a — should still be filtered to user-b
        resp = client.get(
            "/sessions?type=agent&user_id=user-a",
            headers=auth_header(token_b),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        session_ids = [s["session_id"] for s in data]
        assert session_id not in session_ids

    def test_user_cannot_get_other_users_session_by_id(self, client):
        """User B should get 404 when trying to access User A's session by ID."""
        token_a = create_token("user-a", scopes=["agent_os:admin"])
        token_b = create_token("user-b")

        # User A creates a session
        resp = client.post(
            "/sessions?type=agent",
            json={"agent_id": "test-agent", "user_id": "user-a"},
            headers=auth_header(token_a),
        )
        assert resp.status_code == 201
        session_id = resp.json().get("session_id") or resp.json().get("agent_session_id")

        # User B tries to get it by ID — should get 404
        resp = client.get(
            f"/sessions/{session_id}?type=agent",
            headers=auth_header(token_b),
        )
        assert resp.status_code == 404

    def test_create_session_conflict_does_not_leak_across_users(self, client):
        """Re-creating User A's session_id as User B must 409 without leaking A's session.

        POST /sessions rejects a duplicate session_id with 409 (mirrors create_learning)
        and returns no session body, so a non-owner re-posting an existing id cannot read
        User A's user_id / session_name / history through this path under user isolation.
        """
        token_a = create_token("user-a", scopes=["agent_os:admin"])
        token_b = create_token("user-b")

        # User A creates a session with a client-supplied id.
        session_id = "shared-conflict-id"
        resp = client.post(
            "/sessions?type=agent",
            json={
                "session_id": session_id,
                "agent_id": "test-agent",
                "user_id": "user-a",
                "session_name": "user-a-private",
            },
            headers=auth_header(token_a),
        )
        assert resp.status_code == 201, resp.text

        # User B re-creates the same id — must be a bodyless 409, never User A's session.
        resp = client.post(
            "/sessions?type=agent",
            json={"session_id": session_id},
            headers=auth_header(token_b),
        )
        assert resp.status_code == 409, resp.text
        assert "user-a" not in resp.text
        assert "user-a-private" not in resp.text

    def test_user_cannot_delete_other_users_session(self, client):
        """User B should not be able to delete User A's session."""
        token_a = create_token("user-a", scopes=["agent_os:admin"])
        token_b = create_token("user-b")

        # User A creates a session
        resp = client.post(
            "/sessions?type=agent",
            json={"agent_id": "test-agent", "user_id": "user-a"},
            headers=auth_header(token_a),
        )
        assert resp.status_code == 201
        session_id = resp.json().get("session_id") or resp.json().get("agent_session_id")

        # User B tries to delete it
        resp = client.delete(
            f"/sessions/{session_id}",
            headers=auth_header(token_b),
        )
        # Should either 404 or silently no-op (depends on DB adapter)
        # Either way, the session should still exist for admin
        admin_token = create_admin_token()
        resp = client.get(
            f"/sessions/{session_id}?type=agent",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200


# --- Trace isolation ---


class TestTraceIsolation:
    """Verify that trace endpoints are scoped to the JWT user_id."""

    def test_user_sees_only_own_traces(self, client):
        """Regular user should only see their own traces."""
        token_a = create_token("user-a")
        token_b = create_token("user-b")

        # Both users list traces — should get empty (no runs yet) but no errors
        resp_a = client.get("/traces", headers=auth_header(token_a))
        assert resp_a.status_code == 200

        resp_b = client.get("/traces", headers=auth_header(token_b))
        assert resp_b.status_code == 200

    def test_admin_sees_all_traces(self, client):
        """Admin should see traces from all users."""
        admin_token = create_admin_token()
        resp = client.get("/traces", headers=auth_header(admin_token))
        assert resp.status_code == 200

    def test_trace_stats_scoped_to_user(self, client):
        """Trace stats should be filtered by user."""
        token_a = create_token("user-a")
        resp = client.get("/trace_session_stats", headers=auth_header(token_a))
        assert resp.status_code == 200


# --- Memory isolation ---


class TestMemoryIsolation:
    """Verify that memory endpoints are scoped to the JWT user_id."""

    def test_user_sees_only_own_memories(self, client):
        """Regular user should only see their own memories."""
        token_a = create_token("user-a")
        token_b = create_token("user-b")

        # User A creates a memory
        resp = client.post(
            "/memories",
            json={"memory": "User A likes coffee", "user_id": "user-a"},
            headers=auth_header(token_a),
        )
        assert resp.status_code in (200, 201), resp.text
        memory_id = resp.json().get("id") or resp.json().get("memory_id")

        # User B lists memories — should not see User A's memory
        resp = client.get("/memories", headers=auth_header(token_b))
        assert resp.status_code == 200
        data = resp.json()["data"]
        memory_ids = [m.get("id") or m.get("memory_id") for m in data]
        assert memory_id not in memory_ids

    def test_admin_sees_all_memories(self, client):
        """Admin should see memories from all users."""
        token_a = create_token("user-a")
        admin_token = create_admin_token()

        # User A creates a memory
        resp = client.post(
            "/memories",
            json={"memory": "User A likes tea", "user_id": "user-a"},
            headers=auth_header(token_a),
        )
        assert resp.status_code in (200, 201), resp.text
        memory_id = resp.json().get("id") or resp.json().get("memory_id")

        # Admin lists memories — should see it
        resp = client.get("/memories", headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()["data"]
        memory_ids = [m.get("id") or m.get("memory_id") for m in data]
        assert memory_id in memory_ids


# --- Async DB dispatch ---


class TestAsyncDbDispatch:
    """Regression coverage for the sync/async router dispatch against wrapped
    AsyncBaseDb instances. Without virtual-subclass registration, routers fall
    into the sync branch and crash trying to unpack a coroutine.
    """

    @pytest.fixture
    def async_client(self, tmp_path):
        import uuid

        from agno.db.sqlite.async_sqlite import AsyncSqliteDb

        db = AsyncSqliteDb(
            db_file=str(tmp_path / f"async_iso_{uuid.uuid4().hex[:8]}.db"),
        )
        agent = Agent(name="test-agent", id="test-agent", db=db, instructions="hi")
        agent_os = AgentOS(
            id=TEST_OS_ID,
            agents=[agent],
            authorization=True,
            authorization_config=AuthorizationConfig(
                verification_keys=[JWT_SECRET],
                algorithm="HS256",
                user_isolation=True,
            ),
        )
        return TestClient(agent_os.get_app())

    def test_sessions_list_works_on_async_db(self, async_client):
        """GET /sessions must route through the async branch for AsyncBaseDb."""
        token = create_token("user-a")
        resp = async_client.get("/sessions?type=agent", headers=auth_header(token))
        assert resp.status_code == 200, resp.text
        assert "data" in resp.json()

    def test_memories_list_works_on_async_db(self, async_client):
        token = create_token("user-a")
        resp = async_client.get("/memories", headers=auth_header(token))
        assert resp.status_code == 200, resp.text
        assert "data" in resp.json()

    def test_traces_list_works_on_async_db(self, async_client):
        token = create_token("user-a")
        resp = async_client.get("/traces", headers=auth_header(token))
        assert resp.status_code == 200, resp.text


# --- Cancel ownership ---


class TestCancelOwnership:
    """Cancel endpoints must not let one user cancel another user's run."""

    def test_non_admin_cancel_requires_session_id(self, client):
        token = create_token("user-a")
        resp = client.post(
            "/agents/test-agent/runs/some-run/cancel",
            headers=auth_header(token),
        )
        assert resp.status_code == 400
        assert "session_id" in resp.json()["detail"].lower()

    def test_non_admin_cancel_foreign_run_returns_404(self, client):
        # user-a creates a session + synthetic run, user-b tries to cancel by id
        token_a = create_token("user-a", scopes=["agent_os:admin"])
        token_b = create_token("user-b")

        resp = client.post(
            "/sessions?type=agent",
            json={"agent_id": "test-agent", "user_id": "user-a"},
            headers=auth_header(token_a),
        )
        assert resp.status_code == 201
        session_id = resp.json().get("session_id") or resp.json().get("agent_session_id")

        resp = client.post(
            f"/agents/test-agent/runs/run-does-not-exist/cancel?session_id={session_id}",
            headers=auth_header(token_b),
        )
        assert resp.status_code == 404

    def test_admin_cancel_without_session_id_still_succeeds(self, client):
        admin_token = create_admin_token()
        resp = client.post(
            "/agents/test-agent/runs/some-run/cancel",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200


# --- Listing endpoint RBAC ---


class TestListingEndpointRbacByAction:
    """Listing endpoints (e.g. GET /agents) must enforce the action they declare.

    Without the action filter, the JWT middleware's listing fallback used to
    accept any read/run scope, letting a token with only ``agents:run`` list
    every agent it could run. The middleware now scopes the cached
    ``accessible_resource_ids`` to the action required by the route.
    """

    def test_run_only_token_cannot_list_agents(self, client):
        """A token with only `agents:run` must be denied on `GET /agents`."""
        token = create_token("run-only-user", scopes=["agents:run"])
        resp = client.get("/agents", headers=auth_header(token))
        assert resp.status_code == 403, resp.text

    def test_run_only_token_can_still_run_agents(self, client):
        """The same token must still be authorised to invoke a run."""
        token = create_token("run-only-user", scopes=["agents:run"])
        resp = client.post(
            "/agents/test-agent/runs",
            data={"message": "hi", "stream": "false"},
            headers=auth_header(token),
        )
        # 200 if the run executes; what matters is we don't get 403.
        assert resp.status_code != 403, resp.text

    def test_read_token_can_list_agents(self, client):
        """A token with `agents:read` must succeed on `GET /agents`."""
        token = create_token("read-user", scopes=["agents:read"])
        resp = client.get("/agents", headers=auth_header(token))
        assert resp.status_code == 200, resp.text

    def test_per_resource_run_only_does_not_grant_listing(self, client):
        """`agents:test-agent:run` must not unlock the global listing endpoint."""
        token = create_token("per-resource-runner", scopes=["agents:test-agent:run"])
        resp = client.get("/agents", headers=auth_header(token))
        assert resp.status_code == 403, resp.text

    def test_per_resource_read_grants_filtered_listing(self, client):
        """`agents:test-agent:read` must return that agent (and only that one)."""
        token = create_token("per-resource-reader", scopes=["agents:test-agent:read"])
        resp = client.get("/agents", headers=auth_header(token))
        assert resp.status_code == 200, resp.text
        ids = [a.get("id") for a in resp.json()]
        assert "test-agent" in ids


# ---------------------------------------------------------------------------
# Session write ownership — regression for session-cross-user-history-bleed
# ---------------------------------------------------------------------------

SECRET_TEXT = "wire-transfer PIN GRIMSBY-8807"


class ScriptedModel(Model):
    """A model that answers without a provider call.

    The shared ``test_agent`` fixture has no model and no
    ``add_history_to_context``, neither of which is enough to observe a replay.
    """

    def __init__(self, model_id: str, reply: str):
        super().__init__(id=model_id, name=model_id, provider="test")
        self._reply = reply

    def _resp(self) -> ModelResponse:
        return ModelResponse(content=self._reply, role="assistant", response_usage=MessageMetrics())

    def invoke(self, *args, **kwargs):
        return self._resp()

    async def ainvoke(self, *args, **kwargs):
        return self._resp()

    def invoke_stream(self, *args, **kwargs):
        yield self._resp()

    async def ainvoke_stream(self, *args, **kwargs):
        yield self._resp()

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response, **kwargs):
        return self._resp()

    def _parse_provider_response_delta(self, response):
        return self._resp()


@pytest.fixture
def history_agent(shared_db):
    """Replays history and needs no provider."""
    return Agent(
        id="history-agent",
        name="history-agent",
        db=shared_db,
        model=ScriptedModel("scripted-1", "ok"),
        add_history_to_context=True,
        num_history_runs=5,
    )


@pytest.fixture
def history_team(shared_db, history_agent):
    return Team(id="history-team", name="history-team", members=[history_agent], db=shared_db)


@pytest.fixture
def history_workflow(shared_db, history_agent):
    return Workflow(
        id="history-workflow",
        name="history-workflow",
        db=shared_db,
        steps=[Step(name="step1", description="noop", agent=history_agent)],
    )


def _ownership_client(*, user_isolation: bool, agents=None, teams=None, workflows=None, db=None) -> TestClient:
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=agents,
        teams=teams,
        workflows=workflows,
        db=db,
        telemetry=False,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
            user_isolation=user_isolation,
        ),
    )
    return TestClient(agent_os.get_app())


def _open_client(*, agents=None, teams=None, workflows=None, db=None) -> TestClient:
    """No authorization middleware — ``user_id`` is whatever the form field says,
    or absent. The configuration the identity-less variant needs."""
    agent_os = AgentOS(id=TEST_OS_ID, agents=agents, teams=teams, workflows=workflows, db=db, telemetry=False)
    return TestClient(agent_os.get_app(), raise_server_exceptions=False)


def _run(client, path, token=None, **fields):
    data = {"stream": "false", **fields}
    headers = auth_header(token) if token else {}
    return client.post(path, data=data, headers=headers)


def _history(response):
    return [m for m in (response.json().get("messages") or []) if m.get("from_history")]


class TestSessionWriteOwnership:
    """A run posted to another user's ``session_id`` must be refused, and must
    never reach the owner's history.

    Both isolation states are exercised on purpose: the defect reproduced under
    ``user_isolation=True`` as well, because the missing check was on
    ``session_id``, not on ``user_id``.
    """

    @pytest.mark.parametrize("isolation", [True, False])
    def test_non_owner_run_into_foreign_session_is_refused(self, history_agent, isolation):
        client = _ownership_client(user_isolation=isolation, agents=[history_agent], db=history_agent.db)
        sid = "owned-by-c"
        assert (
            _run(client, "/agents/history-agent/runs", create_token("user-c"), message="opened by C", session_id=sid)
        ).status_code == 200

        resp = _run(
            client,
            "/agents/history-agent/runs",
            create_token("user-d"),
            message=f"My private {SECRET_TEXT}",
            session_id=sid,
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "Session not found"
        # The refusal must not disclose who does own it.
        assert "user-c" not in resp.text

    @pytest.mark.parametrize("isolation", [True, False])
    def test_owner_history_never_carries_a_foreign_turn(self, history_agent, isolation):
        client = _ownership_client(user_isolation=isolation, agents=[history_agent], db=history_agent.db)
        sid = "owned-by-c-2"
        _run(client, "/agents/history-agent/runs", create_token("user-c"), message="opened by C", session_id=sid)
        _run(
            client,
            "/agents/history-agent/runs",
            create_token("user-d"),
            message=f"My private {SECRET_TEXT}",
            session_id=sid,
        )

        resp = _run(
            client, "/agents/history-agent/runs", create_token("user-c"), message="what did I say?", session_id=sid
        )
        assert resp.status_code == 200, resp.text
        history = _history(resp)
        assert history, "owner must still replay their own history"
        assert not any(SECRET_TEXT in str(m.get("content")) for m in history)

    @pytest.mark.parametrize("isolation", [True, False])
    def test_no_foreign_run_row_reaches_the_session(self, history_agent, isolation):
        """Storage-level twin: the refusal happens before ``upsert_run``, not
        only before the history read."""
        client = _ownership_client(user_isolation=isolation, agents=[history_agent], db=history_agent.db)
        sid = "owned-by-c-3"
        _run(client, "/agents/history-agent/runs", create_token("user-c"), message="opened by C", session_id=sid)
        _run(
            client,
            "/agents/history-agent/runs",
            create_token("user-d"),
            message=f"My private {SECRET_TEXT}",
            session_id=sid,
        )
        runs = history_agent.db.get_runs(session_id=sid, deserialize=False)[0]
        assert {r["user_id"] for r in runs} == {"user-c"}

    @pytest.mark.parametrize("stream", ["true", "false"])
    def test_refusal_is_a_plain_404_on_every_variant(self, history_agent, stream):
        """``stream`` defaults to True on these routes: the guard must sit before
        the streaming and background branches, so the refusal is a JSON 404 and
        never an SSE frame or a queued ticket."""
        client = _ownership_client(user_isolation=True, agents=[history_agent], db=history_agent.db)
        sid = "owned-by-c-stream"
        _run(client, "/agents/history-agent/runs", create_token("user-c"), message="opened by C", session_id=sid)

        resp = client.post(
            "/agents/history-agent/runs",
            data={"message": "intrude", "stream": stream, "session_id": sid},
            headers=auth_header(create_token("user-d")),
        )
        assert resp.status_code == 404, resp.text
        assert resp.headers["content-type"].startswith("application/json")

    def test_owner_can_still_continue_their_own_session(self, history_agent):
        """Regression guard: the common path must not become a 404."""
        client = _ownership_client(user_isolation=True, agents=[history_agent], db=history_agent.db)
        sid = "owned-by-c-4"
        token = create_token("user-c")
        assert _run(client, "/agents/history-agent/runs", token, message="one", session_id=sid).status_code == 200
        resp = _run(client, "/agents/history-agent/runs", token, message="two", session_id=sid)
        assert resp.status_code == 200
        assert any("one" in str(m.get("content")) for m in _history(resp))

    def test_new_session_id_is_created_not_refused(self, history_agent):
        """A session id nobody owns must 200 and create — the guard must not turn
        every client-supplied id into a 404."""
        client = _ownership_client(user_isolation=True, agents=[history_agent], db=history_agent.db)
        resp = _run(
            client, "/agents/history-agent/runs", create_token("user-c"), message="hello", session_id="brand-new-id"
        )
        assert resp.status_code == 200, resp.text

    def test_admin_may_run_into_any_session(self, history_agent):
        """Admins bypass scoping everywhere else on this surface; keep it true here."""
        client = _ownership_client(user_isolation=True, agents=[history_agent], db=history_agent.db)
        sid = "owned-by-c-5"
        _run(client, "/agents/history-agent/runs", create_token("user-c"), message="opened by C", session_id=sid)
        resp = _run(client, "/agents/history-agent/runs", create_admin_token(), message="admin here", session_id=sid)
        assert resp.status_code == 200, resp.text

    def test_unowned_session_is_claimed_by_the_first_identified_writer(self, history_agent):
        """``user_id IS NULL`` is writable by anyone — but only until someone
        identified writes, because ``upsert_session`` carries ``user_id`` in its
        ON CONFLICT SET list. The guard then treats the row as owned, which is
        the same rule storage applies."""
        db = history_agent.db
        open_client = _open_client(agents=[history_agent], db=db)
        sid = "unowned-then-claimed"
        # An identity-less run creates the row unowned...
        assert _run(open_client, "/agents/history-agent/runs", message="anon one", session_id=sid).status_code == 200
        assert db.get_session(session_id=sid, deserialize=False)["user_id"] is None

        auth_client = _ownership_client(user_isolation=True, agents=[history_agent], db=db)
        # ...the first identified writer is admitted, and claims it...
        assert (
            _run(auth_client, "/agents/history-agent/runs", create_token("user-c"), message="c", session_id=sid)
        ).status_code == 200
        assert db.get_session(session_id=sid, deserialize=False)["user_id"] == "user-c"
        # ...and the next identified writer is a non-owner.
        assert (
            _run(auth_client, "/agents/history-agent/runs", create_token("user-d"), message="d", session_id=sid)
        ).status_code == 404

    def test_guard_uses_the_component_db_when_agentos_has_none(self, history_agent):
        """Components commonly carry their own db while ``AgentOS`` gets none.
        An implementation that reads only ``os.db`` silently no-ops there."""
        client = _ownership_client(user_isolation=True, agents=[history_agent], db=None)
        sid = "component-db-only"
        assert (
            _run(client, "/agents/history-agent/runs", create_token("user-c"), message="opened by C", session_id=sid)
        ).status_code == 200
        resp = _run(client, "/agents/history-agent/runs", create_token("user-d"), message="intrude", session_id=sid)
        assert resp.status_code == 404, resp.text

    @pytest.mark.parametrize("isolation", [True, False])
    def test_team_route_refuses_a_foreign_session(self, history_team, isolation):
        client = _ownership_client(user_isolation=isolation, teams=[history_team], db=history_team.db)
        sid = "team-owned-by-c"
        assert (
            _run(client, "/teams/history-team/runs", create_token("user-c"), message="opened by C", session_id=sid)
        ).status_code == 200
        resp = _run(client, "/teams/history-team/runs", create_token("user-d"), message="intrude", session_id=sid)
        assert resp.status_code == 404, resp.text
        runs = history_team.db.get_runs(session_id=sid, deserialize=False)[0]
        assert {r["user_id"] for r in runs} == {"user-c"}

    @pytest.mark.parametrize("isolation", [True, False])
    def test_workflow_route_refuses_a_foreign_session(self, history_workflow, isolation):
        client = _ownership_client(user_isolation=isolation, workflows=[history_workflow], db=history_workflow.db)
        sid = "wf-owned-by-c"
        assert (
            _run(
                client,
                "/workflows/history-workflow/runs",
                create_token("user-c"),
                message="opened by C",
                session_id=sid,
            )
        ).status_code == 200
        resp = _run(
            client, "/workflows/history-workflow/runs", create_token("user-d"), message="intrude", session_id=sid
        )
        assert resp.status_code == 404, resp.text
        runs = history_workflow.db.get_runs(session_id=sid, deserialize=False)[0]
        assert {r["user_id"] for r in runs} == {"user-c"}


class TestIdentityLessRunOwnership:
    """The identity-less variant. A run carrying no ``user_id`` skips the
    read-side owner filter too, so the intruder reads the owner's history in
    their own response and their run row is stamped with the owner's id — which
    is why the guard must not short-circuit on ``effective_user_id is None``.
    """

    def test_identity_less_run_into_owned_session_is_refused(self, history_agent):
        client = _open_client(agents=[history_agent], db=history_agent.db)
        sid = "owned-by-c-6"
        _run(client, "/agents/history-agent/runs", message="opened by C", session_id=sid, user_id="specUserC")
        before = history_agent.db.get_session(session_id=sid, deserialize=False)

        resp = _run(client, "/agents/history-agent/runs", message=f"My private {SECRET_TEXT}", session_id=sid)

        assert resp.status_code == 404, resp.text
        assert not _history(resp)
        runs = history_agent.db.get_runs(session_id=sid, deserialize=False)[0]
        assert len(runs) == 1
        # The refused caller must not have rewritten the owner's session row
        # either — an identity-less write passes upsert_session's predicate.
        after = history_agent.db.get_session(session_id=sid, deserialize=False)
        assert after["user_id"] == before["user_id"] == "specUserC"
        assert after.get("session_data") == before.get("session_data")

    def test_identity_less_run_into_unowned_session_still_works(self, history_agent):
        """The branch that keeps dev mode and the eval suite alive: a session
        created with no identity stores ``user_id`` NULL, so the owner-is-None
        branch admits every later identity-less run."""
        client = _open_client(agents=[history_agent], db=history_agent.db)
        sid = "nobody-owns-this"
        assert _run(client, "/agents/history-agent/runs", message="one", session_id=sid).status_code == 200
        resp = _run(client, "/agents/history-agent/runs", message="two", session_id=sid)
        assert resp.status_code == 200, resp.text
        assert any("one" in str(m.get("content")) for m in _history(resp))

    def test_component_user_id_default_is_not_locked_out(self, shared_db):
        """The component carries ``user_id`` while the route resolves None, so
        the session row is owned by that default. The guard must compare against
        the EFFECTIVE id or every second run of such a component 404s."""
        agent = Agent(
            id="history-agent",
            name="history-agent",
            db=shared_db,
            model=ScriptedModel("scripted-1", "ok"),
            user_id="anonymous-user",
            add_history_to_context=True,
            num_history_runs=5,
        )
        client = _open_client(agents=[agent], db=shared_db)
        sid = "template-session"
        assert _run(client, "/agents/history-agent/runs", message="one", session_id=sid).status_code == 200
        assert shared_db.get_session(session_id=sid, deserialize=False)["user_id"] == "anonymous-user"
        assert _run(client, "/agents/history-agent/runs", message="two", session_id=sid).status_code == 200
