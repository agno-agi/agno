"""Tests for the v3.0.0 runs-list storage in JsonDb."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

from agno.db.base import SessionType
from agno.db.json.json_db import JsonDb
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession


def _make_run(run_id: str, session_id: str, content: str) -> RunOutput:
    return RunOutput(
        run_id=run_id,
        agent_id="agent-1",
        session_id=session_id,
        content=content,
        status=RunStatus.completed,
        messages=[
            Message(role="user", content=f"q-{content}"),
            Message(role="assistant", content=f"a-{content}"),
        ],
    )


def _new_db() -> JsonDb:
    return JsonDb(db_path=tempfile.mkdtemp())


def _insert_legacy_session(db: JsonDb, session_id: str, runs: List[Dict[str, Any]]) -> None:
    sessions_path = Path(db.db_path) / f"{db.session_table_name}.json"
    sessions_path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if sessions_path.exists():
        with open(sessions_path) as f:
            existing = json.load(f)
    existing.append(
        {
            "session_id": session_id,
            "session_type": "agent",
            "agent_id": "agent-1",
            "user_id": "u1",
            "runs": runs,
            "session_data": {"session_state": {}},
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
        }
    )
    with open(sessions_path, "w") as f:
        json.dump(existing, f, default=str)


def test_fresh_schema_round_trip():
    db = _new_db()
    session = AgentSession(session_id="s1", agent_id="agent-1", user_id="u1")
    session.upsert_run(_make_run("r1", "s1", "one"))
    session.upsert_run(_make_run("r2", "s1", "two"))
    db.upsert_session(session)

    # Session record has no `runs` field
    sessions = db._read_json_file(db.session_table_name)
    assert len(sessions) == 1 and "runs" not in sessions[0]

    # Runs file has both
    rows = db._read_runs_file()
    assert len(rows) == 2

    loaded = db.get_session("s1", SessionType.AGENT)
    assert [r.run_id for r in loaded.runs] == ["r1", "r2"]
    assert loaded.runs[0].messages[0].content == "q-one"


def test_legacy_blob_fallback_on_read():
    db = _new_db()
    runs = [_make_run(f"r{i}", "s2", f"c{i}").to_dict() for i in range(3)]
    _insert_legacy_session(db, "s2", runs)

    loaded = db.get_session("s2", SessionType.AGENT)
    assert [r.run_id for r in loaded.runs] == ["r0", "r1", "r2"]


def test_partial_state_merges():
    db = _new_db()
    legacy = [_make_run(f"rl{i}", "s4", f"c{i}").to_dict() for i in range(3)]
    _insert_legacy_session(db, "s4", legacy)

    # Migrate one of the legacy runs by hand into the runs file
    db._write_runs_file([
        {
            "run_id": "rl1",
            "session_id": "s4",
            "run_type": "agent",
            "agent_id": "agent-1",
            "user_id": "u1",
            "status": "COMPLETED",
            "run_index": 1,
            "run_data": legacy[1],
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
        }
    ])

    loaded = db.get_session("s4", SessionType.AGENT)
    assert {r.run_id for r in loaded.runs} == {"rl0", "rl1", "rl2"}


def test_v3_migration_is_non_destructive():
    db = _new_db()
    legacy = [_make_run(f"r{i}", "s6", f"c{i}").to_dict() for i in range(2)]
    _insert_legacy_session(db, "s6", legacy)

    from agno.db.migrations.versions.v3_0_0 import up as v3_up

    v3_up(db, table_type="sessions", table_name=db.session_table_name)

    assert len(db._read_runs_file()) == 2

    sessions = db._read_json_file(db.session_table_name)
    assert sessions[0].get("runs") is not None


def test_cleanup_refuses_when_legacy_runs_still_present():
    db = _new_db()
    _insert_legacy_session(db, "s7", [_make_run("r1", "s7", "x").to_dict()])

    import pytest

    with pytest.raises(RuntimeError, match="Refusing to unset"):
        db.cleanup_legacy_runs_field()

    assert db.cleanup_legacy_runs_field(force=True) is True
    sessions = db._read_json_file(db.session_table_name)
    assert "runs" not in sessions[0]


def test_get_run_get_runs_apis():
    db = _new_db()
    session = AgentSession(session_id="sx", agent_id="agent-1", user_id="u1")
    for i in range(3):
        session.upsert_run(_make_run(f"r{i}", "sx", f"c{i}"))
    db.upsert_session(session)

    run = db.get_run("r1")
    assert run is not None and run.content == "c1"

    runs = db.get_runs(session_id="sx")
    assert [r.run_id for r in runs] == ["r0", "r1", "r2"]

    db.delete_session("sx")
    assert len(db._read_runs_file()) == 0
