"""Tests for the v3.0.0 user_id migration: column add, idempotency, revert."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import Column, Index, MetaData, Table, UniqueConstraint
from sqlalchemy.schema import CreateIndex, CreateTable

from agno.db.migrations.manager import MigrationManager
from agno.db.migrations.versions.v3_0_0 import SCHEDULE_PROVENANCE_COLUMNS
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
    from agno.db.migrations.versions import v3_0_0

    db, db_file = _new_db()
    _make_legacy(db_file)

    asyncio.run(MigrationManager(db).up(table_type="evals"))
    # the manager stops at the stamp, so the migration is called directly to run it twice
    v3_0_0.up(db, "evals", EVAL_TABLE)

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
    for table_type in ("memories", "approvals"):
        assert v3_0_0.up(db, table_type, EVAL_TABLE) is False
        assert v3_0_0.down(db, table_type, EVAL_TABLE) is False


def test_adding_a_table_type_needs_no_backend_changes(monkeypatch):
    """Isolating another table is a change to USER_ID_TABLE_TYPES only — 'memories' stands in for a future one."""
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

    # After: the same backend functions add the column
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
    """A table type only some adapters support must be skipped, not raise: the SQL adapters report an
    unknown table as version 2.0.0, so MigrationManager runs the migration anyway."""
    from agno.db.migrations.versions import v3_0_0

    db, _ = _new_db()
    monkeypatch.setattr(v3_0_0, "USER_ID_TABLE_TYPES", ("evals", "not_a_real_table"))

    assert v3_0_0.up(db, "not_a_real_table", "agno_not_a_real_table") is False
    assert v3_0_0.down(db, "not_a_real_table", "agno_not_a_real_table") is False


@pytest.mark.asyncio
async def test_async_adapters_can_migrate_a_components_table():
    """MigrationManager reads the table name off the db, so the async adapters need one for components too."""
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
    """A revert that cannot drop the column must not leave it unindexed: SQLite commits DDL outside the
    session transaction, so the index drop sticks even when the column drop fails."""
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
    _strip_user_id(
        db_file,
        SCHEDULES_TABLE,
        [
            f"idx_{SCHEDULES_TABLE}_user_id",
            SCHEDULES_COMPOSITE_INDEX,
            # v3-only unique name backstops also cover user_id
            f"{SCHEDULES_TABLE}_uq_user_name",
            f"{SCHEDULES_TABLE}_uq_unowned_name",
        ],
    )
    _strip_user_id(db_file, SCHEDULE_RUNS_TABLE, [f"idx_{SCHEDULE_RUNS_TABLE}_user_id"])
    assert "user_id" not in _table_columns(db_file, SCHEDULES_TABLE)
    assert "user_id" not in _table_columns(db_file, SCHEDULE_RUNS_TABLE)

    asyncio.run(MigrationManager(db).up(table_type="schedules"))
    asyncio.run(MigrationManager(db).up(table_type="schedule_runs"))

    assert "user_id" in _table_columns(db_file, SCHEDULES_TABLE)
    assert f"idx_{SCHEDULES_TABLE}_user_id" in _table_indexes(db_file, SCHEDULES_TABLE)
    # The (user_id, enabled, next_run_at) composite the listing path uses comes back too
    assert SCHEDULES_COMPOSITE_INDEX in _table_indexes(db_file, SCHEDULES_TABLE)
    assert "user_id" in _table_columns(db_file, SCHEDULE_RUNS_TABLE)
    assert f"idx_{SCHEDULE_RUNS_TABLE}_user_id" in _table_indexes(db_file, SCHEDULE_RUNS_TABLE)
    assert db.get_latest_schema_version(SCHEDULES_TABLE) == "3.0.0"
    assert db.get_latest_schema_version(SCHEDULE_RUNS_TABLE) == "3.0.0"


def test_schedules_revert_drops_composite_before_column():
    """SQLite refuses DROP COLUMN while a multi-column index covers it, so the revert drops the composite first."""
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
    # linked_to still exists on this table, so the (user_id, linked_to) composite comes back too
    assert knowledge_composite in _table_indexes(db_file, KNOWLEDGE_TABLE)
    assert db.get_latest_schema_version(KNOWLEDGE_TABLE) == "3.0.0"


def test_schedules_migration_is_idempotent():
    from agno.db.migrations.versions import v3_0_0

    db, db_file = _new_db_with(["schedules"])
    _strip_user_id(
        db_file,
        SCHEDULES_TABLE,
        [
            f"idx_{SCHEDULES_TABLE}_user_id",
            SCHEDULES_COMPOSITE_INDEX,
            # v3-only unique name backstops also cover user_id
            f"{SCHEDULES_TABLE}_uq_user_name",
            f"{SCHEDULES_TABLE}_uq_unowned_name",
        ],
    )

    asyncio.run(MigrationManager(db).up(table_type="schedules"))
    before_cols = _table_columns(db_file, SCHEDULES_TABLE)
    before_idx = _table_indexes(db_file, SCHEDULES_TABLE)
    v3_0_0.up(db, "schedules", SCHEDULES_TABLE)

    assert _table_columns(db_file, SCHEDULES_TABLE) == before_cols
    assert _table_indexes(db_file, SCHEDULES_TABLE) == before_idx


def _strip_schedules_to_pre_v3(db_file: str) -> None:
    """Mimic a 2.5.6 schedules table: no user_id, no provenance columns, none of their indexes."""
    conn = sqlite3.connect(db_file)
    try:
        for index in [
            f"idx_{SCHEDULES_TABLE}_user_id",
            SCHEDULES_COMPOSITE_INDEX,
            # v3-only unique name backstops also cover user_id
            f"{SCHEDULES_TABLE}_uq_user_name",
            f"{SCHEDULES_TABLE}_uq_unowned_name",
            f"idx_{SCHEDULES_TABLE}_managed_by",
            f"idx_{SCHEDULES_TABLE}_target_id",
        ]:
            conn.execute(f"DROP INDEX IF EXISTS {index}")
        for column in ("user_id", *SCHEDULE_PROVENANCE_COLUMNS):
            conn.execute(f"ALTER TABLE {SCHEDULES_TABLE} DROP COLUMN {column}")
        conn.execute("UPDATE agno_schema_versions SET version='2.5.6' WHERE table_name=?", (SCHEDULES_TABLE,))
        conn.commit()
    finally:
        conn.close()


def _schedule_row(name: str) -> dict:
    return {
        "id": f"sched-{name}",
        "name": name,
        "cron_expr": "0 9 * * *",
        "endpoint": "/agents/analyst/runs",
        "method": "POST",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "enabled": True,
        "created_at": 1,
    }


def test_schedules_migration_adds_provenance_columns_to_stripped_table():
    """A true 2.5.6 schedules table (no provenance columns at all) gains all eight."""
    db, db_file = _new_db_with(["schedules"])
    _strip_schedules_to_pre_v3(db_file)
    cols = _table_columns(db_file, SCHEDULES_TABLE)
    assert "user_id" not in cols
    assert not cols & set(SCHEDULE_PROVENANCE_COLUMNS)

    asyncio.run(MigrationManager(db).up(table_type="schedules"))

    cols = _table_columns(db_file, SCHEDULES_TABLE)
    assert "user_id" in cols
    assert set(SCHEDULE_PROVENANCE_COLUMNS) <= cols
    idx = _table_indexes(db_file, SCHEDULES_TABLE)
    assert f"idx_{SCHEDULES_TABLE}_managed_by" in idx
    assert f"idx_{SCHEDULES_TABLE}_target_id" in idx
    assert db.get_latest_schema_version(SCHEDULES_TABLE) == "3.0.0"


@pytest.mark.asyncio
async def test_async_schedules_migration_adds_provenance_columns():
    """Regression: the async schedules path called db.Session(), which async adapters do not
    have — the migration died after adding user_id, leaving the provenance columns missing
    and the version stamp at 2.5.6."""
    db_file = os.path.join(tempfile.mkdtemp(), "test_async_schedules.db")
    db = AsyncSqliteDb(db_file=db_file)
    await db._get_table(table_type="schedules", create_table_if_not_found=True)
    _strip_schedules_to_pre_v3(db_file)
    cols = _table_columns(db_file, SCHEDULES_TABLE)
    assert "user_id" not in cols
    assert not cols & set(SCHEDULE_PROVENANCE_COLUMNS)

    await MigrationManager(db).up(table_type="schedules")

    cols = _table_columns(db_file, SCHEDULES_TABLE)
    assert "user_id" in cols
    assert set(SCHEDULE_PROVENANCE_COLUMNS) <= cols
    idx = _table_indexes(db_file, SCHEDULES_TABLE)
    assert f"idx_{SCHEDULES_TABLE}_managed_by" in idx
    assert f"idx_{SCHEDULES_TABLE}_target_id" in idx
    assert await db.get_latest_schema_version(SCHEDULES_TABLE) == "3.0.0"

    created = await db.create_schedule(_schedule_row("after-migration"))
    assert created["id"] == "sched-after-migration"


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

METRICS_TABLE = "agno_metrics"
METRICS_LEGACY_UNIQUE = f"{METRICS_TABLE}_uq_metrics_date_period"
METRICS_UNIQUE = f"{METRICS_TABLE}_uq_metrics_user_date_period"
METRICS_DATE_INDEX = f"idx_{METRICS_TABLE}_date"
METRICS_PERIOD_INDEX = f"idx_{METRICS_TABLE}_aggregation_period"
METRICS_USER_INDEX = f"idx_{METRICS_TABLE}_user_id"
METRICS_BACKUP_TABLE = f"{METRICS_TABLE}_pre_v3_0_0"
LOOKALIKE_TABLE = "billing_rollup"

# A day that was over before the upgrade, and the day the upgrade lands on.
FINISHED_DAY = date(2026, 3, 1)
UNFINISHED_DAY = date(2026, 3, 2)


def _legacy_metrics_ddl(db, schemas, table: str) -> list[str]:
    """A metrics table exactly as v2.5.6 created it: no user_id, unique on (date, period)."""
    columns, indexed = [], []
    for name, spec in schemas.METRICS_TABLE_SCHEMA.items():
        if name.startswith("_") or name == "user_id":
            continue
        columns.append(
            Column(
                name,
                spec["type"](),
                primary_key=spec.get("primary_key", False),
                nullable=spec.get("nullable", True),
            )
        )
        if spec.get("index"):
            indexed.append(name)

    legacy = Table(
        table,
        MetaData(schema=getattr(db, "db_schema", None)),
        *columns,
        UniqueConstraint("date", "aggregation_period", name=f"{table}_uq_metrics_date_period"),
    )
    dialect = db.db_engine.dialect
    return [str(CreateTable(legacy).compile(dialect=dialect))] + [
        str(CreateIndex(Index(f"idx_{table}_{name}", legacy.c[name])).compile(dialect=dialect)) for name in indexed
    ]


def _legacy_metrics_insert(table: str) -> str:
    """The INSERT a pre-v3 install ran: no user_id to fill, and a uuid for an id."""
    return (
        f"INSERT INTO {table} (id, agent_runs_count, team_runs_count, workflow_runs_count, agent_sessions_count, "
        "team_sessions_count, workflow_sessions_count, users_count, token_metrics, model_metrics, date, "
        "aggregation_period, created_at, updated_at, completed) "
        "VALUES (:id,7,0,0,4,0,0,2,'{}','{}',:date,'daily',1700000000,NULL,:completed)"
    )


def _metrics_record(user_id: str, day: date = UNFINISHED_DAY) -> dict:
    """One per-user metrics bucket, shaped the way calculate_date_metrics emits one."""
    return {
        "id": str(uuid4()),
        "date": day,
        "aggregation_period": "daily",
        "user_id": user_id,
        "users_count": 1,
        "agent_runs_count": 1,
        "team_runs_count": 0,
        "workflow_runs_count": 0,
        "agent_sessions_count": 1,
        "team_sessions_count": 0,
        "workflow_sessions_count": 0,
        "token_metrics": {},
        "model_metrics": [],
        "created_at": 1700000002,
        "updated_at": 1700000002,
        "completed": False,
    }


def _upsert_metrics(db, records: list[dict]) -> None:
    """Write metrics the way ``calculate_metrics`` does: the upsert names
    (user_id, date, aggregation_period) as its conflict target, so it only lands
    against the v3.0 unique key where a raw INSERT would pass either way."""
    from agno.db.sqlite.utils import bulk_upsert_metrics

    table = db._get_table(table_type="metrics", create_table_if_not_found=True)
    with db.Session() as sess, sess.begin():
        bulk_upsert_metrics(session=sess, table=table, metrics_records=records)


async def _async_upsert_metrics(db, records: list[dict]) -> None:
    """Async version of ``_upsert_metrics``."""
    from agno.db.sqlite.utils import abulk_upsert_metrics

    table = await db._get_table(table_type="metrics", create_table_if_not_found=True)
    async with db.async_session_factory() as sess, sess.begin():
        await abulk_upsert_metrics(session=sess, table=table, metrics_records=records)


def _new_legacy_metrics_db():
    """A v2.5.6 metrics table with one finished day in it."""
    from agno.db.sqlite import schemas

    db_file = os.path.join(tempfile.mkdtemp(), "test.db")
    db = SqliteDb(db_file=db_file)
    db._get_table(table_type="versions", create_table_if_not_found=True)

    conn = sqlite3.connect(db_file)
    try:
        for statement in _legacy_metrics_ddl(db, schemas, METRICS_TABLE):
            conn.execute(statement)
        conn.execute(
            "INSERT INTO agno_schema_versions (table_name, version, created_at) VALUES (?, '2.5.6', '1700000000')",
            (METRICS_TABLE,),
        )
        conn.commit()
    finally:
        conn.close()

    _insert_legacy_metrics_row(db_file, FINISHED_DAY)
    return db, db_file


def _new_lookalike_metrics_db():
    """An operator's own table, wired up as the metrics table by mistake."""
    db_file = os.path.join(tempfile.mkdtemp(), "test.db")
    db = SqliteDb(db_file=db_file, metrics_table=LOOKALIKE_TABLE)
    db._get_table(table_type="versions", create_table_if_not_found=True)

    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            f"CREATE TABLE {LOOKALIKE_TABLE} (id VARCHAR NOT NULL PRIMARY KEY, date DATE NOT NULL, "
            "aggregation_period VARCHAR NOT NULL, amount_cents BIGINT NOT NULL)"
        )
        conn.execute(f"INSERT INTO {LOOKALIKE_TABLE} VALUES ('invoice-1', '2026-03-01', 'daily', 4200)")
        conn.execute(
            "INSERT INTO agno_schema_versions (table_name, version, created_at) VALUES (?, '2.5.6', '1700000000')",
            (LOOKALIKE_TABLE,),
        )
        conn.commit()
    finally:
        conn.close()
    return db, db_file


