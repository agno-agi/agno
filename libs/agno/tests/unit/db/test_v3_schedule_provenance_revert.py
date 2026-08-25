"""The v3.0.0 revert takes the schedule provenance columns and indexes back off.

up() adds eight nullable provenance columns plus the managed_by / target_id lookup
indexes to the schedules table on SQLite and PostgreSQL. down(target_version="2.5.6")
has to leave the table in the shape 2.5.6 declared, or a downgraded install carries
columns and indexes its own schema never mentions.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile

import pytest

from agno.db.migrations.manager import MigrationManager
from agno.db.migrations.versions.v3_0_0 import SCHEDULE_PROVENANCE_COLUMNS, SCHEDULE_PROVENANCE_INDEXED
from agno.db.sqlite import AsyncSqliteDb, SqliteDb

SCHEDULES_TABLE = "agno_schedules"
COMPONENTS_TABLE = "agno_components"
PROVENANCE_INDEXES = {f"idx_{SCHEDULES_TABLE}_{column}" for column in SCHEDULE_PROVENANCE_INDEXED}


def _table_columns(db_file: str, table: str) -> set:
    conn = sqlite3.connect(db_file)
    try:
        return {c[1] for c in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        conn.close()


def _table_indexes(db_file: str, table: str) -> set:
    conn = sqlite3.connect(db_file)
    try:
        return {i[1] for i in conn.execute(f"PRAGMA index_list({table})").fetchall()}
    finally:
        conn.close()


def _new_schedules_db():
    db_file = os.path.join(tempfile.mkdtemp(), "provenance.db")
    db = SqliteDb(db_file=db_file)
    db._get_table(table_type="schedules", create_table_if_not_found=True)
    return db, db_file


def _legacy_insert(db_file: str) -> None:
    """A 2.5.6-shaped INSERT, naming only the columns that version declared."""
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            f"INSERT INTO {SCHEDULES_TABLE} "
            "(id, name, cron_expr, endpoint, method, timezone, timeout_seconds, "
            " max_retries, retry_delay_seconds, enabled, created_at) "
            "VALUES ('s1', 'nightly', '0 9 * * *', '/x', 'POST', 'UTC', 3600, 0, 60, 1, 1)"
        )
        conn.commit()
    finally:
        conn.close()


def test_sqlite_revert_drops_provenance_columns_and_indexes():
    db, db_file = _new_schedules_db()
    assert set(SCHEDULE_PROVENANCE_COLUMNS) <= _table_columns(db_file, SCHEDULES_TABLE)
    assert PROVENANCE_INDEXES <= _table_indexes(db_file, SCHEDULES_TABLE)

    asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="schedules"))

    columns = _table_columns(db_file, SCHEDULES_TABLE)
    assert not columns & set(SCHEDULE_PROVENANCE_COLUMNS)
    assert not _table_indexes(db_file, SCHEDULES_TABLE) & PROVENANCE_INDEXES
    assert "user_id" not in columns
    _legacy_insert(db_file)


def test_sqlite_up_after_provenance_revert_restores_everything():
    db, db_file = _new_schedules_db()
    asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="schedules"))
    assert not _table_columns(db_file, SCHEDULES_TABLE) & set(SCHEDULE_PROVENANCE_COLUMNS)

    asyncio.run(MigrationManager(db).up(table_type="schedules"))

    assert set(SCHEDULE_PROVENANCE_COLUMNS) <= _table_columns(db_file, SCHEDULES_TABLE)
    assert PROVENANCE_INDEXES <= _table_indexes(db_file, SCHEDULES_TABLE)
    assert db.get_latest_schema_version(SCHEDULES_TABLE) == "3.0.0"


def test_sqlite_revert_tolerates_a_partly_migrated_table():
    """up() adds each column only when it is missing, so half-migrated tables exist."""
    db, db_file = _new_schedules_db()
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(f"DROP INDEX idx_{SCHEDULES_TABLE}_target_id")
        for column in ("target_id", "disabled_reason", "updated_by_run_id"):
            conn.execute(f"ALTER TABLE {SCHEDULES_TABLE} DROP COLUMN {column}")
        conn.commit()
    finally:
        conn.close()

    asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="schedules"))

    assert not _table_columns(db_file, SCHEDULES_TABLE) & set(SCHEDULE_PROVENANCE_COLUMNS)
    assert not _table_indexes(db_file, SCHEDULES_TABLE) & PROVENANCE_INDEXES


def test_sqlite_revert_stamps_a_table_that_only_has_provenance_left():
    """user_id already gone, provenance still there: the revert has real work to
    do, so it has to report it and the version stamp has to move."""
    db, db_file = _new_schedules_db()
    conn = sqlite3.connect(db_file)
    try:
        for index in (
            f"idx_{SCHEDULES_TABLE}_user_id",
            f"idx_{SCHEDULES_TABLE}_user_id_enabled_next_run_at",
            f"{SCHEDULES_TABLE}_uq_user_name",
            f"{SCHEDULES_TABLE}_uq_unowned_name",
        ):
            conn.execute(f"DROP INDEX IF EXISTS {index}")
        conn.execute(f"ALTER TABLE {SCHEDULES_TABLE} DROP COLUMN user_id")
        conn.commit()
    finally:
        conn.close()

    asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="schedules"))

    assert not _table_columns(db_file, SCHEDULES_TABLE) & set(SCHEDULE_PROVENANCE_COLUMNS)
    assert db.get_latest_schema_version(SCHEDULES_TABLE) == "2.5.6"


def test_sqlite_revert_leaves_provenance_alone_on_old_sqlite(monkeypatch):
    """DROP COLUMN needs SQLite 3.35.0; below it the revert must change nothing at all."""
    db, db_file = _new_schedules_db()
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 34, 0))

    asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="schedules"))

    assert set(SCHEDULE_PROVENANCE_COLUMNS) <= _table_columns(db_file, SCHEDULES_TABLE)
    assert PROVENANCE_INDEXES <= _table_indexes(db_file, SCHEDULES_TABLE)


def test_sqlite_revert_of_another_table_is_unaffected():
    """Only schedules carries provenance; components must revert exactly as before."""
    db_file = os.path.join(tempfile.mkdtemp(), "components.db")
    db = SqliteDb(db_file=db_file)
    db._get_table(table_type="components", create_table_if_not_found=True)
    assert "user_id" in _table_columns(db_file, COMPONENTS_TABLE)

    asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="components"))

    assert "user_id" not in _table_columns(db_file, COMPONENTS_TABLE)


@pytest.mark.asyncio
async def test_async_sqlite_revert_drops_provenance_columns_and_indexes():
    db_file = os.path.join(tempfile.mkdtemp(), "provenance_async.db")
    db = AsyncSqliteDb(db_file=db_file)
    await db._get_table(table_type="schedules", create_table_if_not_found=True)
    assert set(SCHEDULE_PROVENANCE_COLUMNS) <= _table_columns(db_file, SCHEDULES_TABLE)
    assert PROVENANCE_INDEXES <= _table_indexes(db_file, SCHEDULES_TABLE)

    await MigrationManager(db).down(target_version="2.5.6", table_type="schedules")

    columns = _table_columns(db_file, SCHEDULES_TABLE)
    assert not columns & set(SCHEDULE_PROVENANCE_COLUMNS)
    assert not _table_indexes(db_file, SCHEDULES_TABLE) & PROVENANCE_INDEXES
    assert "user_id" not in columns

    await MigrationManager(db).up(table_type="schedules")
    assert set(SCHEDULE_PROVENANCE_COLUMNS) <= _table_columns(db_file, SCHEDULES_TABLE)
    assert PROVENANCE_INDEXES <= _table_indexes(db_file, SCHEDULES_TABLE)
