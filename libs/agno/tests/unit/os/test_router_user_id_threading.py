"""Router-level tests confirming the migrated routers thread ``user_id``
into their DB calls.

Before the adapter removal, ``UserScopedDbAdapter`` injected ``user_id``
into every wrapped method. With the adapter gone the responsibility moved
into each router endpoint, which now calls ``resolve_db_and_scope`` /
``apply_scope_to_kwargs`` / ``get_scoped_user_id`` explicitly and forwards
the value to the DB.

The contract being pinned by this file:

  1. **Isolation ON + non-admin JWT** — the JWT sub overrides any
     ``?user_id=`` query param. This is what ``user_isolation=True`` buys.
  2. **Isolation OFF (default)** — query param is honoured as-is, even when
     a JWT is present. Legacy unscoped behaviour is preserved.
  3. **No JWT** — query param is honoured as-is.

Session router parity already exists in ``test_client_user_id.py``;
this file adds the same coverage for memory, traces, and approvals.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from agno.os.settings import AgnoAPISettings

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_jwt_middleware(*, user_isolation_enabled: bool):
    """Build a JWT-middleware stand-in that mirrors what AgentOS's real
    middleware writes to ``request.state``.

    The ``user_isolation_enabled`` knob controls whether the strict scoping
    path fires for non-admin callers — exactly the toggle real deployments
    flip via ``AuthorizationConfig(user_isolation=True)``.
    """

    class _JWTStateMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.user_id = "jwt_alice"
            request.state.scopes = ["agents:read", "memories:read", "approvals:read"]
            request.state.user_isolation_enabled = user_isolation_enabled
            return await call_next(request)

    return _JWTStateMiddleware


@pytest.fixture
def no_security_key(monkeypatch):
    monkeypatch.delenv("OS_SECURITY_KEY", raising=False)


# ---------------------------------------------------------------------------
# Memory router
# ---------------------------------------------------------------------------


@pytest.fixture
def memory_db():
    db = MagicMock()
    # ``isinstance(db, AsyncBaseDb)`` is False for a plain MagicMock, so the
    # router takes the sync branch. That's the path we want to exercise here.
    db.get_user_memories = MagicMock(return_value=([], 0))
    db.get_user_memory = MagicMock(return_value=None)
    db.delete_user_memory = MagicMock(return_value=None)
    db.get_all_memory_topics = MagicMock(return_value=[])
    db.get_user_memory_stats = MagicMock(return_value=([], 0))
    return db


def _build_memory_app(memory_db, *, isolation: bool | None):
    """Build an app, optionally wired with the JWT-state middleware. When
    ``isolation`` is None, no JWT middleware is attached (legacy unauth path)."""
    from agno.os.routers.memory.memory import get_memory_router

    app = FastAPI()
    app.include_router(get_memory_router({"default": [memory_db]}, AgnoAPISettings()))
    if isolation is not None:
        app.add_middleware(_make_jwt_middleware(user_isolation_enabled=isolation))
    return app


class TestMemoryRouterUserIdThreading:
    """The router calls ``apply_scope_to_kwargs`` / ``resolve_db_and_scope``;
    these tests pin what reaches the DB on the three cardinal paths."""

    # --- isolation ON --------------------------------------------------

    def test_list_memories_isolation_on_forces_jwt_sub(self, memory_db, no_security_key):
        app = _build_memory_app(memory_db, isolation=True)
        client = TestClient(app)
        resp = client.get("/memories?user_id=attacker")
        assert resp.status_code == 200
        assert memory_db.get_user_memories.call_args.kwargs["user_id"] == "jwt_alice"

    def test_get_memory_isolation_on_forces_jwt_sub(self, memory_db, no_security_key):
        app = _build_memory_app(memory_db, isolation=True)
        TestClient(app).get("/memories/mem-1?user_id=attacker")
        kwargs = memory_db.get_user_memory.call_args.kwargs
        assert kwargs["user_id"] == "jwt_alice"
        assert kwargs["memory_id"] == "mem-1"

    def test_delete_memory_isolation_on_forces_jwt_sub(self, memory_db, no_security_key):
        app = _build_memory_app(memory_db, isolation=True)
        TestClient(app).delete("/memories/mem-1?user_id=attacker")
        kwargs = memory_db.delete_user_memory.call_args.kwargs
        assert kwargs["user_id"] == "jwt_alice"
        assert kwargs["memory_id"] == "mem-1"

    def test_memory_topics_isolation_on_forces_jwt_sub(self, memory_db, no_security_key):
        app = _build_memory_app(memory_db, isolation=True)
        TestClient(app).get("/memory_topics?user_id=attacker")
        assert memory_db.get_all_memory_topics.call_args.kwargs["user_id"] == "jwt_alice"

    def test_memory_stats_isolation_on_forces_jwt_sub(self, memory_db, no_security_key):
        app = _build_memory_app(memory_db, isolation=True)
        TestClient(app).get("/user_memory_stats?user_id=attacker")
        assert memory_db.get_user_memory_stats.call_args.kwargs["user_id"] == "jwt_alice"

    # --- isolation OFF -------------------------------------------------

    def test_list_memories_isolation_off_honours_query_user_id(self, memory_db, no_security_key):
        """With isolation off, the query param wins — same as legacy."""
        app = _build_memory_app(memory_db, isolation=False)
        client = TestClient(app)
        resp = client.get("/memories?user_id=alice")
        assert resp.status_code == 200
        assert memory_db.get_user_memories.call_args.kwargs["user_id"] == "alice"

    # --- no JWT --------------------------------------------------------

    def test_list_memories_no_jwt_passes_query_user_id(self, memory_db, no_security_key):
        app = _build_memory_app(memory_db, isolation=None)
        client = TestClient(app)
        resp = client.get("/memories?user_id=alice")
        assert resp.status_code == 200
        assert memory_db.get_user_memories.call_args.kwargs["user_id"] == "alice"


# ---------------------------------------------------------------------------
# Traces router
# ---------------------------------------------------------------------------


@pytest.fixture
def trace_db():
    db = MagicMock()
    db.get_traces = MagicMock(return_value=([], 0))
    db.get_trace = MagicMock(return_value=None)
    db.get_trace_stats = MagicMock(return_value=([], 0))
    db.get_spans = MagicMock(return_value=[])
    return db


def _build_trace_app(trace_db, *, isolation: bool | None):
    from agno.os.routers.traces.traces import get_traces_router

    app = FastAPI()
    app.include_router(get_traces_router({"default": [trace_db]}, AgnoAPISettings()))
    if isolation is not None:
        app.add_middleware(_make_jwt_middleware(user_isolation_enabled=isolation))
    return app


class TestTraceRouterUserIdThreading:
    def test_list_traces_isolation_on_forces_jwt_sub(self, trace_db, no_security_key):
        app = _build_trace_app(trace_db, isolation=True)
        resp = TestClient(app).get("/traces?user_id=attacker")
        assert resp.status_code == 200
        assert trace_db.get_traces.call_args.kwargs["user_id"] == "jwt_alice"

    def test_list_traces_isolation_off_honours_query_user_id(self, trace_db, no_security_key):
        app = _build_trace_app(trace_db, isolation=False)
        resp = TestClient(app).get("/traces?user_id=alice")
        assert resp.status_code == 200
        assert trace_db.get_traces.call_args.kwargs["user_id"] == "alice"

    def test_list_traces_no_jwt_passes_query_user_id(self, trace_db, no_security_key):
        app = _build_trace_app(trace_db, isolation=None)
        resp = TestClient(app).get("/traces?user_id=alice")
        assert resp.status_code == 200
        assert trace_db.get_traces.call_args.kwargs["user_id"] == "alice"

    def test_get_trace_does_not_pass_user_id(self, trace_db, no_security_key):
        """``trace_id`` is a unique key — a trace already belongs to one
        owner, so ``get_trace`` doesn't accept ``user_id`` / ``session_id`` /
        ``agent_id`` filters. Authorization for the detail endpoint is
        carried by the list endpoint (which scopes trace_id discovery to
        the caller). The router must not pass extra kwargs that don't exist
        in ``BaseDb.get_trace`` — otherwise non-sqlite backends TypeError."""
        app = _build_trace_app(trace_db, isolation=True)
        TestClient(app).get("/traces/trace-1")
        kwargs = trace_db.get_trace.call_args.kwargs
        assert "user_id" not in kwargs
        assert "session_id" not in kwargs
        assert "agent_id" not in kwargs
        assert kwargs["trace_id"] == "trace-1"

    def test_trace_stats_isolation_on_forces_jwt_sub(self, trace_db, no_security_key):
        app = _build_trace_app(trace_db, isolation=True)
        TestClient(app).get("/trace_session_stats?user_id=attacker")
        assert trace_db.get_trace_stats.call_args.kwargs["user_id"] == "jwt_alice"


# ---------------------------------------------------------------------------
# Approvals router
# ---------------------------------------------------------------------------


@pytest.fixture
def approvals_db():
    """Approvals router takes a pre-resolved ``os_db`` (not a ``dbs`` dict),
    so we just hand it a SimpleNamespace with the methods it needs."""
    db = SimpleNamespace()
    db.get_approvals = MagicMock(return_value=([], 0))
    db.get_pending_approval_count = MagicMock(return_value=0)
    db.get_approval = MagicMock(return_value=None)
    db.update_approval = MagicMock(return_value=None)
    db.delete_approval = MagicMock(return_value=True)
    return db


def _build_approvals_app(approvals_db, *, isolation: bool | None):
    from agno.os.routers.approvals.router import get_approval_router

    app = FastAPI()
    app.include_router(get_approval_router(approvals_db, AgnoAPISettings()))
    if isolation is not None:
        app.add_middleware(_make_jwt_middleware(user_isolation_enabled=isolation))
    return app


class TestApprovalsRouterUserIdThreading:
    def test_list_approvals_isolation_on_forces_jwt_sub(self, approvals_db, no_security_key):
        app = _build_approvals_app(approvals_db, isolation=True)
        resp = TestClient(app).get("/approvals?user_id=attacker")
        assert resp.status_code == 200
        assert approvals_db.get_approvals.call_args.kwargs["user_id"] == "jwt_alice"

    def test_list_approvals_isolation_off_honours_query_user_id(self, approvals_db, no_security_key):
        app = _build_approvals_app(approvals_db, isolation=False)
        resp = TestClient(app).get("/approvals?user_id=alice")
        assert resp.status_code == 200
        assert approvals_db.get_approvals.call_args.kwargs["user_id"] == "alice"

    def test_list_approvals_no_jwt_passes_query_user_id(self, approvals_db, no_security_key):
        app = _build_approvals_app(approvals_db, isolation=None)
        resp = TestClient(app).get("/approvals?user_id=alice")
        assert resp.status_code == 200
        assert approvals_db.get_approvals.call_args.kwargs["user_id"] == "alice"

    def test_count_isolation_on_forces_jwt_sub(self, approvals_db, no_security_key):
        app = _build_approvals_app(approvals_db, isolation=True)
        resp = TestClient(app).get("/approvals/count?user_id=attacker")
        assert resp.status_code == 200
        assert approvals_db.get_pending_approval_count.call_args.kwargs["user_id"] == "jwt_alice"

    def test_get_approval_lookup_uses_approval_id(self, approvals_db, no_security_key):
        """The by-id endpoint can't push ``user_id`` into the DB call (the base
        method takes only approval_id). We confirm the DB sees the approval_id
        from the URL — the row-level ownership check lives in
        ``_load_approval_for_user`` and is covered in integration tests."""
        app = _build_approvals_app(approvals_db, isolation=True)
        TestClient(app).get("/approvals/a-1")
        approvals_db.get_approval.assert_called_once_with("a-1")


class TestApprovalsAdminOnlyResolve:
    """Resolve / delete are admin-only under ``user_isolation=True``.

    The approval row's ``user_id`` is the *requester*, not the approver, so
    a non-admin scoped caller cannot resolve or delete approvals — including
    their own. Admins, unscoped callers, and callers with isolation off keep
    the legacy "anyone with JWT can resolve" behaviour.
    """

    def _resolve_payload(self):
        return {"status": "approved"}

    # --- non-admin under isolation: 404 to avoid leaking existence ----

    def test_resolve_forbidden_for_non_admin_under_isolation(self, approvals_db, no_security_key):
        # The row belongs to the caller, but self-resolve is still blocked.
        # Returns 404 (not 403) to avoid leaking the approval's existence.
        approvals_db.get_approval.return_value = {
            "approval_id": "a-1",
            "user_id": "jwt_alice",
            "status": "pending",
        }
        app = _build_approvals_app(approvals_db, isolation=True)
        resp = TestClient(app).post("/approvals/a-1/resolve", json=self._resolve_payload())
        assert resp.status_code == 404
        # Make sure we short-circuited before the DB update.
        approvals_db.update_approval.assert_not_called()

    def test_delete_forbidden_for_non_admin_under_isolation(self, approvals_db, no_security_key):
        approvals_db.get_approval.return_value = {
            "approval_id": "a-1",
            "user_id": "jwt_alice",
            "status": "pending",
        }
        app = _build_approvals_app(approvals_db, isolation=True)
        resp = TestClient(app).delete("/approvals/a-1")
        assert resp.status_code == 404
        approvals_db.delete_approval.assert_not_called()

    # --- isolation OFF: legacy behaviour preserved --------------------

    def test_resolve_allowed_when_isolation_off(self, approvals_db, no_security_key):
        approvals_db.get_approval.return_value = {
            "approval_id": "a-1",
            "user_id": "jwt_alice",
            "status": "pending",
        }
        approvals_db.update_approval.return_value = {
            "approval_id": "a-1",
            "user_id": "jwt_alice",
            "status": "approved",
            "id": "row-1",
            "run_id": "run-1",
            "session_id": "sess-1",
            "source_type": "agent",
        }
        app = _build_approvals_app(approvals_db, isolation=False)
        resp = TestClient(app).post("/approvals/a-1/resolve", json=self._resolve_payload())
        assert resp.status_code == 200
        approvals_db.update_approval.assert_called_once()

    # --- admin: allowed -----------------------------------------------

    def test_resolve_allowed_for_admin(self, approvals_db, no_security_key):
        """An admin token (``agent_os:admin`` in scopes) bypasses the gate."""
        from fastapi import FastAPI
        from starlette.middleware.base import BaseHTTPMiddleware

        from agno.os.routers.approvals.router import get_approval_router

        class _AdminMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state.user_id = "admin-user"
                request.state.scopes = ["agent_os:admin"]
                request.state.user_isolation_enabled = True
                return await call_next(request)

        approvals_db.get_approval.return_value = {
            "approval_id": "a-1",
            "user_id": "someone-else",
            "status": "pending",
        }
        approvals_db.update_approval.return_value = {
            "approval_id": "a-1",
            "user_id": "someone-else",
            "status": "approved",
            "id": "row-1",
            "run_id": "run-1",
            "session_id": "sess-1",
            "source_type": "agent",
        }
        app = FastAPI()
        app.include_router(get_approval_router(approvals_db, AgnoAPISettings()))
        app.add_middleware(_AdminMiddleware)
        resp = TestClient(app).post("/approvals/a-1/resolve", json=self._resolve_payload())
        assert resp.status_code == 200
        approvals_db.update_approval.assert_called_once()
