"""Migrations choose their SQL by database type, so a subclass of a shipped adapter
must get the same migrations instead of being skipped while the version is stamped."""

import sqlite3
from unittest.mock import AsyncMock, patch

import pytest

from agno.db.migrations.manager import MigrationManager
from agno.db.migrations.versions import v2_5_6
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb


class MySqliteDb(SqliteDb):
    pass


class MyAsyncSqliteDb(AsyncSqliteDb):
    pass


class MyPostgresDb(PostgresDb):
    pass


class MyAsyncPostgresDb(AsyncPostgresDb):
    pass


def _approvals_table_before_2_5_6(db_file: str) -> None:
    con = sqlite3.connect(db_file)
    con.execute("CREATE TABLE agno_approvals (id TEXT PRIMARY KEY, run_id TEXT)")
    con.commit()
    con.close()


def _columns(db_file: str) -> list:
    con = sqlite3.connect(db_file)
    columns = [row[1] for row in con.execute("PRAGMA table_info(agno_approvals)")]
    con.close()
    return columns


@pytest.mark.asyncio
@pytest.mark.parametrize("db_class", [SqliteDb, MySqliteDb], ids=["adapter", "subclass"])
async def test_sqlite_subclass_is_migrated(tmp_path, db_class):
    db_file = str(tmp_path / "agno.db")
    _approvals_table_before_2_5_6(db_file)
    db = db_class(db_file=db_file, approvals_table="agno_approvals")
    db.upsert_schema_version("agno_approvals", "2.5.0")

    await MigrationManager(db).up(target_version="2.5.6", table_type="approvals")

    assert "run_status" in _columns(db_file)
    assert db.get_latest_schema_version("agno_approvals") == "2.5.6"


@pytest.mark.asyncio
@pytest.mark.parametrize("db_class", [AsyncSqliteDb, MyAsyncSqliteDb], ids=["adapter", "subclass"])
async def test_async_sqlite_subclass_is_migrated(tmp_path, db_class):
    db_file = str(tmp_path / "agno.db")
    _approvals_table_before_2_5_6(db_file)
    db = db_class(db_file=db_file, approvals_table="agno_approvals")
    await db.upsert_schema_version("agno_approvals", "2.5.0")

    await MigrationManager(db).up(target_version="2.5.6", table_type="approvals")

    assert "run_status" in _columns(db_file)
    assert await db.get_latest_schema_version("agno_approvals") == "2.5.6"


@patch.object(v2_5_6, "_migrate_postgres", return_value=True)
def test_postgres_subclass_dispatches_to_postgres_migration(mock_fn):
    db = object.__new__(MyPostgresDb)

    assert v2_5_6.up(db, "approvals", "agno_approvals") is True
    mock_fn.assert_called_once_with(db, "agno_approvals")


@pytest.mark.asyncio
@patch.object(v2_5_6, "_migrate_async_postgres", new_callable=AsyncMock, return_value=True)
async def test_async_postgres_subclass_dispatches_to_postgres_migration(mock_fn):
    db = object.__new__(MyAsyncPostgresDb)

    assert await v2_5_6.async_up(db, "approvals", "agno_approvals") is True
    mock_fn.assert_awaited_once_with(db, "agno_approvals")
