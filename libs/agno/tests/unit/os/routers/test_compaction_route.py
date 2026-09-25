"""The compaction route's contract: a decline is a 200 with a status, not an error."""

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


@pytest.fixture
def client() -> TestClient:
    db = SqliteDb(db_file=str(Path(tempfile.mkdtemp()) / "compaction.db"))
    agent_os = AgentOS(agents=[Agent(id="a1", name="A", db=db, compaction=Compaction())])
    app = FastAPI()
    app.include_router(get_agent_router(agent_os))
    return TestClient(app)


def test_route_is_registered():
    db = SqliteDb(db_file=str(Path(tempfile.mkdtemp()) / "compaction.db"))
    agent_os = AgentOS(agents=[Agent(id="a1", db=db, compaction=Compaction())])

    paths = {(route.path, tuple(sorted(route.methods))) for route in get_agent_router(agent_os).routes}

    assert ("/agents/{agent_id}/sessions/{session_id}/compact", ("POST",)) in paths


def test_decline_is_a_200_with_a_reason(client: TestClient):
    """Declining to fold is a normal outcome, so a UI must not have to treat it as an error.

    Raising would make "folding would not help here" indistinguishable from a failure.
    """
    response = client.post("/agents/a1/sessions/does-not-exist/compact")

    assert response.status_code == 200
    body = response.json()
    assert body["compacted"] is False
    assert body["status"] == "no_history"
    assert body["message"]  # always something displayable
    assert body["record"] is None


def test_unknown_agent_is_a_404(client: TestClient):
    """A missing agent IS an error - it means the caller asked for something that does not exist."""
    response = client.post("/agents/nope/sessions/s1/compact")

    assert response.status_code == 404


def test_response_shape_is_stable(client: TestClient):
    """These four keys are the contract the FE renders; adding is safe, renaming is not."""
    body = client.post("/agents/a1/sessions/s1/compact").json()

    assert set(body) == {"status", "message", "compacted", "record"}
