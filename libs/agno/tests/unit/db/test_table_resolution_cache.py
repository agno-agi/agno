"""Tests for the per-instance table resolution cache in the SQL adapters.

A resolved table is cached on the adapter, so steady-state operations skip the
per-call existence check and schema inspection. A missing table is never
cached: a read before the table exists returns None and a later write can
still create the table.
"""

import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import event, text

from agno.db.migrations.manager import MigrationManager
from agno.session import AgentSession

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def sqlite_db():
    from agno.db.sqlite.sqlite import SqliteDb

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = SqliteDb(db_file=path)
    yield db
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def async_sqlite_db():
    from agno.db.sqlite.async_sqlite import AsyncSqliteDb

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = AsyncSqliteDb(db_file=path)
    yield db
    try:
        os.unlink(path)
    except OSError:
        pass


RESOLUTION_MARKERS = ("sqlite_master", "table_info", "table_xinfo")


def _collect_statements(sync_engine):
    statements = []

    def on_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", on_execute)
    return statements, on_execute


def _resolution_statements(statements):
    return [s for s in statements if any(marker in s for marker in RESOLUTION_MARKERS)]


# ============================================================================
# STEADY-STATE QUERY COUNT
# ============================================================================


def test_steady_state_read_emits_no_resolution_queries(sqlite_db):
    sqlite_db._create_all_tables()
    session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
    sqlite_db.upsert_session(session)
    assert sqlite_db.get_session(session_id="s1") is not None

    statements, listener = _collect_statements(sqlite_db.db_engine)
    try:
        assert sqlite_db.get_session(session_id="s1") is not None
    finally:
        event.remove(sqlite_db.db_engine, "before_cursor_execute", listener)

    assert _resolution_statements(statements) == []
    # The data queries themselves still run.
    assert len(statements) > 0


async def test_steady_state_read_emits_no_resolution_queries_async(async_sqlite_db):
    await async_sqlite_db._create_all_tables()
    session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
    await async_sqlite_db.upsert_session(session)
    assert await async_sqlite_db.get_session(session_id="s1") is not None

    statements, listener = _collect_statements(async_sqlite_db.db_engine.sync_engine)
    try:
        assert await async_sqlite_db.get_session(session_id="s1") is not None
    finally:
        event.remove(async_sqlite_db.db_engine.sync_engine, "before_cursor_execute", listener)

    assert _resolution_statements(statements) == []
    assert len(statements) > 0


def test_steady_state_read_on_existing_tables_emits_no_resolution_queries(sqlite_db):
    from agno.db.sqlite.sqlite import SqliteDb

    sqlite_db._create_all_tables()
    session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
    sqlite_db.upsert_session(session)

    # A fresh instance over existing tables resolves through reflection.
    db2 = SqliteDb(db_file=sqlite_db.db_file)
    assert db2.get_session(session_id="s1") is not None

    statements, listener = _collect_statements(db2.db_engine)
    try:
        assert db2.get_session(session_id="s1") is not None
    finally:
        event.remove(db2.db_engine, "before_cursor_execute", listener)

    assert _resolution_statements(statements) == []
    assert len(statements) > 0


def test_repeated_resolution_returns_same_table_object(sqlite_db):
    t1 = sqlite_db._get_table(table_type="sessions", create_table_if_not_found=True)
    t2 = sqlite_db._get_table(table_type="sessions", create_table_if_not_found=False)
    assert t1 is not None
    assert t1 is t2
    assert sqlite_db.session_table_name in sqlite_db._resolved_tables


# ============================================================================
# A MISSING TABLE IS NEVER CACHED
# ============================================================================


def test_missing_table_is_not_cached(sqlite_db):
    # Reads before the table exists return None.
    assert sqlite_db._get_table(table_type="sessions", create_table_if_not_found=False) is None
    assert sqlite_db._get_table(table_type="sessions", create_table_if_not_found=False) is None
    assert sqlite_db.session_table_name not in sqlite_db._resolved_tables

    # A later write can still create the table.
    session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
    sqlite_db.upsert_session(session)
    assert sqlite_db.get_session(session_id="s1") is not None


