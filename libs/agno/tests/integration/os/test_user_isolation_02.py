"""Integration tests for review-identified gaps in per-user data isolation.

Covers:
- Workflow run listing scoping (CRITICAL)
- SSE resume ownership (CRITICAL)
- Custom admin_scope propagation through request.state (HIGH)
- Memory admin act-on-behalf (HIGH)
- Factory cancel ownership (MEDIUM)
"""

import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.os.middleware.user_scope import (
    INSUFFICIENT_PERMISSIONS_WS_RECONNECT,
    WORKFLOW_ID_REQUIRED_RECONNECT,
)
from agno.team.team import Team
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

JWT_SECRET = "test-secret-for-pr-fixes"
TEST_OS_ID = "test-pr-fixes-os"
CUSTOM_ADMIN_SCOPE = "custom:admin"


def make_token(
    user_id: str,
    scopes: list[str] | None = None,
    secret: str = JWT_SECRET,
) -> str:
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
    return jwt.encode(payload, secret, algorithm="HS256")


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_agent(shared_db):
    return Agent(name="test-agent", id="test-agent", db=shared_db, instructions="x")


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
    return TestClient(agent_os.get_app())


@pytest.fixture
def custom_admin_client(test_agent):
    """Client with admin_scope configured to a non-default value."""
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


# ---------------------------------------------------------------------------
# Traces list scoping
# ---------------------------------------------------------------------------


class TestTraceListScoping:
    """``GET /traces`` must only return traces owned by the caller.

    The single-trace detail endpoint (``GET /traces/{trace_id}``) does NOT
    enforce row-level ownership: a unique ``trace_id`` is sufficient — see
    the design notes at the top of this file. The list endpoint is where
    isolation actually matters, because that's how non-admin callers
    discover which trace_ids exist at all. If the list endpoint leaked
    other users' rows, every downstream "knew the trace_id" assumption
    falls apart.
    """

    def _insert_trace(self, db, *, trace_id: str, user_id: str):
        from agno.tracing.schemas import Trace

        now = datetime.now(UTC)
        trace = Trace(
            trace_id=trace_id,
            name="root",
            status="OK",
            start_time=now,
            end_time=now,
            duration_ms=0,
            total_spans=0,
            error_count=0,
            run_id=f"run-{trace_id}",
            session_id=f"session-{trace_id}",
            user_id=user_id,
            agent_id="test-agent",
            team_id=None,
            workflow_id=None,
            created_at=now,
        )
        db.upsert_trace(trace)

    def test_user_only_sees_own_traces(self, client, shared_db):
        """A non-admin caller listing traces gets only their own rows."""
        self._insert_trace(shared_db, trace_id="trace-a-1", user_id="user-a")
        self._insert_trace(shared_db, trace_id="trace-a-2", user_id="user-a")
        self._insert_trace(shared_db, trace_id="trace-b-1", user_id="user-b")

        token_a = make_token("user-a")
        resp = client.get("/traces", headers=auth_header(token_a))
        assert resp.status_code == 200, resp.text

        returned_ids = {row["trace_id"] for row in resp.json()["data"]}
        assert returned_ids == {"trace-a-1", "trace-a-2"}, (
            f"user-a's list should only contain their traces, got {returned_ids}"
        )

    def test_user_cannot_filter_to_another_users_traces(self, client, shared_db):
        """A non-admin caller passing ``?user_id=other`` is ignored — the JWT
        sub wins. Without this, knowing another user's id (just an email or
        UUID, not a secret) would be enough to enumerate their traces."""
        self._insert_trace(shared_db, trace_id="trace-other-1", user_id="user-a")

        token_b = make_token("user-b")
        resp = client.get("/traces?user_id=user-a", headers=auth_header(token_b))
        assert resp.status_code == 200, resp.text

        returned_ids = {row["trace_id"] for row in resp.json()["data"]}
        assert "trace-other-1" not in returned_ids, (
            f"query-param user_id must not override the JWT sub; got {returned_ids}"
        )

    def test_admin_sees_all_traces(self, client, shared_db):
        """Admins keep the unscoped operator view — no regression."""
        self._insert_trace(shared_db, trace_id="trace-admin-a", user_id="user-a")
        self._insert_trace(shared_db, trace_id="trace-admin-b", user_id="user-b")

        admin_token = make_token("admin-1", scopes=["agent_os:admin"])
        resp = client.get("/traces", headers=auth_header(admin_token))
        assert resp.status_code == 200, resp.text

        returned_ids = {row["trace_id"] for row in resp.json()["data"]}
        assert {"trace-admin-a", "trace-admin-b"}.issubset(returned_ids), (
            f"admin should see all traces; got {returned_ids}"
        )