def _new_hand_patched_metrics_db():
    """A v3.0 metrics table whose user_id an operator added themselves: it takes NULL."""
    _, fresh_file = _new_db_with(["metrics"])
    nullable_ddl = _table_ddl(fresh_file, METRICS_TABLE).replace("user_id VARCHAR NOT NULL", "user_id VARCHAR")
    assert "user_id VARCHAR NOT NULL" not in nullable_ddl

    db_file = os.path.join(tempfile.mkdtemp(), "test.db")
    db = SqliteDb(db_file=db_file)
    db._get_table(table_type="versions", create_table_if_not_found=True)

    conn = sqlite3.connect(db_file)
    try:
        conn.execute(nullable_ddl)
        conn.execute(
            "INSERT INTO agno_schema_versions (table_name, version, created_at) VALUES (?, '3.0.0', '1700000000')",
            (METRICS_TABLE,),
        )
        conn.commit()
    finally:
        conn.close()

    _insert_legacy_metrics_row(db_file, FINISHED_DAY)
    return db, db_file


def _insert_legacy_metrics_row(db_file: str, day: date, completed: bool = True) -> None:
    """Insert a metrics row the way a pre-v3 install would: no user_id to fill."""
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            _legacy_metrics_insert(METRICS_TABLE),
            {"id": str(uuid4()), "date": day.isoformat(), "completed": completed},
        )
        conn.commit()
    finally:
        conn.close()