async def test_missing_table_is_not_cached_async(async_sqlite_db):
    assert await async_sqlite_db._get_table(table_type="sessions", create_table_if_not_found=False) is None
    assert await async_sqlite_db._get_table(table_type="sessions", create_table_if_not_found=False) is None
    assert async_sqlite_db.session_table_name not in async_sqlite_db._resolved_tables

    session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
    await async_sqlite_db.upsert_session(session)
    assert await async_sqlite_db.get_session(session_id="s1") is not None


# ============================================================================
# INVALIDATION
# ============================================================================


def test_invalidation_allows_recreate_after_external_drop(sqlite_db):
    table = sqlite_db._get_table(table_type="sessions", create_table_if_not_found=True)
    assert table is not None

    with sqlite_db.Session() as sess, sess.begin():
        sess.execute(text(f"DROP TABLE {sqlite_db.session_table_name}"))

    sqlite_db._invalidate_resolved_table(sqlite_db.session_table_name)
    assert sqlite_db.session_table_name not in sqlite_db._resolved_tables

    # Recreation only works when the invalidation also unregistered the
    # table from the adapter's metadata.
    recreated = sqlite_db._get_table(table_type="sessions", create_table_if_not_found=True)
    assert recreated is not None

    session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
    sqlite_db.upsert_session(session)
    assert sqlite_db.get_session(session_id="s1") is not None


async def test_invalidation_allows_recreate_after_external_drop_async(async_sqlite_db):
    table = await async_sqlite_db._get_table(table_type="sessions", create_table_if_not_found=True)
    assert table is not None

    async with async_sqlite_db.async_session_factory() as sess, sess.begin():
        await sess.execute(text(f"DROP TABLE {async_sqlite_db.session_table_name}"))

    async_sqlite_db._invalidate_resolved_table(async_sqlite_db.session_table_name)

    recreated = await async_sqlite_db._get_table(table_type="sessions", create_table_if_not_found=True)
    assert recreated is not None


# ============================================================================
# MIGRATIONS INVALIDATE THE CACHE
# ============================================================================


async def test_up_migration_invalidates_resolved_tables(sqlite_db):
    session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
    sqlite_db.upsert_session(session)
    assert sqlite_db.session_table_name in sqlite_db._resolved_tables

    manager = MigrationManager(sqlite_db)
    with (
        patch.object(manager, "_up_migration", new=AsyncMock(return_value=True)),
        patch.object(sqlite_db, "get_latest_schema_version", return_value="2.0.0"),
        patch.object(sqlite_db, "upsert_schema_version"),
    ):
        await manager.up(table_type="sessions")

    assert sqlite_db.session_table_name not in sqlite_db._resolved_tables