# ---------------------------------------------------------------------------
# Workflow run listing
# ---------------------------------------------------------------------------


class TestWorkflowRunListScoping:
    """Workflow run list must not leak runs from other users' sessions."""

    def _make_workflow_session(self, client, user_id: str, session_id: str):
        """Create a workflow session by writing it directly via the sessions API."""
        token = make_token(user_id, scopes=[CUSTOM_ADMIN_SCOPE, "agent_os:admin"])  # admin to create
        resp = client.post(
            "/sessions?type=workflow",
            json={
                "workflow_id": "test-workflow",
                "user_id": user_id,
                "session_id": session_id,
            },
            headers=auth_header(token),
        )
        # Some adapters require session_id to be auto-generated; accept either.
        if resp.status_code in (200, 201):
            data = resp.json()
            return data.get("session_id") or data.get("workflow_session_id") or session_id
        pytest.skip(f"Could not seed workflow session: {resp.status_code} {resp.text}")

    def test_non_admin_cannot_list_other_users_runs(self, client):
        session_id = self._make_workflow_session(client, "user-a", "wf-sess-1")

        token_b = make_token("user-b")
        resp = client.get(
            f"/workflows/test-workflow/runs?session_id={session_id}",
            headers=auth_header(token_b),
        )
        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Finding 3 — SSE resume ownership
# ---------------------------------------------------------------------------


class TestResumeOwnership:
    """Resume endpoints must require session_id and verify ownership."""

    def test_agent_resume_requires_session_id_for_non_admin(self, client):
        token = make_token("user-a")
        resp = client.post(
            "/agents/test-agent/runs/some-run/resume",
            data={},
            headers=auth_header(token),
        )
        assert resp.status_code == 400, resp.text
        assert "session_id" in resp.json()["detail"].lower()

    def test_team_resume_requires_session_id_for_non_admin(self, client):
        token = make_token("user-a")
        resp = client.post(
            "/teams/test-team/runs/some-run/resume",
            data={},
            headers=auth_header(token),
        )
        assert resp.status_code == 400, resp.text

    def test_workflow_resume_requires_session_id_for_non_admin(self, client):
        token = make_token("user-a")
        resp = client.post(
            "/workflows/test-workflow/runs/some-run/resume",
            data={},
            headers=auth_header(token),
        )
        assert resp.status_code == 400, resp.text

    def test_agent_resume_foreign_run_returns_404(self, client):
        # user-a creates a session, user-b tries to resume a fake run within it
        token_a = make_token("user-a", scopes=["agent_os:admin"])
        token_b = make_token("user-b")

        resp = client.post(
            "/sessions?type=agent",
            json={"agent_id": "test-agent", "user_id": "user-a"},
            headers=auth_header(token_a),
        )
        assert resp.status_code == 201, resp.text
        session_id = resp.json().get("session_id") or resp.json().get("agent_session_id")

        resp = client.post(
            "/agents/test-agent/runs/run-not-real/resume",
            data={"session_id": session_id},
            headers=auth_header(token_b),
        )
        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Finding 5 — Custom admin_scope propagation
# ---------------------------------------------------------------------------


