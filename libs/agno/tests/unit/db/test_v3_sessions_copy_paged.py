import json
import os
import tempfile
import time
from typing import Dict, List

import pytest
from sqlalchemy import text

from agno.db.migrations.versions import v3_0_0
from agno.db.sqlite import AsyncSqliteDb, SqliteDb


@pytest.fixture
def infos(monkeypatch) -> List[str]:
    messages: List[str] = []
    monkeypatch.setattr(v3_0_0, "log_info", messages.append)
    return messages


@pytest.fixture
def warnings(monkeypatch) -> List[str]:
    messages: List[str] = []
    monkeypatch.setattr(v3_0_0, "log_warning", messages.append)
    return messages


def _run(run_id: str) -> Dict[str, object]:
    return {"run_id": run_id, "agent_id": "a1", "status": "COMPLETED", "created_at": 1}


def _legacy_db(sessions: Dict[str, List[str]]) -> SqliteDb:
    """A SqliteDb whose sessions table still has the v2 `runs` column, holding the given run ids per session."""
    db = SqliteDb(db_file=os.path.join(tempfile.mkdtemp(), "legacy.db"))
    db._get_table("sessions", create_table_if_not_found=True)
    db._get_table("runs", create_table_if_not_found=True)
    now = int(time.time())
    with db.Session() as sess, sess.begin():
        sess.execute(text("ALTER TABLE agno_sessions ADD COLUMN runs TEXT"))
        for session_id, run_ids in sessions.items():
            sess.execute(
                text(
                    "INSERT INTO agno_sessions (session_id, session_type, agent_id, user_id, runs, created_at, updated_at) "
                    "VALUES (:sid, 'agent', 'a1', 'u1', :runs, :now, :now)"
                ),
                {"sid": session_id, "runs": json.dumps([_run(r) for r in run_ids]), "now": now},
            )
    return db


def _stored(db: SqliteDb) -> Dict[str, str]:
    with db.Session() as sess:
        return dict(sess.execute(text("SELECT run_id, session_id FROM agno_runs")).tuples().all())


def test_every_run_is_copied_across_pages(infos, warnings, monkeypatch):
    monkeypatch.setattr(v3_0_0, "BATCH_SIZE", 2)
    db = _legacy_db({f"s{i}": [f"s{i}-r0", f"s{i}-r1"] for i in range(5)})

    assert v3_0_0._migrate_sqlite_sessions(db, "agno_sessions") is True

    assert len(_stored(db)) == 10
    assert "-- Copied 10 runs from agno_sessions into the runs table" in infos
    assert warnings == []


def test_a_run_id_held_by_two_sessions_is_named_in_a_warning(infos, warnings):
    db = _legacy_db({"sess-a": ["shared", "a1"], "sess-b": ["shared", "b1"]})

    v3_0_0._migrate_sqlite_sessions(db, "agno_sessions")

    assert _stored(db) == {"shared": "sess-a", "a1": "sess-a", "b1": "sess-b"}
    assert "-- Copied 3 runs from agno_sessions into the runs table" in infos
    [warning] = warnings
    assert "1 run(s) were not copied" in warning
    assert "shared (kept for sess-a, not for sess-b)" in warning


def test_a_run_id_shared_across_pages_is_also_caught(infos, warnings, monkeypatch):
    monkeypatch.setattr(v3_0_0, "BATCH_SIZE", 1)
    db = _legacy_db({"sess-a": ["shared"], "sess-b": ["shared"]})

    v3_0_0._migrate_sqlite_sessions(db, "agno_sessions")

    assert _stored(db) == {"shared": "sess-a"}
    assert "shared (kept for sess-a, not for sess-b)" in warnings[0]


def test_a_rerun_copies_nothing_twice_and_warns_about_nothing(infos, warnings):
    db = _legacy_db({"sess-a": ["a0", "a1"], "sess-b": ["b0"]})
    v3_0_0._migrate_sqlite_sessions(db, "agno_sessions")
    infos.clear()

    v3_0_0._migrate_sqlite_sessions(db, "agno_sessions")

    assert len(_stored(db)) == 3
    assert "-- Copied 0 runs from agno_sessions into the runs table" in infos
    assert warnings == []


def test_a_failure_keeps_the_pages_already_committed(monkeypatch):
    monkeypatch.setattr(v3_0_0, "BATCH_SIZE", 1)
    db = _legacy_db({"s0": ["s0-r0"], "s1": ["s1-r0"], "s2": ["s2-r0"]})
    build = v3_0_0._build_run_rows

    def fail_on_s2(runs, session_id, user_id, run_data_as_string):
        if session_id == "s2":
            raise RuntimeError("process died")
        return build(runs, session_id, user_id, run_data_as_string)

    monkeypatch.setattr(v3_0_0, "_build_run_rows", fail_on_s2)
    with pytest.raises(RuntimeError):
        v3_0_0._migrate_sqlite_sessions(db, "agno_sessions")

    assert _stored(db) == {"s0-r0": "s0", "s1-r0": "s1"}


async def _async_legacy_db(sessions: Dict[str, List[str]]) -> AsyncSqliteDb:
    sync_db = _legacy_db(sessions)
    return AsyncSqliteDb(db_file=sync_db.db_file)


async def test_async_copies_across_pages(infos, monkeypatch):
    monkeypatch.setattr(v3_0_0, "BATCH_SIZE", 2)
    db = await _async_legacy_db({f"s{i}": [f"s{i}-r0", f"s{i}-r1"] for i in range(3)})

    assert await v3_0_0._migrate_async_sqlite_sessions(db, "agno_sessions") is True

    assert "-- Copied 6 runs from agno_sessions into the runs table" in infos


async def test_async_names_a_shared_run_id_in_a_warning(infos, warnings):
    db = await _async_legacy_db({"sess-a": ["shared", "a1"], "sess-b": ["shared", "b1"]})

    await v3_0_0._migrate_async_sqlite_sessions(db, "agno_sessions")

    assert "-- Copied 3 runs from agno_sessions into the runs table" in infos
    assert "shared (kept for sess-a, not for sess-b)" in warnings[0]
