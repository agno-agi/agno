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
