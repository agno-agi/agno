"""Unit tests for the active_run field on GET /sessions/{session_id}.

The field surfaces the thread's in-progress run (PENDING/RUNNING whose event
stream is still live) so a client opening a conversation learns — from the
same response that carries its history — whether an answer is still being
generated and which run to reattach to.
"""

import time
import uuid

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


class _ProbeStream:
    """Event stream stub whose liveness answer varies per run_id."""

    def __init__(self, statuses):
        self.statuses = statuses

    async def get_run_status(self, run_id):
        return self.statuses.get(run_id)


def _build_client(db):
    from agno.os.routers.session.session import attach_routes

    app = FastAPI()
    router = APIRouter()
    attach_routes(router, {"default": [db]})
    app.include_router(router)
    return TestClient(app)


def _seed_session(db: InMemoryDb, runs) -> str:
    uid = uuid.uuid4().hex[:8]
    now = int(time.time())
    session = AgentSession(
        session_id=f"agent-{uid}",
        agent_id="test-agent",
        user_id="user-1",
        session_data={"session_name": "Chat"},
        created_at=now,
        updated_at=now,
        runs=runs,
    )
    db.upsert_session(session)
    return session.session_id


def _run(run_id: str, status: RunStatus) -> RunOutput:
    return RunOutput(run_id=run_id, agent_id="test-agent", user_id="user-1", status=status)


def test_detail_reports_live_running_run(monkeypatch):
    monkeypatch.setattr("agno.os.event_streams.get_event_stream", lambda: _ProbeStream({"r1": RunStatus.running}))
    db = InMemoryDb()
    session_id = _seed_session(db, [_run("r0", RunStatus.completed), _run("r1", RunStatus.running)])
    client = _build_client(db)

    response = client.get(f"/sessions/{session_id}?type=agent")

    assert response.status_code == 200
    active_run = response.json().get("active_run")
    assert active_run is not None
    assert active_run["run_id"] == "r1"
    assert active_run["status"] == "RUNNING"


def test_detail_omits_active_run_when_all_completed(monkeypatch):
    monkeypatch.setattr("agno.os.event_streams.get_event_stream", lambda: _ProbeStream({}))
    db = InMemoryDb()
    session_id = _seed_session(db, [_run("r0", RunStatus.completed)])
    client = _build_client(db)

    response = client.get(f"/sessions/{session_id}?type=agent")

    assert response.status_code == 200
    assert "active_run" not in response.json()


def test_detail_omits_zombie_running_row(monkeypatch):
    # Server restarted: the row still says RUNNING but the stream no longer knows it
    monkeypatch.setattr("agno.os.event_streams.get_event_stream", lambda: _ProbeStream({}))
    db = InMemoryDb()
    session_id = _seed_session(db, [_run("r1", RunStatus.running)])
    client = _build_client(db)

    response = client.get(f"/sessions/{session_id}?type=agent")

    assert response.status_code == 200
    assert "active_run" not in response.json()


def test_detail_omits_paused_run(monkeypatch):
    # PAUSED runs wait on human input and follow the HITL resume flow, not reattach
    monkeypatch.setattr("agno.os.event_streams.get_event_stream", lambda: _ProbeStream({"r1": RunStatus.paused}))
    db = InMemoryDb()
    session_id = _seed_session(db, [_run("r1", RunStatus.paused)])
    client = _build_client(db)

    response = client.get(f"/sessions/{session_id}?type=agent")

    assert response.status_code == 200
    assert "active_run" not in response.json()


def test_detail_picks_newest_live_run(monkeypatch):
    monkeypatch.setattr(
        "agno.os.event_streams.get_event_stream",
        lambda: _ProbeStream({"r1": RunStatus.running, "r2": RunStatus.running}),
    )
    db = InMemoryDb()
    session_id = _seed_session(db, [_run("r1", RunStatus.running), _run("r2", RunStatus.pending)])
    client = _build_client(db)

    response = client.get(f"/sessions/{session_id}?type=agent")

    assert response.status_code == 200
    assert response.json()["active_run"]["run_id"] == "r2"


def test_detail_without_runs_omits_active_run():
    db = InMemoryDb()
    session_id = _seed_session(db, [])
    client = _build_client(db)

    response = client.get(f"/sessions/{session_id}?type=agent")

    assert response.status_code == 200
    assert "active_run" not in response.json()