def _table_ddl(db_file: str, table: str) -> str:
    conn = sqlite3.connect(db_file)
    try:
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        return row[0] if row else ""
    finally:
        conn.close()


def _table_names(db_file: str) -> set[str]:
    conn = sqlite3.connect(db_file)
    try:
        return {t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        conn.close()


def _metrics_rows(db_file: str) -> list:
    """Every metrics row as (date, agent_runs_count)."""
    conn = sqlite3.connect(db_file)
    try:
        return conn.execute(f"SELECT date, agent_runs_count FROM {METRICS_TABLE} ORDER BY date").fetchall()
    finally:
        conn.close()


def _metrics_owners(db_file: str) -> list:
    """Every metrics row's user_id, in order."""
    conn = sqlite3.connect(db_file)
    try:
        return [r[0] for r in conn.execute(f"SELECT user_id FROM {METRICS_TABLE} ORDER BY user_id, date").fetchall()]
    finally:
        conn.close()


def _run_sqlite(db_file: str, *statements: str) -> None:
    """Run statements straight against the database, the way an operator would."""
    conn = sqlite3.connect(db_file)
    try:
        for statement in statements:
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()


def test_metrics_migration_swaps_the_unique_key():
    db, db_file = _new_legacy_metrics_db()
    assert METRICS_LEGACY_UNIQUE in _table_ddl(db_file, METRICS_TABLE)

    asyncio.run(MigrationManager(db).up(table_type="metrics"))

    assert "user_id" in _table_columns(db_file, METRICS_TABLE)
    assert METRICS_USER_INDEX in _table_indexes(db_file, METRICS_TABLE)
    assert METRICS_UNIQUE in _table_ddl(db_file, METRICS_TABLE)
    assert METRICS_LEGACY_UNIQUE not in _table_ddl(db_file, METRICS_TABLE)
    assert db.get_latest_schema_version(METRICS_TABLE) == "3.0.0"


def test_metrics_migration_keeps_rows_and_other_indexes():
    db, db_file = _new_legacy_metrics_db()

    asyncio.run(MigrationManager(db).up(table_type="metrics"))

    assert _metrics_rows(db_file) == [(FINISHED_DAY.isoformat(), 7)]
    # both of the indexes v2.5.6 declared come back with the rebuilt table
    assert {METRICS_DATE_INDEX, METRICS_PERIOD_INDEX} <= _table_indexes(db_file, METRICS_TABLE)
    assert METRICS_BACKUP_TABLE not in _table_names(db_file)


def test_metrics_migrated_rows_land_in_the_unowned_bucket():
    """Rows written before ownership existed get "", not NULL: a unique key containing
    user_id would treat every NULL as distinct."""
    db, db_file = _new_legacy_metrics_db()

    asyncio.run(MigrationManager(db).up(table_type="metrics"))

    assert _metrics_owners(db_file) == [""]
    # "" is an implementation detail: the adapter hands back None
    assert db.get_metrics()[0][0]["user_id"] is None


def test_metrics_migration_drops_unfinished_days_and_keeps_finished_ones():
    """The day the upgrade lands on holds every user's traffic in one row, so stamped
    unowned it would be counted twice. Finished days are frozen and stay as they are."""
    from agno.db.migrations.versions import v3_0_0

    db, db_file = _new_legacy_metrics_db()
    _insert_legacy_metrics_row(db_file, UNFINISHED_DAY, completed=False)

    asyncio.run(MigrationManager(db).up(table_type="metrics"))

    assert _metrics_rows(db_file) == [(FINISHED_DAY.isoformat(), 7)]

    # only the run that adds the column may delete, so a live per-user bucket survives
    _upsert_metrics(db, [_metrics_record("alice")])
    v3_0_0.up(db, "metrics", METRICS_TABLE)

    assert _metrics_owners(db_file) == ["", "alice"]


def test_metrics_two_owners_can_share_a_date_after_the_migration():
    """The whole point of the swap: the legacy key allowed one row per date."""
    _, legacy_file = _new_legacy_metrics_db()
    # the legacy key allows exactly one row per (date, period), whoever owns it
    with pytest.raises(sqlite3.IntegrityError):
        _insert_legacy_metrics_row(legacy_file, FINISHED_DAY)

    db, db_file = _new_legacy_metrics_db()
    asyncio.run(MigrationManager(db).up(table_type="metrics"))

    _upsert_metrics(db, [_metrics_record("alice"), _metrics_record("bob")])

    assert _metrics_owners(db_file) == ["", "alice", "bob"]
    assert [r["user_id"] for r in db.get_metrics(user_id="alice")[0]] == ["alice"]


def test_metrics_migration_is_idempotent():
    from agno.db.migrations.versions import v3_0_0

    db, db_file = _new_legacy_metrics_db()

    asyncio.run(MigrationManager(db).up(table_type="metrics"))
    before_ddl = _table_ddl(db_file, METRICS_TABLE)
    before_idx = _table_indexes(db_file, METRICS_TABLE)
    v3_0_0.up(db, "metrics", METRICS_TABLE)

    assert _table_ddl(db_file, METRICS_TABLE) == before_ddl
    assert _table_indexes(db_file, METRICS_TABLE) == before_idx
    assert _metrics_rows(db_file) == [(FINISHED_DAY.isoformat(), 7)]


def test_metrics_rebuild_refuses_a_table_with_operator_columns():
    """The rebuild recreates the table from the schema, so a column it does not declare would go
    with it. The table is left alone instead."""
    db, db_file = _new_legacy_metrics_db()
    _run_sqlite(
        db_file,
        f"ALTER TABLE {METRICS_TABLE} ADD COLUMN cost_centre TEXT",
        f"UPDATE {METRICS_TABLE} SET cost_centre = 'eu-west'",
    )
    before_ddl = _table_ddl(db_file, METRICS_TABLE)

    asyncio.run(MigrationManager(db).up(table_type="metrics"))

    assert _table_ddl(db_file, METRICS_TABLE) == before_ddl
    assert "user_id" not in _table_columns(db_file, METRICS_TABLE)
    conn = sqlite3.connect(db_file)
    try:
        assert conn.execute(f"SELECT cost_centre FROM {METRICS_TABLE}").fetchall() == [("eu-west",)]
    finally:
        conn.close()


def test_metrics_interrupted_rebuild_leaves_the_table_untouched():
    """The rebuild is one transaction: a statement failing part way through leaves the
    table as it was, and a second run once the obstacle is gone migrates cleanly."""
    db, db_file = _new_legacy_metrics_db()
    before_ddl = _table_ddl(db_file, METRICS_TABLE)
    before_indexes = _table_indexes(db_file, METRICS_TABLE)
    # index names are database-wide in SQLite, so one squatting on a name the
    # rebuild needs fails it after the table has been renamed aside
    _run_sqlite(
        db_file,
        "CREATE TABLE leftover (user_id VARCHAR)",
        f"CREATE INDEX {METRICS_USER_INDEX} ON leftover (user_id)",
    )

    with pytest.raises(Exception):
        asyncio.run(MigrationManager(db).up(table_type="metrics"))

    assert _table_ddl(db_file, METRICS_TABLE) == before_ddl
    assert _table_indexes(db_file, METRICS_TABLE) == before_indexes
    assert _metrics_rows(db_file) == [(FINISHED_DAY.isoformat(), 7)]
    assert METRICS_BACKUP_TABLE not in _table_names(db_file)
    assert db.get_latest_schema_version(METRICS_TABLE) == "2.5.6"

    _run_sqlite(db_file, f"DROP INDEX {METRICS_USER_INDEX}")
    asyncio.run(MigrationManager(db).up(table_type="metrics"))

    assert METRICS_UNIQUE in _table_ddl(db_file, METRICS_TABLE)
    assert _metrics_rows(db_file) == [(FINISHED_DAY.isoformat(), 7)]


def test_metrics_rebuild_refuses_a_lookalike_table():
    """The rebuild replaces the table, so a metrics_table pointing elsewhere is refused."""
    db, db_file = _new_lookalike_metrics_db()
    before_ddl = _table_ddl(db_file, LOOKALIKE_TABLE)

    asyncio.run(MigrationManager(db).up(table_type="metrics"))

    assert _table_ddl(db_file, LOOKALIKE_TABLE) == before_ddl
    assert "user_id" not in _table_columns(db_file, LOOKALIKE_TABLE)
    conn = sqlite3.connect(db_file)
    try:
        assert conn.execute(f"SELECT amount_cents FROM {LOOKALIKE_TABLE}").fetchall() == [(4200,)]
    finally:
        conn.close()


def test_metrics_revert_refuses_while_rows_are_owned():
    """Dropping user_id would merge alice's and bob's buckets for a date."""
    db, db_file = _new_legacy_metrics_db()
    asyncio.run(MigrationManager(db).up(table_type="metrics"))
    _upsert_metrics(db, [_metrics_record("alice"), _metrics_record("bob")])

    asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="metrics"))

    assert "user_id" in _table_columns(db_file, METRICS_TABLE)
    assert METRICS_UNIQUE in _table_ddl(db_file, METRICS_TABLE)
    assert db.get_latest_schema_version(METRICS_TABLE) == "3.0.0"


