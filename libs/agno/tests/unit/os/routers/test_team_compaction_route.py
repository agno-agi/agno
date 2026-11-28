"""The team compaction route's contract, the same as the agent's: a decline is a 200 with a status, a missing
session is a 404."""

import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.sqlite import SqliteDb
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.os import AgentOS
from agno.os.routers.teams.router import get_team_router
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team import Team


class _Summarizer:
    id = "stub"

    async def aresponse(self, messages, **kwargs):
        return ModelResponse(content="SUMMARY OF THE EARLIER TURNS")


def _run(number: int) -> TeamRunOutput:
    pad = "pad " * 300
    return TeamRunOutput(
        run_id=f"r{number}",
        team_id="t1",
        session_id="s-history",
        status=RunStatus.completed,
        messages=[
            Message(role="user", content=f"question {number} {pad}"),
            Message(role="assistant", content=f"answer {number} {pad}"),
        ],
    )


def _team(team_id: str, db: SqliteDb, compaction=None) -> Team:
    return Team(id=team_id, members=[Agent(id=f"{team_id}-member")], db=db, compaction=compaction)


def _client(authorization: bool = False) -> TestClient:
    db = SqliteDb(db_file=str(Path(tempfile.mkdtemp()) / "compaction.db"))
    db.upsert_session(TeamSession(session_id="s1", team_id="t1", runs=[]))
    db.upsert_session(TeamSession(session_id="s2", team_id="t2", runs=[]))
    db.upsert_session(TeamSession(session_id="s-history", team_id="t1", runs=[]))
    for number in range(6):
        db.upsert_run(run=_run(number), session_id="s-history")
    db.upsert_session(TeamSession(session_id="s3", team_id="t3", runs=[]))
    folding = Compaction(compact_at_tokens=None, uncompacted_runs=1, model=_Summarizer())
    teams = [_team("t1", db, folding), _team("t2", db, Compaction()), _team("t3", db)]
    app = FastAPI()
    if authorization:

        @app.middleware("http")
        async def enable_authorization(request, call_next):
            request.state.authorization_enabled = True
            return await call_next(request)

    app.include_router(get_team_router(AgentOS(teams=teams)))
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    return _client()


def test_route_is_registered():
    db = SqliteDb(db_file=str(Path(tempfile.mkdtemp()) / "compaction.db"))

    paths = {
        (route.path, tuple(sorted(route.methods))) for route in get_team_router(AgentOS(teams=[_team("t1", db)])).routes
    }

    assert ("/teams/{team_id}/sessions/{session_id}/compact", ("POST",)) in paths


def test_the_leaders_conversation_is_folded_and_the_record_names_the_team(client: TestClient):
    response = client.post("/teams/t1/sessions/s-history/compact")

    assert response.status_code == 200
    body = response.json()
    assert body["compacted"] is True and body["status"] == "compacted"
    assert body["record"]["messages_compacted"] == 10
    assert body["record"]["owner_id"] == "t1"


def test_decline_is_a_200_with_a_reason(client: TestClient):
    response = client.post("/teams/t1/sessions/s1/compact")

    assert response.status_code == 200
    body = response.json()
    assert body["compacted"] is False and body["status"] == "no_history"
    assert body["message"] and body["record"] is None


def test_a_team_without_compaction_says_so(client: TestClient):
    body = client.post("/teams/t3/sessions/s3/compact").json()

    assert body["compacted"] is False and body["status"] == "not_enabled"


def test_unknown_session_is_a_404(client: TestClient):
    assert client.post("/teams/t1/sessions/does-not-exist/compact").status_code == 404


def test_unknown_team_is_a_404(client: TestClient):
    assert client.post("/teams/nope/sessions/s1/compact").status_code == 404


def test_another_teams_session_is_a_404(monkeypatch):
    """The resource gate authorised t1, so t1's route must not fold t2's session."""

    async def may_run_t1_only(request, resource_id, resource_type, action):
        return resource_id == "t1"

    monkeypatch.setattr("agno.os.auth.acheck_resource_access", may_run_t1_only)
    client = _client(authorization=True)

    assert client.post("/teams/t1/sessions/s2/compact").status_code == 404


def test_response_shape_is_the_agent_routes(client: TestClient):
    body = client.post("/teams/t1/sessions/s1/compact").json()

    assert set(body) == {"status", "message", "compacted", "record", "metrics"}
