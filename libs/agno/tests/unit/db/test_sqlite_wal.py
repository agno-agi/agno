"""SqliteDb must run its database in WAL journal mode.

SQLite's default DELETE journal creates, fsyncs and deletes a rollback
journal file on every commit; WAL avoids that per-commit file churn. The
adapter issues PRAGMA journal_mode=WAL on each new connection — the mode
persists in the database file, so a completely separate connection must
report it too. synchronous stays at SQLite's default (FULL) so commits
keep their durability guarantee, and databases where WAL cannot work
(e.g. in-memory) must keep operating in whatever mode SQLite falls back
to.
"""

import sqlite3

import pytest
from sqlalchemy import text

from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb


def _journal_mode_via_separate_connection(db_file: str) -> str:
    """Read the journal mode the way any other process would see it."""
    conn = sqlite3.connect(db_file)
    try:
        return conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()


def test_fresh_sqlite_db_is_in_wal_mode(tmp_path):
    db_file = str(tmp_path / "wal.db")
    db = SqliteDb(db_file=db_file, session_table="sess")

    with db.db_engine.connect():
        pass

    assert _journal_mode_via_separate_connection(db_file) == "wal"


@pytest.mark.asyncio
async def test_fresh_async_sqlite_db_is_in_wal_mode(tmp_path):
    db_file = str(tmp_path / "wal_async.db")
    db = AsyncSqliteDb(db_file=db_file, session_table="sess")

    async with db.db_engine.connect():
        pass
    await db.db_engine.dispose()

    assert _journal_mode_via_separate_connection(db_file) == "wal"


def test_wal_does_not_weaken_durability(tmp_path):
    """synchronous must stay at SQLite's default FULL (2) — WAL changes the
    journal, not how hard commits sync."""
    db = SqliteDb(db_file=str(tmp_path / "sync.db"), session_table="sess")

    with db.db_engine.connect() as conn:
        assert conn.execute(text("PRAGMA synchronous")).fetchone()[0] == 2


def test_in_memory_database_falls_back_gracefully():
    """In-memory databases cannot use WAL; the adapter must accept SQLite's
    fallback mode instead of failing the connection."""
    db = SqliteDb(db_url="sqlite:///:memory:", session_table="sess")

    with db.db_engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).fetchone()[0]

    assert mode == "memory"