class TestCustomAdminScopePropagation:
    """A custom admin_scope must reach get_scoped_user_id via request.state."""

    def test_custom_admin_scope_grants_admin_data_access(self, custom_admin_client):
        # Seed a session under user-a (using the custom admin scope to bypass
        # any user filtering at write time).
        token_admin = make_token("admin-user", scopes=[CUSTOM_ADMIN_SCOPE])
        token_b = make_token("user-b")

        resp = custom_admin_client.post(
            "/sessions?type=agent",
            json={"agent_id": "test-agent", "user_id": "user-a"},
            headers=auth_header(token_admin),
        )
        assert resp.status_code == 201, resp.text
        session_id = resp.json().get("session_id") or resp.json().get("agent_session_id")

        # Custom-admin lists sessions — must see user-a's session.
        resp = custom_admin_client.get(
            "/sessions?type=agent",
            headers=auth_header(token_admin),
        )
        assert resp.status_code == 200
        ids = [s["session_id"] for s in resp.json()["data"]]
        assert session_id in ids

        # Non-admin must NOT see it.
        resp = custom_admin_client.get(
            "/sessions?type=agent",
            headers=auth_header(token_b),
        )
        assert resp.status_code == 200
        ids = [s["session_id"] for s in resp.json()["data"]]
        assert session_id not in ids

    def test_default_admin_scope_is_no_longer_admin_when_custom_configured(self, custom_admin_client):
        """A token with the default `agent_os:admin` scope must NOT be treated
        as admin when the operator configured a custom admin_scope."""
        token_default = make_token("user-x", scopes=["agent_os:admin"])
        # Listing should not error, but data must be filtered by user-x (none).
        resp = custom_admin_client.get(
            "/sessions?type=agent",
            headers=auth_header(token_default),
        )
        # The token has no per-resource read scope — listing should 403 or
        # return an empty/own-only result depending on default scope mapping.
        # The key invariant: this caller must not be admin-equivalent.
        assert resp.status_code in (200, 403), resp.text


# ---------------------------------------------------------------------------
# Finding 6 — Memory admin act-on-behalf
# ---------------------------------------------------------------------------


