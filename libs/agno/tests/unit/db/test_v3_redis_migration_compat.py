"""Tests for the v3.0.0 per-run-key storage in RedisDb.

Uses ``fakeredis`` so no real Redis instance is needed.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest

fakeredis = pytest.importorskip("fakeredis")

from agno.db.base import SessionType
from agno.db.redis.redis import RedisDb
from agno.db.redis.utils import generate_redis_key, serialize_data
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


def _new_db() -> RedisDb:
    return RedisDb(redis_client=fakeredis.FakeRedis(decode_responses=True), db_prefix="agno")


def _insert_legacy_session(db: RedisDb, session_id: str, runs: List[Dict[str, Any]]) -> None:
    """Write a v2.x-shaped session record directly (with inline `runs` field)."""
    data = {
        "session_id": session_id,
        "session_type": "agent",
        "agent_id": "agent-1",
        "user_id": "u1",
        "runs": runs,
        "session_data": {"session_state": {}},
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    }
    key = generate_redis_key(prefix=db.db_prefix, table_type="sessions", key_id=session_id)
    db.redis_client.set(key, serialize_data(data))


def test_fresh_schema_round_trip():
    db = _new_db()

    session = AgentSession(session_id="s1", agent_id="agent-1", user_id="u1")
    session.upsert_run(_make_run("r1", "s1", "one"))
    session.upsert_run(_make_run("r2", "s1", "two"))
    db.upsert_session(session)

    # Session record has no `runs` field
    raw = db._get_record("sessions", "s1")
    assert raw is not None and "runs" not in raw

    # Runs collection has both
    rows, total = db.get_runs(session_id="s1", deserialize=False)
    assert total == 2

    loaded = db.get_session("s1", SessionType.AGENT)
    assert [r.run_id for r in loaded.runs] == ["r1", "r2"]
    assert loaded.runs[0].messages[0].content == "q-one"


def test_legacy_blob_fallback_on_read():
    db = _new_db()
    runs = [_make_run(f"r{i}", "s2", f"c{i}").to_dict() for i in range(3)]
    _insert_legacy_session(db, "s2", runs)

    loaded = db.get_session("s2", SessionType.AGENT)
    assert [r.run_id for r in loaded.runs] == ["r0", "r1", "r2"]


def test_partial_state_merges_collection_and_blob():
    db = _new_db()
    legacy = [_make_run(f"rl{i}", "s4", f"c{i}").to_dict() for i in range(3)]
    _insert_legacy_session(db, "s4", legacy)

    # Migrate just one of the legacy runs into the runs keys via the helper directly
    middle = {
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
    db._store_record("runs", "rl1", middle, index_fields=["session_id"])
    db.redis_client.zadd(db._runs_by_session_index_key("s4"), {"rl1": 1.0})

    loaded = db.get_session("s4", SessionType.AGENT)
    assert {r.run_id for r in loaded.runs} == {"rl0", "rl1", "rl2"}


def test_v3_migration_is_non_destructive():
    db = _new_db()
    legacy = [_make_run(f"r{i}", "s6", f"c{i}").to_dict() for i in range(2)]
    _insert_legacy_session(db, "s6", legacy)

    from agno.db.migrations.versions.v3_0_0 import up as v3_up

    v3_up(db, table_type="sessions", table_name="agno_sessions")

    # Runs are in the runs keys
    rows, total = db.get_runs(session_id="s6", deserialize=False)
    assert total == 2

    # Legacy field is preserved on the session record
    raw = db._get_record("sessions", "s6")
    assert raw is not None and raw.get("runs") is not None


def test_cleanup_refuses_when_legacy_runs_still_present():
    db = _new_db()
    _insert_legacy_session(db, "s7", [_make_run("r1", "s7", "x").to_dict()])

    with pytest.raises(RuntimeError, match="Refusing to unset"):
        db.cleanup_legacy_runs_field()

    assert db.cleanup_legacy_runs_field(force=True) is True
    raw = db._get_record("sessions", "s7")
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
    # All run keys + the sorted-set index should be gone
    rows, total = db.get_runs(session_id="sx", deserialize=False)
    assert total == 0
