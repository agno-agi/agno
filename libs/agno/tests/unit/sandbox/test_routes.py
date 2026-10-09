from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import Request

from agno.agents.sandbox import SandboxAgent
from agno.db.sqlite import SqliteDb
from agno.os.scopes import check_route_scopes, get_default_scope_mappings
from agno.os.settings import AgnoAPISettings
from agno.sandbox.router import destroy_session_sandboxes, get_sandbox_router
from agno.session.agent import AgentSession

from .test_resolution import FakeProvider


@pytest.mark.asyncio
async def test_management_scopes_ownership_redaction_and_delete_tombstone(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "routes.db"))
    agent = SandboxAgent(id="coder", db=db, provider=FakeProvider())
    sid = str(uuid4())
    db.upsert_sandbox(
        dict(
            sandbox_id=sid,
            session_id="s",
            agent_id="coder",
            user_id="owner",
            provider="fake",
            generation=1,
            status="ready",
            url="http://secret-runtime",
            provider_ref="container",
            metadata={"secret": "never-public", "checkpoint": "commit"},
        )
    )
    app = FastAPI()
    app.state.sandbox_agents = [agent]

    @app.middleware("http")
    async def trusted_test_identity(request, call_next):
        request.state.user_isolation_enabled = True
        request.state.user_id = request.headers.get("test-user", "owner")
        request.state.scopes = []
        return await call_next(request)

    app.include_router(get_sandbox_router(SimpleNamespace(agents=[agent], settings=AgnoAPISettings())))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/sandboxes")
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert "secret" not in response.text and "container" not in response.text
        assert (await client.get("/sandboxes", headers={"test-user": "other"})).json() == []
        assert (await client.get("/sessions/s/sandbox", headers={"test-user": "other"})).status_code == 404
        assert (await client.delete(f"/sandboxes/{sid}", headers={"test-user": "other"})).status_code == 404
        assert (await client.post("/sessions/s/sandbox:pause")).status_code == 501
        row = db.get_sandbox(session_id="s")
        db.upsert_sandbox({**row, "active_run_id": "busy", "active_attempt": 1}, row["revision"])
        assert (await client.delete(f"/sandboxes/{sid}")).status_code == 409
        row = db.get_sandbox(session_id="s")
        db.upsert_sandbox({**row, "active_run_id": None}, row["revision"])

    request = Request({"type": "http", "app": app})
    await destroy_session_sandboxes(request, db, ["s"], "other")
    assert db.get_sandbox(session_id="s")["status"] == "ready"
    await destroy_session_sandboxes(request, db, ["s"], "owner")
    assert db.get_sandbox(session_id="s")["metadata"]["session_deleted"]
    with pytest.raises(ValueError, match="deleted"):
        await agent._resolve(
            dict(id="queued", session_id="s", user_id="owner", attempt=1),
            SimpleNamespace(config=SimpleNamespace(lock_grace_seconds=1)),
        )
    # A session queued before its first sandbox exists also acquires a tombstone.
    db.upsert_session(AgentSession(session_id="queued-session", agent_id="coder", user_id="owner"))
    await destroy_session_sandboxes(request, db, ["queued-session"], "owner")
    assert db.get_sandbox(session_id="queued-session")["metadata"]["session_deleted"]
    db.db_engine.dispose()


@pytest.mark.parametrize(
    "method,path,scope",
    [
        ("GET", "/sandboxes", "sessions:read"),
        ("GET", "/sessions/s/sandbox", "sessions:read"),
        ("DELETE", "/sandboxes/id", "sessions:delete"),
        ("POST", "/sessions/s/sandbox:pause", "sessions:write"),
    ],
)
def test_routes_require_session_scopes(method, path, scope):
    mappings = get_default_scope_mappings()
    assert not check_route_scopes([], mappings, method, path).allowed
    assert check_route_scopes([scope], mappings, method, path).allowed
