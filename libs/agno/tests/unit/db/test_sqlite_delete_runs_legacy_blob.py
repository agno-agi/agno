"""``delete_run``/``delete_runs`` must remove a run from the legacy ``runs`` blob together with its row.

A session written by agno 2.x keeps its history in the ``runs`` column; agno 3
merges that blob with the runs table on every read. Two gaps let a deleted run
come back on the next read:

- ``delete_runs`` returned before scrubbing the blob when the runs table did not
  exist yet, which is the state of every 2.x database nothing has appended to;
- the scrub ran in a second, best-effort transaction whose failure was swallowed,
  so the row delete could commit while the blob kept the run.

Both are covered here against SQLite; the same change is applied to the
Postgres, MySQL and SingleStore adapters.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.run.agent import RunOutput

_LEGACY_SESSIONS_DDL = (
    "CREATE TABLE agno_sessions (session_id TEXT PRIMARY KEY, session_type TEXT, user_id TEXT, "
    "agent_id TEXT, team_id TEXT, workflow_id TEXT, session_data JSON, agent_data JSON, team_data JSON, "
    "workflow_data JSON, metadata JSON, summary JSON, runs JSON, created_at INTEGER, updated_at INTEGER)"
)


def _legacy_db(tmp_path, run_ids):
    """A 2.x-shaped database: sessions table with a runs blob, no runs table."""
    db_file = str(tmp_path / "legacy.db")
    blob = [
        {"run_id": run_id, "agent_id": "a1", "status": "COMPLETED", "created_at": index}
        for index, run_id in enumerate(run_ids)
    ]
    con = sqlite3.connect(db_file)
    con.execute(_LEGACY_SESSIONS_DDL)
    # 2.x stored the JSON text of the list inside the JSON column.
    con.execute(
        "INSERT INTO agno_sessions (session_id, session_type, agent_id, runs, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        ("s1", "agent", "a1", json.dumps(json.dumps(blob)), 1000, 1000),
    )
    con.commit()
    con.close()
    return SqliteDb(db_file=db_file), db_file


def _blob_ids(db_file):
    con = sqlite3.connect(db_file)
    try:
        (raw,) = con.execute("SELECT runs FROM agno_sessions WHERE session_id = 's1'").fetchone()
    finally:
        con.close()
    return [run["run_id"] for run in json.loads(json.loads(raw))]


def _loaded_ids(db):
    return [run.run_id for run in db.get_session("s1").runs]


def test_delete_runs_scrubs_the_blob_before_any_run_row_exists(tmp_path):
    db, db_file = _legacy_db(tmp_path, ["r0", "r1", "r2"])
    assert _loaded_ids(db) == ["r0", "r1", "r2"]

    db.delete_runs(["r1"])

    assert _blob_ids(db_file) == ["r0", "r2"]
    assert _loaded_ids(db) == ["r0", "r2"]


def test_delete_run_scrubs_the_blob_before_any_run_row_exists(tmp_path):
    db, db_file = _legacy_db(tmp_path, ["r0", "r1"])

    assert db.delete_run("r0") is False  # no row existed, but the blob entry is gone
    assert _blob_ids(db_file) == ["r1"]
    assert _loaded_ids(db) == ["r1"]


def test_a_failed_scrub_rolls_back_the_row_delete(tmp_path):
    db, db_file = _legacy_db(tmp_path, ["r0", "r1"])
    db.upsert_run(RunOutput(run_id="r2", agent_id="a1", session_id="s1"), session_id="s1")
    assert _loaded_ids(db) == ["r0", "r1", "r2"]

    con = sqlite3.connect(db_file)
    con.execute(
        "CREATE TRIGGER refuse_blob_rewrite BEFORE UPDATE OF runs ON agno_sessions "
        "BEGIN SELECT RAISE(ABORT, 'blob rewrite refused'); END"
    )
    con.commit()
    con.close()

    with pytest.raises(Exception, match="blob rewrite refused"):
        db.delete_runs(["r0", "r2"])

    # Neither surface changed: the row delete did not commit without the scrub.
    assert _blob_ids(db_file) == ["r0", "r1"]
    assert _loaded_ids(db) == ["r0", "r1", "r2"]


@pytest.mark.asyncio
async def test_async_delete_runs_scrubs_the_blob_before_any_run_row_exists(tmp_path):
    _, db_file = _legacy_db(tmp_path, ["r0", "r1", "r2"])
    db = AsyncSqliteDb(db_file=db_file)
    try:
        await db.delete_runs(["r1"])
        assert _blob_ids(db_file) == ["r0", "r2"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_async_failed_scrub_rolls_back_the_row_delete(tmp_path):
    _, db_file = _legacy_db(tmp_path, ["r0", "r1"])
    db = AsyncSqliteDb(db_file=db_file)
    try:
        await db.upsert_run(RunOutput(run_id="r2", agent_id="a1", session_id="s1"), session_id="s1")
        con = sqlite3.connect(db_file)
        con.execute(
            "CREATE TRIGGER refuse_blob_rewrite BEFORE UPDATE OF runs ON agno_sessions "
            "BEGIN SELECT RAISE(ABORT, 'blob rewrite refused'); END"
        )
        con.commit()
        con.close()

        with pytest.raises(Exception, match="blob rewrite refused"):
            await db.delete_runs(["r0", "r2"])

        assert _blob_ids(db_file) == ["r0", "r1"]
        assert await db.get_run("r2") is not None
    finally:
        await db.close()