def test_metrics_revert_refuses_when_an_owner_is_null():
    """The column is NOT NULL, so a NULL owner is not the unowned bucket."""
    db, db_file = _new_hand_patched_metrics_db()

    asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="metrics"))

    assert "user_id" in _table_columns(db_file, METRICS_TABLE)
    assert METRICS_UNIQUE in _table_ddl(db_file, METRICS_TABLE)
    assert db.get_latest_schema_version(METRICS_TABLE) == "3.0.0"


def test_metrics_revert_restores_the_legacy_unique_key():
    db, db_file = _new_legacy_metrics_db()
    before_ddl = _table_ddl(db_file, METRICS_TABLE)
    before_indexes = _table_indexes(db_file, METRICS_TABLE)
    assert {METRICS_DATE_INDEX, METRICS_PERIOD_INDEX} <= before_indexes
    asyncio.run(MigrationManager(db).up(table_type="metrics"))

    asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="metrics"))

    # back to the v2.5.6 table statement for statement, and to its indexes
    assert _table_ddl(db_file, METRICS_TABLE) == before_ddl
    assert _table_indexes(db_file, METRICS_TABLE) == before_indexes
    assert "user_id" not in _table_columns(db_file, METRICS_TABLE)
    assert _metrics_rows(db_file) == [(FINISHED_DAY.isoformat(), 7)]
    assert db.get_latest_schema_version(METRICS_TABLE) == "2.5.6"


