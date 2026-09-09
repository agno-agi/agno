"""Postgres mirror of the async schedules migration tests in test_v3_user_id_migration.py.

Regression coverage: the async schedules migration path called db.Session(), which async
adapters do not have — on a pre-3.0 install the migration died after adding user_id,
leaving the provenance columns missing and the version stamp at 2.5.6.

Runs against the live pgvector container (localhost:5532) with a unique schema per run;
skips cleanly when psycopg or the server is absent.
"""

import uuid

import pytest
from sqlalchemy import create_engine, text

from agno.db.migrations.manager import MigrationManager
from agno.db.migrations.versions.v3_0_0 import SCHEDULE_PROVENANCE_COLUMNS

pytest.importorskip("psycopg")

from agno.db.postgres import AsyncPostgresDb  # noqa: E402

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
SCHEDULES_TABLE = "agno_schedules"


def _server_reachable() -> bool:
    # A raw probe, not an adapter call: adapter methods catch and log
    # connection errors, so they cannot signal an absent server.
    engine = create_engine(DB_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def _postgres_server():
    if not _server_reachable():
        pytest.skip(f"Postgres server not reachable at {DB_URL}")


@pytest.fixture
def schema(_postgres_server):
    name = f"v3_mig_{uuid.uuid4().hex[:8]}"
    yield name
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
        conn.commit()
    engine.dispose()


def _strip_schedules_to_pre_v3(schema: str) -> None:
    """Mimic a 2.5.6 schedules table: no user_id, no provenance columns, rewound stamp.

    Postgres drops every index that covers a column with the column itself, so the
    user_id and provenance indexes (unique name backstops included) go too.
    """
    engine = create_engine(DB_URL)
    try:
        with engine.connect() as conn:
            for column in ("user_id", *SCHEDULE_PROVENANCE_COLUMNS):
                conn.execute(text(f'ALTER TABLE "{schema}".{SCHEDULES_TABLE} DROP COLUMN {column}'))
            conn.execute(
                text(f"UPDATE \"{schema}\".agno_schema_versions SET version='2.5.6' WHERE table_name=:t"),
                {"t": SCHEDULES_TABLE},
            )
            conn.commit()
    finally:
        engine.dispose()


def _table_columns(schema: str) -> set:
    engine = create_engine(DB_URL)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_schema = :s AND table_name = :t"),
                {"s": schema, "t": SCHEDULES_TABLE},
            ).fetchall()
        return {r[0] for r in rows}
    finally:
        engine.dispose()


def _table_indexes(schema: str) -> set:
    engine = create_engine(DB_URL)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = :s AND tablename = :t"),
                {"s": schema, "t": SCHEDULES_TABLE},
            ).fetchall()
        return {r[0] for r in rows}
    finally:
        engine.dispose()


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


@pytest.mark.asyncio
async def test_async_postgres_schedules_migration_adds_provenance_columns(schema):
    db = AsyncPostgresDb(db_url=DB_URL, db_schema=schema)
    try:
        await db._get_table(table_type="schedules", create_table_if_not_found=True)
        _strip_schedules_to_pre_v3(schema)
        cols = _table_columns(schema)
        assert "user_id" not in cols
        assert not cols & set(SCHEDULE_PROVENANCE_COLUMNS)

        await MigrationManager(db).up(table_type="schedules")

        cols = _table_columns(schema)
        assert "user_id" in cols
        assert set(SCHEDULE_PROVENANCE_COLUMNS) <= cols
        idx = _table_indexes(schema)
        assert f"idx_{SCHEDULES_TABLE}_managed_by" in idx
        assert f"idx_{SCHEDULES_TABLE}_target_id" in idx
        assert await db.get_latest_schema_version(SCHEDULES_TABLE) == "3.0.0"

        created = await db.create_schedule(_schedule_row("after-migration"))
        assert created["id"] == "sched-after-migration"
    finally:
        await db.db_engine.dispose()