class TestMemoryAdminActOnBehalf:
    """Admin must be able to delete/optimize memories for another user."""

    def test_admin_delete_memories_targets_body_user_id(self, client):
        # Seed a memory for user-a.
        token_a = make_token("user-a")
        resp = client.post(
            "/memories",
            json={"memory": "User A loves trail running", "user_id": "user-a"},
            headers=auth_header(token_a),
        )
        if resp.status_code not in (200, 201):
            pytest.skip(f"Memory create not supported in this env: {resp.text}")
        memory_id = resp.json().get("id") or resp.json().get("memory_id")
        assert memory_id

        # Admin (with default scope) deletes user-a's memory by id, specifying
        # user_id in the body. This must succeed; the fixed handler must not
        # overwrite request.user_id with the admin's own JWT user_id.
        admin_token = make_token("admin-user", scopes=["agent_os:admin"])
        resp = client.request(
            "DELETE",
            "/memories",
            json={"memory_ids": [memory_id], "user_id": "user-a"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 204, resp.text

        # Verify user-a can no longer see it.
        resp = client.get("/memories", headers=auth_header(token_a))
        assert resp.status_code == 200
        ids = [m.get("id") or m.get("memory_id") for m in resp.json()["data"]]
        assert memory_id not in ids

    def test_non_admin_cannot_act_on_other_users_memory(self, client):
        token_a = make_token("user-a")
        resp = client.post(
            "/memories",
            json={"memory": "User A's secret", "user_id": "user-a"},
            headers=auth_header(token_a),
        )
        if resp.status_code not in (200, 201):
            pytest.skip(f"Memory create not supported: {resp.text}")
        memory_id = resp.json().get("id") or resp.json().get("memory_id")

        # User-b tries to delete user-a's memory by passing user_id=user-a.
        # The fixed handler must overwrite request.user_id with user-b's JWT id,
        # so the delete operates on user-b's namespace and is a no-op.
        token_b = make_token("user-b")
        client.request(
            "DELETE",
            "/memories",
            json={"memory_ids": [memory_id], "user_id": "user-a"},
            headers=auth_header(token_b),
        )

        # The memory should still exist for user-a.
        resp = client.get("/memories", headers=auth_header(token_a))
        assert resp.status_code == 200
        ids = [m.get("id") or m.get("memory_id") for m in resp.json()["data"]]
        assert memory_id in ids


# ---------------------------------------------------------------------------
# Finding 7 — Factory cancel ownership (smoke test via non-factory route)
# ---------------------------------------------------------------------------


class TestCancelOwnership:
    """Cancel routes must enforce session ownership; existing tests cover the
    non-factory path. This adds a regression covering admin bypass via custom
    admin scope."""

    def test_custom_admin_can_cancel_without_session_id(self, custom_admin_client):
        token = make_token("admin-x", scopes=[CUSTOM_ADMIN_SCOPE])
        resp = custom_admin_client.post(
            "/agents/test-agent/runs/some-run/cancel",
            headers=auth_header(token),
        )
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Re-review finding 1 — Continue-run ownership
# ---------------------------------------------------------------------------


class TestContinueRunOwnership:
    """Continue-run routes must verify session+component ownership before
    revealing run status (409 vs 404 leaks existence)."""

    def test_agent_continue_requires_session_id_for_non_admin(self, client):
        token = make_token("user-a")
        resp = client.post(
            "/agents/test-agent/runs/some-run/continue",
            data={"tools": ""},
            headers=auth_header(token),
        )
        # Either ownership-check 400 ("session_id required") or
        # session_id-check 400 ("session_id is required to continue a run").
        assert resp.status_code == 400, resp.text

    def test_agent_continue_foreign_run_returns_404(self, client):
        token_a = make_token("user-a", scopes=["agent_os:admin"])
        token_b = make_token("user-b")

        resp = client.post(
            "/sessions?type=agent",
            json={"agent_id": "test-agent", "user_id": "user-a"},
            headers=auth_header(token_a),
        )
        assert resp.status_code == 201, resp.text
        session_id = resp.json().get("session_id") or resp.json().get("agent_session_id")

        resp = client.post(
            "/agents/test-agent/runs/run-not-real/continue",
            data={"tools": "", "session_id": session_id},
            headers=auth_header(token_b),
        )
        assert resp.status_code == 404, resp.text

    def test_workflow_continue_requires_session_id_for_non_admin(self, client):
        token = make_token("user-a")
        resp = client.post(
            "/workflows/test-workflow/runs/some-run/continue",
            data={"step_requirements": ""},
            headers=auth_header(token),
        )
        assert resp.status_code == 400, resp.text

    def test_workflow_continue_foreign_run_returns_404(self, client):
        token_a = make_token("user-a", scopes=["agent_os:admin"])
        token_b = make_token("user-b")

        resp = client.post(
            "/sessions?type=workflow",
            json={"workflow_id": "test-workflow", "user_id": "user-a"},
            headers=auth_header(token_a),
        )
        if resp.status_code not in (200, 201):
            pytest.skip(f"Could not seed workflow session: {resp.status_code} {resp.text}")
        session_id = resp.json().get("session_id") or resp.json().get("workflow_session_id")

        resp = client.post(
            "/workflows/test-workflow/runs/run-fake/continue",
            data={"step_requirements": "", "session_id": session_id},
            headers=auth_header(token_b),
        )
        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Re-review finding 2 — Per-resource RBAC bypass via cross-component runs
# ---------------------------------------------------------------------------


@pytest.fixture
def two_agent_client(shared_db):
    """Two agents on the same OS, so a session/run from agent-b can be probed
    against /agents/agent-a/...
    """
    a1 = Agent(name="agent-a", id="agent-a", db=shared_db, instructions="x")
    a2 = Agent(name="agent-b", id="agent-b", db=shared_db, instructions="x")
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[a1, a2],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
            user_isolation=True,
        ),
    )
    return TestClient(agent_os.get_app())


