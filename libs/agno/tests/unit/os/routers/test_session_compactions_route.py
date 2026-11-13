"""GET /sessions/{session_id}/compactions returns every compaction of a session, including the manual ones no run
made, so a client can show them after a reload."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.os.routers.session.session import get_session_router
from agno.session import AgentSession


def _row(compaction_id: str, created_at: int, run_id=None, session_id: str = "s1", archived: bool = True) -> dict:
    return {
        "compaction_id": compaction_id,
        "session_id": session_id,
        "run_id": run_id,
        "user_id": "alice",
        "first_kept_message_id": "m-19",
        "summary": "A long summary of the folded turns",
        "archived_messages": "the folded transcript" if archived else None,
        "messages_compacted": 18,
        "tokens_before": 15_864,
        "tokens_after": 3_981,
        "created_at": created_at,
    }


@pytest.fixture
def client(tmp_path) -> TestClient:
    db = SqliteDb(id="test-db", db_file=str(tmp_path / "sessions.db"))
    db.upsert_session(AgentSession(session_id="s1", agent_id="a1", user_id="alice", runs=[]))
    db.upsert_session(AgentSession(session_id="s2", agent_id="a1", user_id="alice", runs=[]))
    db.upsert_compaction(_row("auto-fold", created_at=100, run_id="r3"))
    db.upsert_compaction(_row("manual-fold", created_at=200, archived=False))
    db.upsert_compaction(_row("other-session", created_at=300, session_id="s2"))
    app = FastAPI()
    app.include_router(get_session_router({"test-db": [db]}))
    return TestClient(app)


def test_lists_manual_and_automatic_compactions_newest_first(client: TestClient):
    """A manual compaction is made by no run, so the records are the only place that has every compaction. It
    carries no run_id and is placed by created_at. The summary and the archived messages stay out: they are large,
    and they repeat conversation content."""
    response = client.get("/sessions/s1/compactions", params={"type": "agent"})

    numbers = {"messages_compacted": 18, "tokens_before": 15864, "tokens_after": 3981}
    assert response.status_code == 200
    assert response.json() == [
        {"id": "manual-fold", **numbers, "created_at": "1970-01-01T00:03:20Z", "archived": False},
        {"id": "auto-fold", "run_id": "r3", **numbers, "created_at": "1970-01-01T00:01:40Z", "archived": True},
    ]


def test_a_session_the_caller_cannot_read_is_a_404(client: TestClient):
    """The compactions follow the session's ownership, as its runs do."""
    assert client.get("/sessions/s1/compactions", params={"user_id": "bob"}).status_code == 404
    assert client.get("/sessions/does-not-exist/compactions").status_code == 404


def test_a_database_without_compaction_records_returns_none(tmp_path):
    """Only sync databases store compaction records. The rest have none to return, which is not an error."""
    db = AsyncSqliteDb(id="test-db", db_file=str(tmp_path / "sessions.db"))
    app = FastAPI()
    app.include_router(get_session_router({"test-db": [db]}))

    with TestClient(app) as client:
        assert client.post("/sessions", params={"type": "agent"}, json={"session_id": "s1"}).status_code in (200, 201)
        response = client.get("/sessions/s1/compactions")

    assert (response.status_code, response.json()) == (200, [])
