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
from agno.exceptions import SchemaMismatchError


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
    assert len(other._table_cache) == 0
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
    assert ("schedules", db.schedules_table_name) not in db._table_cache

    table = db._get_table(table_type="schedule_runs", create_table_if_not_found=True)
    assert table is not None


def test_migration_invalidates_resolved_table(db):
    import asyncio

    from agno.db.migrations.manager import MigrationManager

    db._get_table(table_type="sessions", create_table_if_not_found=True)

    # Make the migration actually execute: v2 shape (legacy runs column) and a
    # rolled-back stamp. No-op steps deliberately keep the cache.
    with db.Session() as sess, sess.begin():
        sess.execute(text("ALTER TABLE agno_sessions ADD COLUMN runs JSON"))
    db._invalidate_table_cache(db.session_table_name)
    db._get_table(table_type="sessions")
    assert ("sessions", db.session_table_name) in db._table_cache
    db.upsert_schema_version(db.session_table_name, "2.5.6")

    asyncio.run(MigrationManager(db).up(table_type="sessions"))
    assert ("sessions", db.session_table_name) not in db._table_cache


def test_in_memory_sqlite_does_not_cache():
    mem = SqliteDb(db_url="sqlite:///:memory:")
    assert mem._table_cache.enabled is False
    mem._get_table(table_type="sessions", create_table_if_not_found=True)
    assert len(mem._table_cache) == 0


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
        exists = sess.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agno_memories'")).scalar()
    assert exists == 1


def test_fk_dependency_map_covers_every_schema_fk():
    """Every FK declared in the postgres schemas (the superset across adapters)
    must have its parent listed in _fk_dependencies, or first-time creation of
    the dependent table breaks after the parent is invalidated."""
    from agno.db.postgres.schemas import get_table_schema_definition

    db = SqliteDb(db_url="sqlite:///:memory:")
    table_types = [
        "sessions",
        "runs",
        "memories",
        "metrics",
        "evals",
        "knowledge",
        "versions",
        "components",
        "component_configs",
        "component_links",
        "learnings",
        "schedules",
        "schedule_runs",
        "approvals",
        "traces",
        "spans",
    ]
    for table_type in table_types:
        try:
            schema = get_table_schema_definition(
                table_type,
                traces_table_name="agno_traces",
                db_schema="ai",
                schedules_table_name="agno_schedules",
                session_table_name="agno_sessions",
            )
        except (ValueError, KeyError):
            continue
        declares_fk = bool(schema.get("__foreign_keys__")) or any(
            isinstance(cfg, dict) and "foreign_key" in cfg for cfg in schema.values()
        )
        if declares_fk:
            assert db._fk_dependencies(table_type), (
                f"{table_type} declares a foreign key but _fk_dependencies has no entry for it"
            )


def test_down_migration_invalidates_resolved_table(db):
    """Reverts change table shape too (e.g. dropping user_id); the down path
    must evict the cached resolution just like up does."""
    import asyncio

    from agno.db.migrations.manager import MigrationManager

    # A full v3 state (sessions + runs tables) so the revert actually executes
    db._get_table(table_type="sessions", create_table_if_not_found=True)
    db._get_table(table_type="runs", create_table_if_not_found=True)
    assert ("sessions", db.session_table_name) in db._table_cache

    asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="sessions"))
    assert ("sessions", db.session_table_name) not in db._table_cache


def test_same_physical_name_for_two_types_fails_loudly():
    """Two table types configured to one physical table must not silently
    alias through the cache; validation raises for the second type."""
    tmp = tempfile.mkdtemp()
    shared = SqliteDb(db_file=f"{tmp}/t.db", session_table="agno_shared", memory_table="agno_shared")
    shared._get_table(table_type="sessions", create_table_if_not_found=True)
    with pytest.raises(SchemaMismatchError, match="invalid schema"):
        shared._get_table(table_type="memories", create_table_if_not_found=True)


def test_store_rejects_stale_object_after_invalidation(db):
    """A resolver suspended across an invalidation cannot re-pin its stale
    table: the store guard checks object identity, not table name."""
    t_old = db._get_table(table_type="sessions", create_table_if_not_found=True)
    with db.Session() as sess, sess.begin():
        sess.execute(text("ALTER TABLE agno_sessions ADD COLUMN new_col TEXT"))
    db._invalidate_table_cache(db.session_table_name)
    t_new = db._get_table(table_type="sessions")
    assert "new_col" in t_new.c

    db._store_resolved_table("sessions", db.session_table_name, t_old)  # stale write-back
    assert db._get_table(table_type="sessions") is t_new


def test_fk_loop_does_not_create_unrelated_tables(db):
    """SQLite declares no component FKs; the _create_table FK-parent loop must
    not create agno_components as a side effect. (_get_table has an older,
    deliberate parent-creation branch, so call _get_or_create_table directly.)"""
    db._get_or_create_table(
        table_name=db.component_configs_table_name,
        table_type="component_configs",
        create_table_if_not_found=True,
    )
    with db.Session() as sess:
        exists = sess.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agno_components'")
        ).scalar()
    assert exists is None


def test_noop_migration_keeps_cache(db):
    """up() on an already-current schema must not evict resolutions."""
    import asyncio

    from agno.db.migrations.manager import MigrationManager

    db._get_table(table_type="sessions", create_table_if_not_found=True)
    asyncio.run(MigrationManager(db).up(table_type="sessions"))
    assert ("sessions", db.session_table_name) in db._table_cache


