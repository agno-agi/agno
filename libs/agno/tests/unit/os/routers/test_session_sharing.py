"""AgentOS routes for sharing an agent session with other users."""

import tempfile
from pathlib import Path
from typing import Optional

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.os.middleware.user_scope import assert_session_writable
from agno.os.routers.session.session import get_session_router
from agno.os.settings import AgnoAPISettings
from agno.run.agent import RunOutput
from agno.session import AgentSession
from agno.session.sharing import SHARING_KEY, ajoin_shared_session, session_members


@pytest.fixture
def db():
    database = SqliteDb(db_file=str(Path(tempfile.mkdtemp()) / "sessions.db"))
    database.upsert_session(AgentSession(session_id="team", user_id="alice", agent_id="a1"))
    database.upsert_run(
        run=RunOutput(run_id="r1", session_id="team", user_id="alice", agent_id="a1", content="hi"),
        session_id="team",
        user_id="alice",
        run_index=0,
    )
    return database


def client(db, user: Optional[str]) -> TestClient:
    app = FastAPI()
    app.include_router(get_session_router({"default": [db]}, AgnoAPISettings()))

    class ScopedJWT(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.user_id = user
            request.state.user_isolation_enabled = True
            request.state.scopes = []
            return await call_next(request)

    if user is not None:
        app.add_middleware(ScopedJWT)
    return TestClient(app, raise_server_exceptions=False)


def share(db, user: Optional[str], members):
    return client(db, user).put("/sessions/team/sharing", json={"members": members})


def test_owner_shares_and_members_read(db):
    response = share(db, "alice", ["bob"])
    assert response.status_code == 200, response.text
    assert session_members(db.get_session(session_id="team", session_type=SessionType.AGENT)) == ["bob"]
    bob = client(db, "bob")
    assert bob.get("/sessions/team?type=agent").status_code == 200
    assert bob.get("/sessions/team/runs?type=agent").status_code == 200
    assert bob.get("/sessions/team/runs/r1?type=agent").status_code == 200
    assert client(db, "carol").get("/sessions/team?type=agent").status_code == 404


def test_only_owner_or_admin_changes_sharing(db):
    share(db, "alice", ["bob"])
    assert share(db, "bob", ["bob", "carol"]).status_code == 403
    assert share(db, "carol", ["carol"]).status_code == 404
    assert share(db, None, []).status_code == 200
    assert client(db, "bob").get("/sessions/team?type=agent").status_code == 404


def test_sharing_cannot_be_set_through_metadata(db):
    share(db, "alice", ["bob"])
    forged = {"metadata": {"tag": "x", SHARING_KEY: {"members": ["mallory"]}}}
    assert client(db, "alice").patch("/sessions/team?type=agent", json=forged).status_code == 200
    stored = db.get_session(session_id="team", session_type=SessionType.AGENT)
    assert stored.metadata["tag"] == "x"
    assert session_members(stored) == ["bob"]
    created = client(db, "mallory").post(
        "/sessions?type=agent", json={"session_id": "own", "metadata": {SHARING_KEY: {"members": ["eve"]}}}
    )
    assert created.status_code in (200, 201), created.text
    assert session_members(db.get_session(session_id="own", session_type=SessionType.AGENT)) == []


@pytest.mark.asyncio
async def test_run_guard_admits_members_only(db):
    share(db, "alice", ["bob"])
    await assert_session_writable(db, "team", "bob", session_type=SessionType.AGENT)
    with pytest.raises(HTTPException):
        await assert_session_writable(db, "team", "carol", session_type=SessionType.AGENT)


@pytest.mark.asyncio
async def test_chat_senders_join_the_thread_session(db):
    from agno.agent import Agent
    from agno.team import Team

    agent = Agent(id="a1", db=db)
    await ajoin_shared_session(agent, "team", "bob")
    await ajoin_shared_session(agent, "team", "alice")
    await ajoin_shared_session(Team(id="t1", members=[], db=db), "team", "carol")
    await ajoin_shared_session(agent, "missing", "dave")
    assert session_members(db.get_session(session_id="team", session_type=SessionType.AGENT)) == ["bob"]
    assert db.get_session(session_id="missing", session_type=SessionType.AGENT) is None
