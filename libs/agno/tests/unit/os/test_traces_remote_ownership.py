"""S2 / finding #2: the RemoteDb branch of GET /traces/{trace_id} must ALSO enforce
ownership locally for a scoped caller -- not rely solely on the remote enforcing it via
the forwarded bearer. A remote that predates the ownership fix (or trusts an upstream
gateway) would otherwise leak another user's trace back through the gateway.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from agno.os.routers.traces.schemas import TraceDetail
from agno.os.routers.traces.traces import get_traces_router
from agno.os.settings import AgnoAPISettings
from agno.remote.base import RemoteDb


def _build(remote_trace_user_id: str, *, scoped: bool):
    now = datetime.now(UTC)
    trace = TraceDetail(
        trace_id="t1",
        name="root",
        status="OK",
        duration="0ms",
        start_time=now,
        end_time=now,
        total_spans=0,
        error_count=0,
        user_id=remote_trace_user_id,
        created_at=now,
        tree=[],
    )
    remote = MagicMock(spec=RemoteDb)
    remote.get_trace = AsyncMock(return_value=trace)

    class _State(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.user_id = "user-b"
            request.state.scopes = ["traces:read"]
            # scoped=True -> non-admin isolated caller (effective_user_id == "user-b");
            # scoped=False -> isolation off (effective_user_id is None, admin-like).
            request.state.user_isolation_enabled = scoped
            return await call_next(request)

    app = FastAPI()
    app.include_router(get_traces_router({"remote": [remote]}, AgnoAPISettings()))
    app.add_middleware(_State)
    return TestClient(app), remote


class TestRemoteDbTraceOwnership:
    def test_scoped_non_owner_gets_404(self):
        # The remote returns user-a's trace; without the local ownership check the gateway
        # would forward it (200) -- a leak. With the fix, the gateway 404s.
        client, remote = _build("user-a", scoped=True)
        resp = client.get("/traces/t1")
        assert resp.status_code == 404, resp.text
        remote.get_trace.assert_awaited()

    def test_scoped_owner_gets_200(self):
        client, _ = _build("user-b", scoped=True)
        resp = client.get("/traces/t1")
        assert resp.status_code == 200, resp.text

    def test_unscoped_caller_skips_local_check(self):
        # isolation off -> effective_user_id is None -> single call, no local ownership gate
        # (admins/operators keep the unscoped view).
        client, _ = _build("user-a", scoped=False)
        resp = client.get("/traces/t1")
        assert resp.status_code == 200, resp.text
