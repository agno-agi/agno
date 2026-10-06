"""The compaction route's contract: a decline is a 200 with a status, a missing session is a 404."""

import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.routers.agents.router import get_agent_router
from agno.session import AgentSession


def _client(authorization: bool = False) -> TestClient:
    db = SqliteDb(db_file=str(Path(tempfile.mkdtemp()) / "compaction.db"))
    db.upsert_session(AgentSession(session_id="s1", agent_id="a1", runs=[]))
    db.upsert_session(AgentSession(session_id="s2", agent_id="a2", runs=[]))
    agents = [Agent(id=agent_id, db=db, compaction=Compaction()) for agent_id in ("a1", "a2")]
    app = FastAPI()
    if authorization:

        @app.middleware("http")
        async def enable_authorization(request, call_next):
            request.state.authorization_enabled = True
            return await call_next(request)

    app.include_router(get_agent_router(AgentOS(agents=agents)))
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    return _client()


def test_route_is_registered():
    db = SqliteDb(db_file=str(Path(tempfile.mkdtemp()) / "compaction.db"))
    agent_os = AgentOS(agents=[Agent(id="a1", db=db, compaction=Compaction())])

    paths = {(route.path, tuple(sorted(route.methods))) for route in get_agent_router(agent_os).routes}

    assert ("/agents/{agent_id}/sessions/{session_id}/compact", ("POST",)) in paths


def test_decline_is_a_200_with_a_reason(client: TestClient):
    """Declining to fold is a normal outcome, so a UI must not have to treat it as an error.

    Raising would make "folding would not help here" indistinguishable from a failure.
    """
    response = client.post("/agents/a1/sessions/s1/compact")

    assert response.status_code == 200
    body = response.json()
    assert body["compacted"] is False
    assert body["status"] == "no_history"
    assert body["message"]  # always something displayable
    assert body["record"] is None


def test_unknown_session_is_a_404(client: TestClient):
    """A session that does not exist is a 404, as on the other session routes - not no_history,
    which would read as "exists, nothing to fold yet"."""
    response = client.post("/agents/a1/sessions/does-not-exist/compact")

    assert response.status_code == 404


def test_another_agents_session_is_a_404(monkeypatch):
    """The resource gate authorised a1, so a1's route must not fold a2's session."""

    async def may_run_a1_only(request, resource_id, resource_type, action):
        return resource_id == "a1"

    monkeypatch.setattr("agno.os.auth.acheck_resource_access", may_run_a1_only)
    client = _client(authorization=True)

    assert client.post("/agents/a1/sessions/s1/compact").status_code == 200
    response = client.post("/agents/a1/sessions/s2/compact")

    assert response.status_code == 404


def test_unknown_agent_is_a_404(client: TestClient):
    """A missing agent IS an error - it means the caller asked for something that does not exist."""
    response = client.post("/agents/nope/sessions/s1/compact")

    assert response.status_code == 404


def test_response_shape_is_stable(client: TestClient):
    """These four keys are the contract the FE renders; adding is safe, renaming is not."""
    body = client.post("/agents/a1/sessions/s1/compact").json()

    assert set(body) == {"status", "message", "compacted", "record"}