@pytest.mark.asyncio
async def test_async_metrics_up_and_down():
    _, db_file = _new_legacy_metrics_db()
    db = AsyncSqliteDb(db_file=db_file)

    await MigrationManager(db).up(table_type="metrics")
    assert "user_id" in _table_columns(db_file, METRICS_TABLE)
    assert METRICS_UNIQUE in _table_ddl(db_file, METRICS_TABLE)
    assert {METRICS_DATE_INDEX, METRICS_PERIOD_INDEX, METRICS_USER_INDEX} <= _table_indexes(db_file, METRICS_TABLE)

    await _async_upsert_metrics(db, [_metrics_record("alice"), _metrics_record("bob")])
    assert _metrics_owners(db_file) == ["", "alice", "bob"]
    assert [r["user_id"] for r in (await db.get_metrics(user_id="alice"))[0]] == ["alice"]

    # the owned rows block the revert here exactly as they do on the sync adapter
    await MigrationManager(db).down(target_version="2.5.6", table_type="metrics")
    assert "user_id" in _table_columns(db_file, METRICS_TABLE)

    _run_sqlite(db_file, f"DELETE FROM {METRICS_TABLE} WHERE user_id <> ''")
    await MigrationManager(db).down(target_version="2.5.6", table_type="metrics")

    assert "user_id" not in _table_columns(db_file, METRICS_TABLE)
    assert METRICS_LEGACY_UNIQUE in _table_ddl(db_file, METRICS_TABLE)
    assert {METRICS_DATE_INDEX, METRICS_PERIOD_INDEX} <= _table_indexes(db_file, METRICS_TABLE)
    assert _metrics_rows(db_file) == [(FINISHED_DAY.isoformat(), 7)]