async def test_failed_migration_still_invalidates_resolved_tables(sqlite_db):
    session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
    sqlite_db.upsert_session(session)
    assert sqlite_db.session_table_name in sqlite_db._resolved_tables

    manager = MigrationManager(sqlite_db)
    with (
        patch.object(manager, "_up_migration", new=AsyncMock(side_effect=RuntimeError("boom"))),
        patch.object(sqlite_db, "get_latest_schema_version", return_value="2.0.0"),
        patch.object(sqlite_db, "upsert_schema_version"),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await manager.up(table_type="sessions")

    assert sqlite_db.session_table_name not in sqlite_db._resolved_tables


async def test_down_migration_invalidates_resolved_tables(sqlite_db):
    session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
    sqlite_db.upsert_session(session)
    assert sqlite_db.session_table_name in sqlite_db._resolved_tables

    manager = MigrationManager(sqlite_db)
    with (
        patch.object(manager, "_down_migration", new=AsyncMock(return_value=True)),
        patch.object(sqlite_db, "get_latest_schema_version", return_value="3.0.0"),
        patch.object(sqlite_db, "upsert_schema_version"),
    ):
        await manager.down(target_version="2.5.6", table_type="sessions")

    assert sqlite_db.session_table_name not in sqlite_db._resolved_tables


async def test_dependent_table_creation_works_after_migration_invalidated_parent(sqlite_db):
    """Invalidation removes the parent from metadata; creating a dependent
    table afterwards must re-register the parent, not raise
    NoReferencedTableError."""
    schedules = sqlite_db._get_table(table_type="schedules", create_table_if_not_found=True)
    assert schedules is not None

    manager = MigrationManager(sqlite_db)
    with (
        patch.object(manager, "_up_migration", new=AsyncMock(return_value=True)),
        patch.object(sqlite_db, "get_latest_schema_version", return_value="2.0.0"),
        patch.object(sqlite_db, "upsert_schema_version"),
    ):
        await manager.up(table_type="schedules")
    assert sqlite_db.schedules_table_name not in sqlite_db._resolved_tables

    schedule_runs = sqlite_db._get_table(table_type="schedule_runs", create_table_if_not_found=True)
    assert schedule_runs is not None


def test_create_all_tables_recreates_externally_dropped_table(sqlite_db):
    sqlite_db._create_all_tables()
    session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
    sqlite_db.upsert_session(session)

    with sqlite_db.Session() as sess, sess.begin():
        sess.execute(text(f"DROP TABLE {sqlite_db.session_table_name}"))

    sqlite_db._create_all_tables()
    assert sqlite_db.get_session(session_id="s1") is None
    sqlite_db.upsert_session(session)
    assert sqlite_db.get_session(session_id="s1") is not None


def test_in_memory_sqlite_does_not_cache_across_threads():
    """In-memory SQLite keeps one private database per thread, so resolved
    tables must not be cached: a worker thread would query a table that only
    exists in the creating thread's database."""
    import threading

    from agno.db.sqlite.sqlite import SqliteDb

    db = SqliteDb(db_url="sqlite:///:memory:")
    assert db._cache_resolved_tables is False

    session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
    db.upsert_session(session)
    assert db._resolved_tables == {}

    errors = []

    def read_from_other_thread():
        try:
            # This thread's private database has no tables; the read must
            # degrade to None, not fail on a cached Table.
            assert db.get_session(session_id="s1") is None
        except Exception as e:
            errors.append(e)

    t = threading.Thread(target=read_from_other_thread)
    t.start()
    t.join()
    assert errors == []


def test_file_backed_sqlite_keeps_caching_enabled(sqlite_db):
    assert sqlite_db._cache_resolved_tables is True


# ============================================================================
# RUNTIME DDL INVALIDATES THE CACHE
# ============================================================================


def test_cleanup_legacy_runs_column_invalidates_sessions_table(sqlite_db):
    session = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
    sqlite_db.upsert_session(session)

    # Simulate a legacy database: the sessions table has a runs column and the
    # adapter resolved the table while the column existed.
    with sqlite_db.Session() as sess, sess.begin():
        sess.execute(text(f"ALTER TABLE {sqlite_db.session_table_name} ADD COLUMN runs TEXT"))
    sqlite_db._invalidate_resolved_table(sqlite_db.session_table_name)
    table = sqlite_db._get_table(table_type="sessions", create_table_if_not_found=False)
    assert table is not None
    assert "runs" in table.c

    assert sqlite_db.cleanup_legacy_runs_column(force=True) is True
    assert sqlite_db.session_table_name not in sqlite_db._resolved_tables

    # Reads keep working after the drop: the re-resolved table no longer
    # carries the dropped column.
    fetched = sqlite_db.get_session(session_id="s1")
    assert fetched is not None
    refreshed = sqlite_db._get_table(table_type="sessions", create_table_if_not_found=False)
    assert refreshed is not None
    assert "runs" not in refreshed.c
