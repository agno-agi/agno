"""Tests for the v3.0.0 evals user_id migration: column add, idempotency, revert."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile

import pytest

from agno.db.migrations.manager import MigrationManager
from agno.db.schemas.evals import EvalRunRecord, EvalType
from agno.db.sqlite import AsyncSqliteDb, SqliteDb

EVAL_TABLE = "agno_eval_runs"
EVAL_INDEX = f"idx_{EVAL_TABLE}_user_id"


def _new_db():
    db_file = os.path.join(tempfile.mkdtemp(), "test.db")
    db = SqliteDb(db_file=db_file)
    db._get_table(table_type="evals", create_table_if_not_found=True)
    return db, db_file


def _make_record(run_id: str) -> EvalRunRecord:
    return EvalRunRecord(
        run_id=run_id,
        eval_type=EvalType.ACCURACY,
        eval_data={"score": 8},
        eval_input={"input": "2+2"},
        name="baseline",
        agent_id="agent-1",
    )


def _columns(db_file: str) -> set[str]:
    conn = sqlite3.connect(db_file)
    try:
        return {c[1] for c in conn.execute(f"PRAGMA table_info({EVAL_TABLE})").fetchall()}
    finally:
        conn.close()


def _column_type(db_file: str, column: str) -> str | None:
    conn = sqlite3.connect(db_file)
    try:
        for col in conn.execute(f"PRAGMA table_info({EVAL_TABLE})").fetchall():
            if col[1] == column:
                return col[2]
        return None
    finally:
        conn.close()


def _indexes(db_file: str) -> set[str]:
    conn = sqlite3.connect(db_file)
    try:
        return {i[1] for i in conn.execute(f"PRAGMA index_list({EVAL_TABLE})").fetchall()}
    finally:
        conn.close()


def _make_legacy(db_file: str) -> None:
    """Strip user_id and rewind the version row, mimicking a pre-v3 eval table."""
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(f"DROP INDEX IF EXISTS {EVAL_INDEX}")
        conn.execute(f"ALTER TABLE {EVAL_TABLE} DROP COLUMN user_id")
        conn.execute("UPDATE agno_schema_versions SET version='2.5.6' WHERE table_name=?", (EVAL_TABLE,))
        conn.commit()
    finally:
        conn.close()


def _insert_legacy_run(db_file: str, run_id: str) -> None:
    """Insert a row the way a pre-v3 install would: no user_id column to fill."""
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            f"INSERT INTO {EVAL_TABLE} (run_id, eval_type, eval_data, eval_input, name, created_at) "
            "VALUES (?, 'accuracy', '{}', '{}', 'legacy', 1700000000)",
            (run_id,),
        )
        conn.commit()
    finally:
        conn.close()


def test_up_adds_user_id_column_and_index():
    db, db_file = _new_db()
    _make_legacy(db_file)
    assert "user_id" not in _columns(db_file)
    assert EVAL_INDEX not in _indexes(db_file)

    asyncio.run(MigrationManager(db).up(table_type="evals"))

    assert "user_id" in _columns(db_file)
    assert EVAL_INDEX in _indexes(db_file)
    assert db.get_latest_schema_version(EVAL_TABLE) == "3.0.0"


def test_migrated_column_type_matches_fresh_schema():
    """A migrated table and a freshly created one must declare the same type."""
    fresh, fresh_file = _new_db()
    fresh_type = _column_type(fresh_file, "user_id")

    db, db_file = _new_db()
    _make_legacy(db_file)
    asyncio.run(MigrationManager(db).up(table_type="evals"))

    assert _column_type(db_file, "user_id") == fresh_type


def test_up_is_idempotent():
    db, db_file = _new_db()
    _make_legacy(db_file)

    asyncio.run(MigrationManager(db).up(table_type="evals"))
    # force=True runs the migration again even though the version is already current
    asyncio.run(MigrationManager(db).up(table_type="evals", force=True))

    assert "user_id" in _columns(db_file)
    assert len([i for i in _indexes(db_file) if i == EVAL_INDEX]) == 1


def test_legacy_rows_survive_with_null_user_id():
    db, db_file = _new_db()
    _make_legacy(db_file)
    _insert_legacy_run(db_file, "legacy-1")

    asyncio.run(MigrationManager(db).up(table_type="evals"))

    run = db.get_eval_run("legacy-1", deserialize=False)
    assert run is not None
    assert run["user_id"] is None
    # An unowned run stays global: visible unscoped, invisible to a scoped caller
    assert db.get_eval_run("legacy-1", deserialize=False, user_id="alice") is None


def test_down_drops_column_and_index_preserving_rows():
    db, db_file = _new_db()
    _make_legacy(db_file)
    _insert_legacy_run(db_file, "legacy-1")
    asyncio.run(MigrationManager(db).up(table_type="evals"))
    db.create_eval_run(_make_record("run-2"))

    asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="evals"))

    assert "user_id" not in _columns(db_file)
    assert EVAL_INDEX not in _indexes(db_file)
    assert db.get_latest_schema_version(EVAL_TABLE) == "2.5.6"

    conn = sqlite3.connect(db_file)
    try:
        assert conn.execute(f"SELECT COUNT(*) FROM {EVAL_TABLE}").fetchone()[0] == 2
    finally:
        conn.close()


def test_up_after_down_restores_the_column():
    db, db_file = _new_db()
    _make_legacy(db_file)
    asyncio.run(MigrationManager(db).up(table_type="evals"))
    asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="evals"))
    asyncio.run(MigrationManager(db).up(table_type="evals"))

    assert "user_id" in _columns(db_file)
    assert EVAL_INDEX in _indexes(db_file)


def test_other_table_types_are_untouched():
    """A table type outside USER_ID_TABLE_TYPES gets no user_id work."""
    from agno.db.migrations.versions import v3_0_0

    db, _ = _new_db()
    for table_type in ("memories", "metrics", "culture", "approvals"):
        assert v3_0_0.up(db, table_type, EVAL_TABLE) is False
        assert v3_0_0.down(db, table_type, EVAL_TABLE) is False


def test_adding_a_table_type_needs_no_backend_changes(monkeypatch):
    """Isolating another table is a one-line change to USER_ID_TABLE_TYPES.

    Uses 'memories' as the stand-in: it has a user_id column in every adapter
    schema, so it exercises the same path a future table type would take.
    """
    from agno.db.migrations.versions import v3_0_0

    db_file = os.path.join(tempfile.mkdtemp(), "test.db")
    db = SqliteDb(db_file=db_file)
    db._get_table(table_type="memories", create_table_if_not_found=True)

    conn = sqlite3.connect(db_file)
    try:
        conn.execute("DROP INDEX IF EXISTS idx_agno_memories_user_id")
        conn.execute("ALTER TABLE agno_memories DROP COLUMN user_id")
        conn.commit()
        cols = {c[1] for c in conn.execute("PRAGMA table_info(agno_memories)").fetchall()}
        assert "user_id" not in cols
    finally:
        conn.close()

    # Before: memories is not isolated, so the migration leaves it alone
    assert v3_0_0.up(db, "memories", "agno_memories") is False

    monkeypatch.setattr(v3_0_0, "USER_ID_TABLE_TYPES", ("evals", "memories"))

    # After: the same backend functions add the column, with no other edit
    assert v3_0_0.up(db, "memories", "agno_memories") is True

    conn = sqlite3.connect(db_file)
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(agno_memories)").fetchall()}
        idxs = {i[1] for i in conn.execute("PRAGMA index_list(agno_memories)").fetchall()}
        assert "user_id" in cols
        assert "idx_agno_memories_user_id" in idxs
    finally:
        conn.close()

    assert v3_0_0.down(db, "memories", "agno_memories") is True


def test_table_type_the_backend_does_not_have_is_skipped(monkeypatch):
    """A table type only some adapters support must be skipped, not raise.

    The SQL adapters report an unknown table as version 2.0.0 rather than None, so
    MigrationManager runs the migration anyway and it has to bow out on its own.
    """
    from agno.db.migrations.versions import v3_0_0

    db, _ = _new_db()
    monkeypatch.setattr(v3_0_0, "USER_ID_TABLE_TYPES", ("evals", "not_a_real_table"))

    assert v3_0_0.up(db, "not_a_real_table", "agno_not_a_real_table") is False
    assert v3_0_0.down(db, "not_a_real_table", "agno_not_a_real_table") is False


@pytest.mark.asyncio
async def test_async_adapters_can_migrate_a_components_table():
    """MigrationManager reads the table name off the db, so the async adapters need it
    even though they cannot read or write components themselves."""
    db = AsyncSqliteDb(db_file=os.path.join(tempfile.mkdtemp(), "test_components.db"))
    assert db.components_table_name == "agno_components"

    await MigrationManager(db).up()


def test_document_backend_is_a_noop():
    """Document backends carry user_id without a schema change."""
    from agno.db.json import JsonDb
    from agno.db.migrations.versions import v3_0_0

    db = JsonDb(db_path=tempfile.mkdtemp())
    assert v3_0_0.up(db, "evals", EVAL_TABLE) is False
    assert v3_0_0.down(db, "evals", EVAL_TABLE) is False

    db.create_eval_run(_make_record("run-1"))
    db.update_eval_run_user_id("run-1", "alice")
    assert db.get_eval_run("run-1", user_id="alice") is not None
    assert db.get_eval_run("run-1", user_id="bob") is None


@pytest.mark.asyncio
async def test_async_up_and_down():
    db_file = os.path.join(tempfile.mkdtemp(), "test_async.db")
    db = AsyncSqliteDb(db_file=db_file)
    await db._get_table(table_type="evals", create_table_if_not_found=True)
    _make_legacy(db_file)

    await MigrationManager(db).up(table_type="evals")
    assert "user_id" in _columns(db_file)
    assert EVAL_INDEX in _indexes(db_file)

    await db.create_eval_run(_make_record("alice-run"))
    await db.update_eval_run_user_id("alice-run", "alice")
    assert await db.get_eval_run("alice-run", user_id="alice") is not None
    assert await db.get_eval_run("alice-run", user_id="bob") is None

    await MigrationManager(db).down(target_version="2.5.6", table_type="evals")
    assert "user_id" not in _columns(db_file)
    assert EVAL_INDEX not in _indexes(db_file)


def test_revert_skips_on_old_sqlite(monkeypatch):
    """SQLite added DROP COLUMN in 3.35.0, so an older one must be left untouched."""
    db, db_file = _new_db()
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 34, 0))

    asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="evals"))

    assert "user_id" in _columns(db_file)
    assert EVAL_INDEX in _indexes(db_file)


def test_failed_revert_leaves_the_index_in_place():
    """A revert that cannot drop the column must not leave the column unindexed.

    SQLite commits DDL outside the session transaction, so the index drop sticks
    even when the column drop fails.
    """
    db, db_file = _new_db()

    conn = sqlite3.connect(db_file)
    try:
        # a view over user_id makes DROP COLUMN fail
        conn.execute(f"CREATE VIEW v_owner AS SELECT user_id FROM {EVAL_TABLE}")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(Exception):
        asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="evals"))

    assert "user_id" in _columns(db_file)
    assert EVAL_INDEX in _indexes(db_file), "the index must be restored when the column drop fails"


# ---------------------------------------------------------------------------
# schedules / schedule_runs / knowledge
# ---------------------------------------------------------------------------

SCHEDULES_TABLE = "agno_schedules"
SCHEDULE_RUNS_TABLE = "agno_schedule_runs"
KNOWLEDGE_TABLE = "agno_knowledge"
SCHEDULES_COMPOSITE_INDEX = f"idx_{SCHEDULES_TABLE}_user_id_enabled_next_run_at"


def _new_db_with(table_types: list[str]):
    db_file = os.path.join(tempfile.mkdtemp(), "test.db")
    db = SqliteDb(db_file=db_file)
    for table_type in table_types:
        db._get_table(table_type=table_type, create_table_if_not_found=True)
    return db, db_file


def _table_columns(db_file: str, table: str) -> set[str]:
    conn = sqlite3.connect(db_file)
    try:
        return {c[1] for c in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        conn.close()


def _table_indexes(db_file: str, table: str) -> set[str]:
    conn = sqlite3.connect(db_file)
    try:
        return {i[1] for i in conn.execute(f"PRAGMA index_list({table})").fetchall()}
    finally:
        conn.close()


def _strip_user_id(db_file: str, table: str, indexes: list[str]) -> None:
    """Mimic a pre-v3 table: drop the user_id indexes and column, rewind the version."""
    conn = sqlite3.connect(db_file)
    try:
        for index in indexes:
            conn.execute(f"DROP INDEX IF EXISTS {index}")
        conn.execute(f"ALTER TABLE {table} DROP COLUMN user_id")
        conn.execute("UPDATE agno_schema_versions SET version='2.5.6' WHERE table_name=?", (table,))
        conn.commit()
    finally:
        conn.close()


def test_schedules_migration_restores_column_and_composite_index():
    """Both schedule tables gain user_id, and schedules gets its composite index back."""
    db, db_file = _new_db_with(["schedules", "schedule_runs"])
    _strip_user_id(db_file, SCHEDULES_TABLE, [f"idx_{SCHEDULES_TABLE}_user_id", SCHEDULES_COMPOSITE_INDEX])
    _strip_user_id(db_file, SCHEDULE_RUNS_TABLE, [f"idx_{SCHEDULE_RUNS_TABLE}_user_id"])
    assert "user_id" not in _table_columns(db_file, SCHEDULES_TABLE)
    assert "user_id" not in _table_columns(db_file, SCHEDULE_RUNS_TABLE)

    asyncio.run(MigrationManager(db).up(table_type="schedules"))
    asyncio.run(MigrationManager(db).up(table_type="schedule_runs"))

    assert "user_id" in _table_columns(db_file, SCHEDULES_TABLE)
    assert f"idx_{SCHEDULES_TABLE}_user_id" in _table_indexes(db_file, SCHEDULES_TABLE)
    # A migrated table matches a fresh one: the (user_id, enabled, next_run_at)
    # composite the listing path relies on is created too.
    assert SCHEDULES_COMPOSITE_INDEX in _table_indexes(db_file, SCHEDULES_TABLE)
    assert "user_id" in _table_columns(db_file, SCHEDULE_RUNS_TABLE)
    assert f"idx_{SCHEDULE_RUNS_TABLE}_user_id" in _table_indexes(db_file, SCHEDULE_RUNS_TABLE)
    assert db.get_latest_schema_version(SCHEDULES_TABLE) == "3.0.0"
    assert db.get_latest_schema_version(SCHEDULE_RUNS_TABLE) == "3.0.0"


def test_schedules_revert_drops_composite_before_column():
    """SQLite refuses DROP COLUMN while a multi-column index covers it — the
    revert must drop the composite first or fail."""
    db, db_file = _new_db_with(["schedules"])
    assert SCHEDULES_COMPOSITE_INDEX in _table_indexes(db_file, SCHEDULES_TABLE)

    asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="schedules"))

    assert "user_id" not in _table_columns(db_file, SCHEDULES_TABLE)
    assert SCHEDULES_COMPOSITE_INDEX not in _table_indexes(db_file, SCHEDULES_TABLE)
    assert f"idx_{SCHEDULES_TABLE}_user_id" not in _table_indexes(db_file, SCHEDULES_TABLE)


def test_schedules_up_after_down_restores_everything():
    db, db_file = _new_db_with(["schedules"])
    asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="schedules"))
    assert "user_id" not in _table_columns(db_file, SCHEDULES_TABLE)

    asyncio.run(MigrationManager(db).up(table_type="schedules"))

    assert "user_id" in _table_columns(db_file, SCHEDULES_TABLE)
    assert SCHEDULES_COMPOSITE_INDEX in _table_indexes(db_file, SCHEDULES_TABLE)


def test_knowledge_migration_adds_user_id():
    db, db_file = _new_db_with(["knowledge"])
    knowledge_composite = f"idx_{KNOWLEDGE_TABLE}_user_id_linked_to"
    _strip_user_id(db_file, KNOWLEDGE_TABLE, [f"idx_{KNOWLEDGE_TABLE}_user_id", knowledge_composite])
    assert "user_id" not in _table_columns(db_file, KNOWLEDGE_TABLE)

    asyncio.run(MigrationManager(db).up(table_type="knowledge"))

    assert "user_id" in _table_columns(db_file, KNOWLEDGE_TABLE)
    assert f"idx_{KNOWLEDGE_TABLE}_user_id" in _table_indexes(db_file, KNOWLEDGE_TABLE)
    # linked_to still exists on this table, so the (user_id, linked_to)
    # composite comes back too.
    assert knowledge_composite in _table_indexes(db_file, KNOWLEDGE_TABLE)
    assert db.get_latest_schema_version(KNOWLEDGE_TABLE) == "3.0.0"


def test_schedules_migration_is_idempotent():
    db, db_file = _new_db_with(["schedules"])
    _strip_user_id(db_file, SCHEDULES_TABLE, [f"idx_{SCHEDULES_TABLE}_user_id", SCHEDULES_COMPOSITE_INDEX])

    asyncio.run(MigrationManager(db).up(table_type="schedules"))
    before_cols = _table_columns(db_file, SCHEDULES_TABLE)
    before_idx = _table_indexes(db_file, SCHEDULES_TABLE)
    asyncio.run(MigrationManager(db).up(table_type="schedules", force=True))

    assert _table_columns(db_file, SCHEDULES_TABLE) == before_cols
    assert _table_indexes(db_file, SCHEDULES_TABLE) == before_idx
