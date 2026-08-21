"""Db-level opt-in auto-migration: ``SomeDb(auto_migrate=True)`` applies pending schema
migrations once, on the first cold table resolution, before that table is validated."""

import asyncio
import os
import sqlite3
import tempfile

import pytest

from agno.db.migrations.manager import MigrationManager
from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb

LATEST = MigrationManager.available_versions[-1][1].public


@pytest.fixture
def db_file():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, "auto_migrate.db")


def _stage_stale_evals_table(db_file: str) -> str:
    """Create the evals table the way an older Agno would have left it: stamped 2.0.0
    and without the user_id column v3 expects. Returns the table name."""
    db = SqliteDb(db_file=db_file)
    db._get_table(table_type="evals", create_table_if_not_found=True)
    db.upsert_schema_version(db.eval_table_name, "2.0.0")
    conn = sqlite3.connect(db_file)
    conn.execute(f"DROP INDEX IF EXISTS idx_{db.eval_table_name}_user_id")
    conn.execute(f"ALTER TABLE {db.eval_table_name} DROP COLUMN user_id")
    conn.commit()
    conn.close()
    return db.eval_table_name


def _columns(db_file: str, table: str) -> set:
    conn = sqlite3.connect(db_file)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_default_is_off_and_stale_table_is_rejected(db_file):
    table = _stage_stale_evals_table(db_file)
    db = SqliteDb(db_file=db_file)

    assert db.auto_migrate is False
    with pytest.raises(ValueError, match="has an invalid schema"):
        db._get_table(table_type="evals", create_table_if_not_found=True)
    # Nothing was applied behind the user's back.
    assert "user_id" not in _columns(db_file, table)
    assert db.get_latest_schema_version(table) == "2.0.0"


def test_auto_migrate_heals_stale_table_on_first_use(db_file):
    table = _stage_stale_evals_table(db_file)
    db = SqliteDb(db_file=db_file, auto_migrate=True)

    resolved = db._get_table(table_type="evals", create_table_if_not_found=True)

    assert resolved is not None
    assert "user_id" in _columns(db_file, table)
    assert db.get_latest_schema_version(table) == LATEST
    assert asyncio.run(MigrationManager(db).pending()) == []


def test_auto_migrate_runs_once_per_db(db_file, monkeypatch):
    _stage_stale_evals_table(db_file)
    db = SqliteDb(db_file=db_file, auto_migrate=True)
    calls = []
    original = MigrationManager.up_sync

    def counting(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MigrationManager, "up_sync", counting)

    db._get_table(table_type="evals", create_table_if_not_found=True)
    db._get_table(table_type="sessions", create_table_if_not_found=True)
    db._get_table(table_type="memories", create_table_if_not_found=True)

    assert len(calls) == 1


def test_auto_migrate_works_when_an_event_loop_is_running(db_file):
    """A sync adapter used from async code (FastAPI handlers, notebooks) must not
    trip over asyncio.run; the migration runs on a worker thread instead."""
    table = _stage_stale_evals_table(db_file)
    db = SqliteDb(db_file=db_file, auto_migrate=True)

    async def use_db_from_async_code():
        return db._get_table(table_type="evals", create_table_if_not_found=True)

    assert asyncio.run(use_db_from_async_code()) is not None
    assert "user_id" in _columns(db_file, table)


def test_fresh_database_with_auto_migrate_just_works(db_file):
    """No stale tables: auto_migrate is a no-op apart from stamping, and tables are created normally."""
    db = SqliteDb(db_file=db_file, auto_migrate=True)
    assert db._get_table(table_type="sessions", create_table_if_not_found=True) is not None
    assert asyncio.run(MigrationManager(db).pending()) == []


def test_async_adapter_auto_migrate_heals_stale_table_on_first_use(db_file):
    table = _stage_stale_evals_table(db_file)

    async def scenario():
        db = AsyncSqliteDb(db_file=db_file, auto_migrate=True)
        assert db.auto_migrate is True
        resolved = await db._get_table(table_type="evals", create_table_if_not_found=True)
        assert resolved is not None
        assert await db.get_latest_schema_version(table) == LATEST
        assert await MigrationManager(db).pending() == []

    asyncio.run(scenario())
    assert "user_id" in _columns(db_file, table)


def test_async_adapter_default_is_off(db_file):
    table = _stage_stale_evals_table(db_file)

    async def scenario():
        db = AsyncSqliteDb(db_file=db_file)
        assert db.auto_migrate is False
        with pytest.raises(ValueError, match="has an invalid schema"):
            await db._get_table(table_type="evals", create_table_if_not_found=True)

    asyncio.run(scenario())
    assert "user_id" not in _columns(db_file, table)


def test_up_sync_outside_and_inside_a_running_loop(db_file):
    _stage_stale_evals_table(db_file)
    db = SqliteDb(db_file=db_file)

    MigrationManager(db).up_sync()
    assert asyncio.run(MigrationManager(db).pending()) == []

    # Idempotent, and safe to call from inside a running loop too.
    async def inside():
        MigrationManager(db).up_sync()

    asyncio.run(inside())
    assert asyncio.run(MigrationManager(db).pending()) == []


def test_up_sync_refuses_async_adapters(db_file):
    with pytest.raises(TypeError, match="await MigrationManager"):
        MigrationManager(AsyncSqliteDb(db_file=db_file)).up_sync()