def test_create_all_tables_is_cheap_when_warm(db):
    """The externally-dropped-table re-check must cost one existence query per
    table, not a full re-reflection of everything."""
    db._create_all_tables()
    statements = count_queries(db.db_engine, db._create_all_tables)
    assert len(statements) <= 25, f"{len(statements)} statements on warm _create_all_tables"


def test_in_memory_sqlite_multi_thread_does_not_collide():
    """With the cache disabled, each thread re-resolves into its private
    database; shared-metadata redefinition must not raise."""
    import threading

    mem = SqliteDb(db_url="sqlite:///file:cache_test_mem?mode=memory&uri=true")
    errors = []

    def worker():
        try:
            assert mem._get_table(table_type="sessions", create_table_if_not_found=True) is not None
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[:2]


def test_async_create_from_scratch_does_not_deadlock(tmp_path):
    """Creating a table via the async adapter stamps the versions table, which
    re-enters the resolution lock; the lock must be task-reentrant.
    (Regression: AgentOS startup hung in _create_all_tables on async adapters.)"""
    import asyncio

    from agno.db.sqlite.async_sqlite import AsyncSqliteDb

    async def run():
        adb = AsyncSqliteDb(db_file=str(tmp_path / "a.db"))
        table = await asyncio.wait_for(
            adb._get_table(table_type="sessions", create_table_if_not_found=True), timeout=15
        )
        assert table is not None
        await asyncio.wait_for(adb._create_all_tables(), timeout=30)

    asyncio.run(run())


def test_async_lock_survives_sequential_event_loops(tmp_path):
    """One adapter instance across repeated asyncio.run calls: the inner lock
    is recreated per loop, so a contended acquire in the second loop must not
    raise 'bound to a different event loop'."""
    import asyncio

    from agno.db.sqlite.async_sqlite import AsyncSqliteDb

    adb = AsyncSqliteDb(db_file=str(tmp_path / "l.db"))

    async def contend():
        await asyncio.gather(
            adb._get_table(table_type="sessions", create_table_if_not_found=True),
            adb._get_table(table_type="memories", create_table_if_not_found=True),
        )

    asyncio.run(contend())
    adb._invalidate_table_cache(adb.session_table_name)
    adb._invalidate_table_cache(adb.memory_table_name)
    asyncio.run(contend())  # second loop, contended


def test_in_memory_threads_do_not_accumulate_constraints():
    """extend_existing re-runs of _create_table must not re-append constraints:
    the metrics unique constraint stays single however many threads create."""
    import threading

    from sqlalchemy import UniqueConstraint

    mem = SqliteDb(db_url="sqlite:///:memory:")

    def worker():
        mem._get_table(table_type="metrics", create_table_if_not_found=True)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    table = next(t for t in mem.metadata.tables.values() if t.name == mem.metrics_table_name)
    uqs = [c for c in table.constraints if isinstance(c, UniqueConstraint)]
    assert len(uqs) == 1, f"{len(uqs)} copies of the unique constraint"


def test_fk_parent_reregistered_when_cached_but_unregistered(db):
    """The FK loop must re-register a parent that is cached but missing from
    metadata (the invalidation half-window), not trust the cache fast path."""
    db._get_table(table_type="sessions", create_table_if_not_found=True)
    for t in list(db.metadata.tables.values()):
        if t.name == db.session_table_name:
            db.metadata.remove(t)  # half-invalidation: metadata gone, cache entry kept

    table = db._get_table(table_type="runs", create_table_if_not_found=True)
    assert table is not None


def test_create_all_recreates_table_registered_only_via_fk_side_effect(db):
    """Reflecting runs pulls sessions into metadata without caching it; after an
    external drop, _create_all_tables must still recreate sessions."""
    db._create_all_tables()

    fresh = SqliteDb(db_file=db.db_file)
    fresh._get_or_create_table(table_name=fresh.runs_table_name, table_type="runs", create_table_if_not_found=True)
    assert fresh._get_cached_table("sessions", fresh.session_table_name) is None
    assert any(t.name == fresh.session_table_name for t in fresh.metadata.tables.values())

    with fresh.Session() as sess, sess.begin():
        sess.execute(text("PRAGMA foreign_keys=OFF"))
        sess.execute(text("DROP TABLE agno_sessions"))
    fresh._create_all_tables()
    with fresh.Session() as sess:
        exists = sess.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agno_sessions'")).scalar()
    assert exists == 1


def test_absent_table_read_probe_does_not_take_resolve_lock(db):
    """get with create=False on a missing table must answer without the lock,
    so a permanently absent table cannot serialize other resolutions."""
    import threading

    db._get_table(table_type="sessions", create_table_if_not_found=True)
    acquired = db._resolve_lock.acquire()  # hold the lock from this thread
    try:
        result = {}

        def probe():
            result["runs"] = db._get_table(table_type="runs", create_table_if_not_found=False)

        t = threading.Thread(target=probe)
        t.start()
        t.join(timeout=3)
        assert not t.is_alive(), "read probe blocked on the resolution lock"
        assert result["runs"] is None
    finally:
        if acquired:
            db._resolve_lock.release()
