"""Tests for the v3.2.2 migration: user_type on the user directory, added to a table that predates it."""

import asyncio
import os
import sqlite3
import tempfile

from agno.db.migrations.manager import MigrationManager
from agno.db.sqlite import AsyncSqliteDb, SqliteDb

TABLE = "agno_authz_users"
INDEX = f"idx_{TABLE}_user_type"


def _legacy_db_file() -> str:
    """A database holding the user directory as v3.1 created it: no user_type, stamped 3.0.0."""
    db_file = os.path.join(tempfile.mkdtemp(), "legacy.db")
    conn = sqlite3.connect(db_file)
    conn.executescript(
        f"""
        CREATE TABLE {TABLE} (
            id VARCHAR NOT NULL PRIMARY KEY, email VARCHAR, name VARCHAR, disabled BOOLEAN NOT NULL,
            created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL, user_metadata TEXT
        );
        INSERT INTO {TABLE} VALUES ('a@example.com', 'a@example.com', 'A', 0, 1, 1, NULL);
        """
    )
    conn.commit()
    conn.close()
    return db_file


def _stamp(db, version: str = "3.0.0") -> None:
    db.upsert_schema_version(TABLE, version)


def _shape(db_file: str):
    conn = sqlite3.connect(db_file)
    try:
        columns = {c[1] for c in conn.execute(f"PRAGMA table_info({TABLE})").fetchall()}
        indexes = {i[1] for i in conn.execute(f"PRAGMA index_list({TABLE})").fetchall()}
        return columns, indexes
    finally:
        conn.close()


def test_an_unmigrated_table_says_to_run_the_migration():
    from agno.db.utils import MigrationRequiredError

    db = SqliteDb(db_file=_legacy_db_file())
    try:
        db.get_authz_user("a@example.com")
    except MigrationRequiredError:
        return
    raise AssertionError("an unmigrated user directory should ask for the migration")


def test_up_adds_user_type_and_its_index_and_keeps_rows():
    db_file = _legacy_db_file()
    db = SqliteDb(db_file=db_file)
    _stamp(db)
    asyncio.run(MigrationManager(db).up(table_type="authz_users"))
    columns, indexes = _shape(db_file)
    assert "user_type" in columns and INDEX in indexes
    assert db.get_latest_schema_version(TABLE) == "3.2.2"
    # The existing user is still there, with NULL read as an end user
    user = db.get_authz_user("a@example.com")
    assert user is not None and user["user_type"] is None


def test_up_is_idempotent_and_down_reverts():
    db_file = _legacy_db_file()
    db = SqliteDb(db_file=db_file)
    _stamp(db)
    manager = MigrationManager(db)
    asyncio.run(manager.up(table_type="authz_users"))
    asyncio.run(manager.up(table_type="authz_users", force=True))
    assert "user_type" in _shape(db_file)[0]
    asyncio.run(manager.down(target_version="3.0.0", table_type="authz_users"))
    columns, indexes = _shape(db_file)
    assert "user_type" not in columns and INDEX not in indexes


def test_the_directory_works_on_the_migrated_table():
    from agno.os.authz.user_directory import ORG_USER, UserDirectory, user_type_of

    db_file = _legacy_db_file()
    db = SqliteDb(db_file=db_file)
    _stamp(db)
    asyncio.run(MigrationManager(db).up(table_type="authz_users"))
    directory = UserDirectory(db=SqliteDb(db_file=db_file))
    directory.remember_org_access("a@example.com", {"org_id": "o", "os_id": "s", "role": "member"}, ["agents:run"])
    assert user_type_of(directory.get("a@example.com")) == ORG_USER


def test_async_up_adds_user_type():
    db_file = _legacy_db_file()
    _stamp(SqliteDb(db_file=db_file))
    asyncio.run(MigrationManager(AsyncSqliteDb(db_file=db_file)).up(table_type="authz_users"))
    columns, indexes = _shape(db_file)
    assert "user_type" in columns and INDEX in indexes


def test_a_missing_table_is_skipped():
    db = SqliteDb(db_file=os.path.join(tempfile.mkdtemp(), "empty.db"))
    asyncio.run(MigrationManager(db).up(table_type="authz_users"))
    conn = sqlite3.connect(db.db_file)
    try:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (TABLE,)).fetchone() is None
    finally:
        conn.close()
