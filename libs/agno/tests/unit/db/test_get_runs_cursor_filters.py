"""get_runs cursor filters, has_unindexed_runs and get_session(include_runs) across adapters that run locally."""

import asyncio
import json
import sqlite3

import pytest

from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from tests.unit.db.run_cursor_contract import SESSION_ID, check_contract, seed


@pytest.fixture(params=["sqlite", "in_memory"])
def sync_db(request, tmp_path):
    if request.param == "sqlite":
        return SqliteDb(db_file=str(tmp_path / "runs.db"))
    return InMemoryDb()


def test_contract(sync_db):
    asyncio.run(check_contract(sync_db))


@pytest.mark.asyncio
async def test_async_sqlite_contract(tmp_path):
    await check_contract(AsyncSqliteDb(db_file=str(tmp_path / "runs.db")))


@pytest.mark.parametrize("blob, expected", [([{"run_id": "x"}], True), ([], False), (None, False)])
def test_sqlite_legacy_blob_is_unindexed(tmp_path, blob, expected):
    db_file = str(tmp_path / "runs.db")
    asyncio.run(seed(SqliteDb(db_file=db_file)))
    # Only a db migrated from v2 keeps the legacy runs column, so add it as the migration leaves it.
    con = sqlite3.connect(db_file)
    con.execute("ALTER TABLE agno_sessions ADD COLUMN runs TEXT")
    con.execute(
        "UPDATE agno_sessions SET runs = ? WHERE session_id = ?",
        (json.dumps(blob) if blob is not None else None, SESSION_ID),
    )
    con.commit()
    con.close()
    assert SqliteDb(db_file=db_file).has_unindexed_runs(SESSION_ID) is expected


def test_sqlite_null_run_index_is_unindexed(tmp_path):
    from sqlalchemy import update

    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    asyncio.run(seed(db))
    runs_table = db._get_table(table_type="runs")
    with db.Session() as sess, sess.begin():
        sess.execute(update(runs_table).where(runs_table.c.run_id == "r3").values(run_index=None))
    assert db.has_unindexed_runs(SESSION_ID) is True


def test_in_memory_run_without_index_is_unindexed():
    db = InMemoryDb()
    asyncio.run(seed(db))
    db._sessions[SESSION_ID]["runs"].append({"run_id": "loose", "agent_id": "agent-1"})
    assert db.has_unindexed_runs(SESSION_ID) is True


def test_unported_adapter_reports_unindexed():
    from agno.db.base import BaseDb

    assert BaseDb.has_unindexed_runs(object(), SESSION_ID) is True  # type: ignore[arg-type]
