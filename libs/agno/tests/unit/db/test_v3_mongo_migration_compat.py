"""Tests for the v3.0.0 runs-collection migration in MongoDb.

Mirrors test_v3_migration_compat.py (the SQLite version), but exercises the Mongo
adapter via mongomock so no real MongoDB instance is needed.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest

mongomock = pytest.importorskip("mongomock")

from agno.db.base import SessionType  # noqa: E402
from agno.db.mongo.mongo import MongoDb  # noqa: E402
from agno.models.message import Message  # noqa: E402
from agno.run.agent import RunOutput  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402
from agno.session import AgentSession  # noqa: E402


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


def _new_db() -> MongoDb:
    client = mongomock.MongoClient()
    db = MongoDb(
        db_client=client,
        db_name="test_db",
        session_collection="agno_sessions",
        runs_collection="agno_runs",
    )
    db._database = client["test_db"]
    return db


def _insert_legacy_session(db: MongoDb, session_id: str, runs: List[Dict[str, Any]]) -> None:
    """Directly write a session document with a legacy `runs` array (simulates v2.x)."""
    db._database["agno_sessions"].insert_one(
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


def test_fresh_schema_round_trip():
    db = _new_db()

    session = AgentSession(session_id="s1", agent_id="agent-1", user_id="u1")
    session.upsert_run(_make_run("r1", "s1", "one"))
    session.upsert_run(_make_run("r2", "s1", "two"))
    db.upsert_session(session)

    raw = db._database["agno_sessions"].find_one({"session_id": "s1"})
    assert raw is not None and "runs" not in raw
    assert db._database["agno_runs"].count_documents({"session_id": "s1"}) == 2

    loaded = db.get_session("s1", SessionType.AGENT)
    assert [r.run_id for r in loaded.runs] == ["r1", "r2"]
    assert loaded.runs[0].messages[0].content == "q-one"


def test_legacy_blob_fallback_on_read():
    db = _new_db()
    runs = [_make_run(f"r{i}", "s2", f"c{i}").to_dict() for i in range(3)]
    _insert_legacy_session(db, "s2", runs)

    loaded = db.get_session("s2", SessionType.AGENT)
    assert [r.run_id for r in loaded.runs] == ["r0", "r1", "r2"]


def test_continue_legacy_session_writes_all_runs_to_collection():
    db = _new_db()
    legacy = [_make_run(f"r{i}", "s3", f"c{i}").to_dict() for i in range(2)]
    _insert_legacy_session(db, "s3", legacy)

    loaded = db.get_session("s3", SessionType.AGENT)
    assert len(loaded.runs) == 2

    loaded.upsert_run(_make_run("r2", "s3", "fresh"))
    db.upsert_session(loaded)

    ids = [d["run_id"] for d in db._database["agno_runs"].find({"session_id": "s3"}, sort=[("run_index", 1)])]
    assert ids == ["r0", "r1", "r2"]

    reloaded = db.get_session("s3", SessionType.AGENT)
    assert [r.run_id for r in reloaded.runs] == ["r0", "r1", "r2"]


def test_partial_state_merges_collection_and_blob():
    db = _new_db()
    legacy = [_make_run(f"rl{i}", "s4", f"c{i}").to_dict() for i in range(3)]
    _insert_legacy_session(db, "s4", legacy)

    db._database["agno_runs"].insert_one(
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
    )

    loaded = db.get_session("s4", SessionType.AGENT)
    assert {r.run_id for r in loaded.runs} == {"rl0", "rl1", "rl2"}


def test_partial_state_collection_wins_over_blob_on_conflict():
    db = _new_db()
    blob_version = _make_run("rx", "s5", "blob-version").to_dict()
    _insert_legacy_session(db, "s5", [blob_version])

    table_version = _make_run("rx", "s5", "collection-version").to_dict()
    db._database["agno_runs"].insert_one(
        {
            "run_id": "rx",
            "session_id": "s5",
            "run_type": "agent",
            "agent_id": "agent-1",
            "user_id": "u1",
            "status": "COMPLETED",
            "run_index": 0,
            "run_data": table_version,
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
        }
    )

    loaded = db.get_session("s5", SessionType.AGENT)
    assert len(loaded.runs) == 1
    assert loaded.runs[0].content == "collection-version"


def test_v3_migration_is_non_destructive():
    db = _new_db()
    legacy = [_make_run(f"r{i}", "s6", f"c{i}").to_dict() for i in range(2)]
    _insert_legacy_session(db, "s6", legacy)

    from agno.db.migrations.versions.v3_0_0 import up as v3_up

    v3_up(db, table_type="sessions", table_name="agno_sessions")

    assert db._database["agno_runs"].count_documents({"session_id": "s6"}) == 2

    raw = db._database["agno_sessions"].find_one({"session_id": "s6"})
    assert raw is not None and raw.get("runs") is not None


def test_cleanup_refuses_when_legacy_runs_still_present():
    db = _new_db()
    legacy = [_make_run("r1", "s7", "x").to_dict()]
    _insert_legacy_session(db, "s7", legacy)

    with pytest.raises(RuntimeError, match="Refusing to unset"):
        db.cleanup_legacy_runs_field()

    assert db.cleanup_legacy_runs_field(force=True) is True
    raw = db._database["agno_sessions"].find_one({"session_id": "s7"})
    assert raw is not None and "runs" not in raw


def test_cleanup_succeeds_after_migration():
    db = _new_db()
    legacy = [_make_run("r1", "s8", "x").to_dict()]
    _insert_legacy_session(db, "s8", legacy)

    from agno.db.migrations.versions.v3_0_0 import up as v3_up

    v3_up(db, table_type="sessions", table_name="agno_sessions")

    # Touch the session — the next write will null/unset the legacy field
    session = db.get_session("s8", SessionType.AGENT)
    db.upsert_session(session)

    assert db.cleanup_legacy_runs_field() in (True, False)
    raw = db._database["agno_sessions"].find_one({"session_id": "s8"})
    assert raw is not None and "runs" not in raw


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
    assert db._database["agno_runs"].count_documents({"session_id": "sx"}) == 0