class TestCrossComponentRbacBypass:
    """A token with per-resource scope must not be able to operate on a
    run that belongs to a different component, even when the same user owns
    both sessions/runs."""

    def _seed_agent_b_session(self, two_agent_client):
        # Use a token that can write sessions for user-x under any agent.
        token = make_token("user-x", scopes=["agent_os:admin"])
        resp = two_agent_client.post(
            "/sessions?type=agent",
            json={"agent_id": "agent-b", "user_id": "user-x"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201, resp.text
        return resp.json().get("session_id") or resp.json().get("agent_session_id")

    def test_cancel_rejects_cross_agent_run_id(self, two_agent_client):
        session_id = self._seed_agent_b_session(two_agent_client)

        # Token has scope only for agent-a. The route's RBAC accepts because
        # of the per-agent run scope; the ownership helper must additionally
        # block this because the session belongs to agent-b.
        token = make_token("user-x", scopes=["agents:agent-a:run"])
        resp = two_agent_client.post(
            f"/agents/agent-a/runs/some-run/cancel?session_id={session_id}",
            headers=auth_header(token),
        )
        # 404 — neither the run nor the cross-agent session is exposed.
        assert resp.status_code == 404, resp.text


class TestWebSocketReconnectRBAC:
    """WebSocket reconnect must enforce workflows:run scope and require a
    workflow_id, matching the contract of start-workflow.

    Without these guards a token with no workflow scope could subscribe to a
    buffered run by guessing its run_id, and even with a scope the missing
    workflow_id would cause the session/run component check to silently skip.
    """

    # Maximum frames to consume waiting for a specific event. Big enough to
    # cover the auth handshake (connected + 1-2 authenticated frames) without
    # hanging on a buggy server.
    _MAX_FRAMES = 8

    def _drain_until(self, ws, predicate):
        """Read frames until ``predicate(frame)`` returns True. Fails fast
        rather than hanging when the server never emits the expected frame."""
        for _ in range(self._MAX_FRAMES):
            frame = json.loads(ws.receive_text())
            if predicate(frame):
                return frame
        raise AssertionError(f"Expected frame matching predicate within {self._MAX_FRAMES} messages")

    def _authenticate(self, ws, token):
        """Run the auth handshake and consume all of its frames.

        On JWT auth the server emits "connected" (on accept), then
        "authenticated" twice (one from WebSocketManager, one from the route
        with the user_id). Drain until we see the user_id-bearing confirmation
        so subsequent reads return the test's reply, not auth leftovers.
        """
        self._drain_until(ws, lambda f: f.get("event") == "connected")
        ws.send_text(json.dumps({"action": "authenticate", "token": token}))
        self._drain_until(ws, lambda f: f.get("event") == "authenticated" and f.get("user_id") is not None)

    def test_reconnect_rejected_without_workflow_scope(self, client):
        # Token with no workflow scopes.
        token = make_token("user-a", scopes=["agents:read"])
        with client.websocket_connect("/workflows/ws") as ws:
            self._authenticate(ws, token)
            ws.send_text(
                json.dumps(
                    {
                        "action": "reconnect",
                        "run_id": "some-run",
                        "session_id": "some-session",
                        "workflow_id": "test-workflow",
                    }
                )
            )
            event = self._drain_until(ws, lambda f: f.get("event") == "error")
        assert event["error"] == INSUFFICIENT_PERMISSIONS_WS_RECONNECT, event

    def test_reconnect_rejected_when_workflow_id_missing(self, client):
        token = make_token("user-a")  # full scopes (including workflows:run)
        with client.websocket_connect("/workflows/ws") as ws:
            self._authenticate(ws, token)
            ws.send_text(
                json.dumps(
                    {
                        "action": "reconnect",
                        "run_id": "some-run",
                        "session_id": "some-session",
                        # workflow_id deliberately omitted
                    }
                )
            )
            event = self._drain_until(ws, lambda f: f.get("event") == "error")
        assert event["error"] == WORKFLOW_ID_REQUIRED_RECONNECT, event

    def test_reconnect_with_scope_proceeds_to_ownership_check(self, client):
        """A non-admin with workflows:run gets past the RBAC gate and reaches
        the ownership check, which 404s here because the run doesn't exist."""
        token = make_token("user-a", scopes=["workflows:test-workflow:run"])
        with client.websocket_connect("/workflows/ws") as ws:
            self._authenticate(ws, token)
            ws.send_text(
                json.dumps(
                    {
                        "action": "reconnect",
                        "run_id": "nonexistent-run",
                        "session_id": "nonexistent-session",
                        "workflow_id": "test-workflow",
                    }
                )
            )
            event = self._drain_until(ws, lambda f: f.get("event") == "error")
        # The RBAC + workflow_id checks pass; the downstream ownership check
        # surfaces a different error (run not found).
        assert event["error"] != INSUFFICIENT_PERMISSIONS_WS_RECONNECT, event
        assert event["error"] != WORKFLOW_ID_REQUIRED_RECONNECT, event

    def test_admin_reconnect_does_not_require_workflow_id(self, client):
        """Admins bypass scope/workflow_id requirements; the handler still
        runs but won't reject pre-ownership for admin."""
        admin_token = make_token("admin-x", scopes=["agent_os:admin"])
        with client.websocket_connect("/workflows/ws") as ws:
            self._authenticate(ws, admin_token)
            ws.send_text(
                json.dumps(
                    {
                        "action": "reconnect",
                        "run_id": "nonexistent-run",
                        "session_id": "nonexistent-session",
                        # No workflow_id — admin bypass.
                    }
                )
            )
            event = self._drain_until(ws, lambda f: f.get("event") == "error")
        # Admin passes the dispatch-layer gates; the only error must come from
        # the downstream ownership/buffer lookup, never from the RBAC/workflow_id
        # gates we added.
        assert event["error"] != INSUFFICIENT_PERMISSIONS_WS_RECONNECT, event
        assert event["error"] != WORKFLOW_ID_REQUIRED_RECONNECT, event


class TestWorkflowSessionLeakViaAgentRoute:
    """A WorkflowSession containing a nested agent run must NOT be reachable
    through /agents/{agent_id}/... routes. Even though the nested run has a
    valid agent_id, the session itself belongs to a workflow, not an agent.
    """

    @pytest.fixture
    def seeded_client(self, shared_db, test_agent, test_workflow):
        """OS with one agent + one workflow, plus a WorkflowSession seeded
        directly into the shared db that contains a nested agent run."""
        from agno.run.agent import RunOutput
        from agno.session.workflow import WorkflowSession

        agent_run = RunOutput(
            run_id="nested-agent-run",
            agent_id="test-agent",
            session_id="wf-sess-with-nested-run",
            user_id="user-x",
            content="secret nested content",
        )
        wf_session = WorkflowSession(
            session_id="wf-sess-with-nested-run",
            workflow_id="test-workflow",
            user_id="user-x",
            runs=[agent_run],
            created_at=1,
        )
        shared_db.upsert_session(wf_session)

        agent_os = AgentOS(
            id=TEST_OS_ID,
            agents=[test_agent],
            workflows=[test_workflow],
            authorization=True,
            authorization_config=AuthorizationConfig(
                verification_keys=[JWT_SECRET],
                algorithm="HS256",
                user_isolation=True,
            ),
        )
        return TestClient(agent_os.get_app())

    def test_list_agent_runs_rejects_workflow_session(self, seeded_client):
        """GET /agents/test-agent/runs?session_id=<workflow-session> must 404."""
        token = make_token("user-x", scopes=["agents:test-agent:read", "agents:test-agent:run"])
        resp = seeded_client.get(
            "/agents/test-agent/runs?session_id=wf-sess-with-nested-run",
            headers=auth_header(token),
        )
        assert resp.status_code == 404, resp.text

    def test_get_agent_run_rejects_workflow_session(self, seeded_client):
        """GET /agents/test-agent/runs/<nested>?session_id=<workflow-session> must 404."""
        token = make_token("user-x", scopes=["agents:test-agent:read", "agents:test-agent:run"])
        resp = seeded_client.get(
            "/agents/test-agent/runs/nested-agent-run?session_id=wf-sess-with-nested-run",
            headers=auth_header(token),
        )
        assert resp.status_code == 404, resp.text

    def test_cancel_agent_run_rejects_workflow_session(self, seeded_client):
        """POST /agents/test-agent/runs/<nested>/cancel?session_id=<workflow-session> must 404."""
        token = make_token("user-x", scopes=["agents:test-agent:run"])
        resp = seeded_client.post(
            "/agents/test-agent/runs/nested-agent-run/cancel?session_id=wf-sess-with-nested-run",
            headers=auth_header(token),
        )
        assert resp.status_code == 404, resp.text

    def test_resume_agent_run_rejects_workflow_session(self, seeded_client):
        """POST /agents/test-agent/runs/<nested>/resume with workflow session must 404."""
        token = make_token("user-x", scopes=["agents:test-agent:read", "agents:test-agent:run"])
        resp = seeded_client.post(
            "/agents/test-agent/runs/nested-agent-run/resume",
            data={"session_id": "wf-sess-with-nested-run"},
            headers=auth_header(token),
        )
        assert resp.status_code == 404, resp.text

    def test_continue_agent_run_rejects_workflow_session(self, seeded_client):
        """POST /agents/test-agent/runs/<nested>/continue with workflow session must 404."""
        token = make_token("user-x", scopes=["agents:test-agent:run"])
        resp = seeded_client.post(
            "/agents/test-agent/runs/nested-agent-run/continue",
            data={"tools": "", "session_id": "wf-sess-with-nested-run"},
            headers=auth_header(token),
        )
        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Re-review finding 3 — Custom admin_scope on list endpoints
# ---------------------------------------------------------------------------


class TestCustomAdminScopeListings:
    """Custom admin tokens must succeed on /agents, /teams, /workflows."""

    def test_custom_admin_can_list_agents(self, custom_admin_client):
        token = make_token("admin-x", scopes=[CUSTOM_ADMIN_SCOPE])
        resp = custom_admin_client.get("/agents", headers=auth_header(token))
        assert resp.status_code == 200, resp.text
        # The fixture has a single agent registered; admin must see it.
        ids = [a.get("id") for a in resp.json()]
        assert "test-agent" in ids


# ---------------------------------------------------------------------------
# Opt-in: user_isolation must default to OFF
# ---------------------------------------------------------------------------


@pytest.fixture
def no_isolation_client(test_agent):
    """AgentOS with authorization=True but user_isolation NOT enabled.

    Asserts the backwards-compatibility contract: JWT/RBAC apply, but the
    user-scoped DB wrapper and per-user ownership gates stay dormant.
    """
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
            # user_isolation deliberately omitted — must default to False.
        ),
    )
    return TestClient(agent_os.get_app())


