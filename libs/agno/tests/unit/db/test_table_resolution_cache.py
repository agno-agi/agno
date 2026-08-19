"""Table resolution caching in the SQLAlchemy adapters.

_get_or_create_table used to re-run an existence check and schema validation
on every call, costing round-trips per query. Resolved tables are now cached
per instance. Rules under test:

- second resolution of a table issues zero SQL
- a missing table is never cached, so a table created later (including by
  another process) is still picked up
- in-process schema changes (cleanup_legacy_runs_column, migrations)
  invalidate the cache
"""

import tempfile

import pytest
from sqlalchemy import event, text

from agno.db.sqlite import SqliteDb


@pytest.fixture
def db():
    tmp = tempfile.mkdtemp()
    return SqliteDb(db_file=f"{tmp}/cache.db")


def count_queries(engine, fn):
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return statements


def test_second_resolution_issues_no_queries(db):
    table = db._get_table(table_type="sessions", create_table_if_not_found=True)
    assert table is not None

    statements = count_queries(db.db_engine, lambda: db._get_table(table_type="sessions"))
    assert statements == []


def test_missing_table_is_not_cached(db):
    assert db._get_table(table_type="sessions", create_table_if_not_found=False) is None
    # Simulate another process creating the table between calls
    other = SqliteDb(db_file=db.db_file)
    assert other._get_table(table_type="sessions", create_table_if_not_found=True) is not None

    table = db._get_table(table_type="sessions", create_table_if_not_found=False)
    assert table is not None


def test_cleanup_invalidates_cached_table(db):
    table = db._get_table(table_type="sessions", create_table_if_not_found=True)
    assert "runs" not in table.c

    # Recreate the v2 shape: a legacy runs column on the sessions table
    with db.Session() as sess, sess.begin():
        sess.execute(text(f"ALTER TABLE {db.session_table_name} ADD COLUMN runs JSON"))
    db._invalidate_table_cache(db.session_table_name)
    table = db._get_table(table_type="sessions")
    assert "runs" in table.c

    assert db.cleanup_legacy_runs_column(force=True) is True
    table = db._get_table(table_type="sessions")
    assert "runs" not in table.c


def test_separate_instances_have_separate_caches(db):
    db._get_table(table_type="sessions", create_table_if_not_found=True)
    other = SqliteDb(db_file=db.db_file)
    assert other._table_cache == {}
    assert other._get_table(table_type="sessions") is not None


def test_dependent_table_creation_after_migration_invalidated_parent(db):
    """A migration invalidating an FK parent must not break first-time creation
    of a dependent table (schedule_runs declares an FK to schedules)."""
    import asyncio

    from agno.db.migrations.manager import MigrationManager

    # v2-shaped schedules table: the full current schema minus user_id, so the
    # v3 migration executes (ALTER ADD user_id) and invalidates the table
    with db.Session() as sess, sess.begin():
        sess.execute(
            text(
                "CREATE TABLE agno_schedules ("
                "id TEXT PRIMARY KEY, name TEXT, description TEXT, method TEXT, "
                "endpoint TEXT, payload TEXT, cron_expr TEXT, timezone TEXT, "
                "timeout_seconds INTEGER, max_retries INTEGER, retry_delay_seconds INTEGER, "
                "enabled BOOLEAN, next_run_at INTEGER, locked_by TEXT, locked_at INTEGER, "
                "created_at INTEGER, updated_at INTEGER)"
            )
        )
    asyncio.run(MigrationManager(db).up(table_type="schedules"))
    assert db.schedules_table_name not in db._table_cache

    table = db._get_table(table_type="schedule_runs", create_table_if_not_found=True)
    assert table is not None


def test_migration_invalidates_resolved_table(db):
    import asyncio

    from agno.db.migrations.manager import MigrationManager

    db._get_table(table_type="sessions", create_table_if_not_found=True)
    assert db.session_table_name in db._table_cache

    # Created tables are stamped at the latest version; roll the stamp back so
    # the manager actually walks a migration step
    db.upsert_schema_version(db.session_table_name, "2.5.6")
    asyncio.run(MigrationManager(db).up(table_type="sessions"))
    assert db.session_table_name not in db._table_cache


def test_in_memory_sqlite_does_not_cache():
    mem = SqliteDb(db_url="sqlite:///:memory:")
    assert mem._cache_tables is False
    mem._get_table(table_type="sessions", create_table_if_not_found=True)
    assert mem._table_cache == {}


def test_external_drop_then_recreate_rebuilds_table_and_indexes(db):
    """Invalidate + recreate after an external DROP must rebuild the table,
    its named indexes included, without 'already defined' or duplicate-index
    errors from stale metadata."""
    db._get_table(table_type="sessions", create_table_if_not_found=True)

    with db.Session() as sess, sess.begin():
        sess.execute(text("DROP TABLE agno_sessions"))

    db._invalidate_table_cache(db.session_table_name)
    table = db._get_table(table_type="sessions", create_table_if_not_found=True)
    assert table is not None

    with db.Session() as sess:
        indexes = sess.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='agno_sessions'")
        ).fetchall()
    assert any("idx_" in row[0] for row in indexes)


def test_create_all_tables_recreates_externally_dropped_table(db):
    db._create_all_tables()
    with db.Session() as sess, sess.begin():
        sess.execute(text("DROP TABLE agno_memories"))

    db._create_all_tables()
    with db.Session() as sess:
        exists = sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agno_memories'")
        ).scalar()
    assert exists == 1
