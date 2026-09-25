import json
import logging
import os
import tempfile
import time
from typing import Dict, List

import pytest
from sqlalchemy import text

from agno.db.migrations.versions import v3_0_0
from agno.db.sqlite import AsyncSqliteDb, SqliteDb


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: List[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def logged():
    """Agno's logger sets propagate=False, so caplog never sees these; attach a handler directly."""
    logger = logging.getLogger("agno")
    handler = _Collect()
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield handler.records
    logger.removeHandler(handler)
    logger.setLevel(old_level)


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


def _messages(records: List[logging.LogRecord], level: int) -> List[str]:
    return [r.getMessage() for r in records if r.levelno == level]


def test_every_run_is_copied_across_pages(logged, monkeypatch):
    monkeypatch.setattr(v3_0_0, "BATCH_SIZE", 2)
    db = _legacy_db({f"s{i}": [f"s{i}-r0", f"s{i}-r1"] for i in range(5)})

    assert v3_0_0._migrate_sqlite_sessions(db, "agno_sessions") is True

    assert len(_stored(db)) == 10
    assert "-- Copied 10 runs from agno_sessions into the runs table" in _messages(logged, logging.INFO)
    assert _messages(logged, logging.WARNING) == []


def test_a_run_id_held_by_two_sessions_is_named_in_a_warning(logged):
    db = _legacy_db({"sess-a": ["shared", "a1"], "sess-b": ["shared", "b1"]})

    v3_0_0._migrate_sqlite_sessions(db, "agno_sessions")

    assert _stored(db) == {"shared": "sess-a", "a1": "sess-a", "b1": "sess-b"}
    assert "-- Copied 3 runs from agno_sessions into the runs table" in _messages(logged, logging.INFO)
    [warning] = _messages(logged, logging.WARNING)
    assert "1 run(s) were not copied" in warning
    assert "shared (kept for sess-a, not for sess-b)" in warning


def test_a_run_id_shared_across_pages_is_also_caught(logged, monkeypatch):
    monkeypatch.setattr(v3_0_0, "BATCH_SIZE", 1)
    db = _legacy_db({"sess-a": ["shared"], "sess-b": ["shared"]})

    v3_0_0._migrate_sqlite_sessions(db, "agno_sessions")

    assert _stored(db) == {"shared": "sess-a"}
    assert "shared (kept for sess-a, not for sess-b)" in _messages(logged, logging.WARNING)[0]


def test_a_rerun_copies_nothing_twice_and_warns_about_nothing(logged):
    db = _legacy_db({"sess-a": ["a0", "a1"], "sess-b": ["b0"]})
    v3_0_0._migrate_sqlite_sessions(db, "agno_sessions")
    logged.clear()

    v3_0_0._migrate_sqlite_sessions(db, "agno_sessions")

    assert len(_stored(db)) == 3
    assert "-- Copied 0 runs from agno_sessions into the runs table" in _messages(logged, logging.INFO)
    assert _messages(logged, logging.WARNING) == []


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


async def test_async_copies_across_pages(logged, monkeypatch):
    monkeypatch.setattr(v3_0_0, "BATCH_SIZE", 2)
    db = await _async_legacy_db({f"s{i}": [f"s{i}-r0", f"s{i}-r1"] for i in range(3)})

    assert await v3_0_0._migrate_async_sqlite_sessions(db, "agno_sessions") is True

    assert "-- Copied 6 runs from agno_sessions into the runs table" in _messages(logged, logging.INFO)


async def test_async_names_a_shared_run_id_in_a_warning(logged):
    db = await _async_legacy_db({"sess-a": ["shared", "a1"], "sess-b": ["shared", "b1"]})

    await v3_0_0._migrate_async_sqlite_sessions(db, "agno_sessions")

    assert "-- Copied 3 runs from agno_sessions into the runs table" in _messages(logged, logging.INFO)
    assert "shared (kept for sess-a, not for sess-b)" in _messages(logged, logging.WARNING)[0]
