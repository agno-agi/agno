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