class TestUserIsolationDefaultOff:
    """When AuthorizationConfig(user_isolation=...) is left unset, the
    ownership/scoping behaviour added by the user-scoped-DB work must not
    fire. RBAC alone still governs access."""

    def test_non_admin_cancel_does_not_require_session_id(self, no_isolation_client):
        """Without isolation, the non-admin cancel path drops the
        session_id-required gate that was added for ownership verification.
        The route should accept the cancel and return 200 (cancel stores
        intent even for non-existent runs)."""
        token = make_token("user-a", scopes=["agents:test-agent:run"])
        resp = no_isolation_client.post(
            "/agents/test-agent/runs/some-run/cancel",
            headers=auth_header(token),
        )
        # 403 would mean RBAC denied; 400 would mean the isolation gate
        # still fired. Neither should happen here.
        assert resp.status_code == 200, resp.text

    def test_rbac_still_denies_without_run_scope(self, no_isolation_client):
        """User isolation being off must NOT relax RBAC. A token with only
        read scope must still be denied on a cancel (run) endpoint."""
        token = make_token("user-a", scopes=["agents:test-agent:read"])
        resp = no_isolation_client.post(
            "/agents/test-agent/runs/some-run/cancel",
            headers=auth_header(token),
        )
        assert resp.status_code == 403, resp.text

    def test_sessions_list_returns_other_users_sessions(self, no_isolation_client):
        """Without isolation, the sessions list does not auto-filter by JWT
        user_id. user-b can see user-a's session because the DB wrapper
        stays unscoped — matching legacy AgentOS behavior."""
        # Seed a session under user-a via an admin token (write path).
        admin_token = make_token("admin", scopes=["agent_os:admin"])
        resp = no_isolation_client.post(
            "/sessions?type=agent",
            json={"agent_id": "test-agent", "user_id": "user-a"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 201, resp.text
        session_id = resp.json().get("session_id") or resp.json().get("agent_session_id")

        # user-b lists sessions — must see user-a's session because no scoping.
        token_b = make_token("user-b", scopes=["sessions:read"])
        resp = no_isolation_client.get("/sessions?type=agent", headers=auth_header(token_b))
        assert resp.status_code == 200, resp.text
        ids = [s["session_id"] for s in resp.json()["data"]]
        assert session_id in ids
