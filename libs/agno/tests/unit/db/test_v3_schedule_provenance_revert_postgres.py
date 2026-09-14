"""Postgres mirror of tests/unit/db/test_v3_schedule_provenance_revert.py.

up() adds the eight schedule provenance columns and the managed_by / target_id
lookup indexes; down(target_version="2.5.6") has to take them back off, on the
sync and the async adapter alike.

Runs against the live pgvector container (localhost:5532) with a unique schema per
run; skips cleanly when psycopg or the server is absent.
"""

import uuid

import pytest
from sqlalchemy import create_engine, text

from agno.db.migrations.manager import MigrationManager
from agno.db.migrations.versions.v3_0_0 import SCHEDULE_PROVENANCE_COLUMNS, SCHEDULE_PROVENANCE_INDEXED

pytest.importorskip("psycopg")

from agno.db.postgres import AsyncPostgresDb, PostgresDb  # noqa: E402

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
SCHEDULES_TABLE = "agno_schedules"
PROVENANCE_INDEXES = {f"idx_{SCHEDULES_TABLE}_{column}" for column in SCHEDULE_PROVENANCE_INDEXED}


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
    name = f"v3_prov_{uuid.uuid4().hex[:8]}"
    yield name
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
        conn.commit()
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


@pytest.mark.asyncio
async def test_postgres_revert_drops_provenance_columns_and_indexes(schema):
    db = PostgresDb(db_url=DB_URL, db_schema=schema)
    db._get_table(table_type="schedules", create_table_if_not_found=True)
    assert set(SCHEDULE_PROVENANCE_COLUMNS) <= _table_columns(schema)
    assert PROVENANCE_INDEXES <= _table_indexes(schema)

    await MigrationManager(db).down(target_version="2.5.6", table_type="schedules")

    columns = _table_columns(schema)
    assert not columns & set(SCHEDULE_PROVENANCE_COLUMNS)
    assert not _table_indexes(schema) & PROVENANCE_INDEXES
    assert "user_id" not in columns

    await MigrationManager(db).up(table_type="schedules")
    assert set(SCHEDULE_PROVENANCE_COLUMNS) <= _table_columns(schema)
    assert PROVENANCE_INDEXES <= _table_indexes(schema)


@pytest.mark.asyncio
async def test_async_postgres_revert_drops_provenance_columns_and_indexes(schema):
    db = AsyncPostgresDb(db_url=DB_URL, db_schema=schema)
    await db._get_table(table_type="schedules", create_table_if_not_found=True)
    assert set(SCHEDULE_PROVENANCE_COLUMNS) <= _table_columns(schema)
    assert PROVENANCE_INDEXES <= _table_indexes(schema)

    await MigrationManager(db).down(target_version="2.5.6", table_type="schedules")

    columns = _table_columns(schema)
    assert not columns & set(SCHEDULE_PROVENANCE_COLUMNS)
    assert not _table_indexes(schema) & PROVENANCE_INDEXES
    assert "user_id" not in columns

    await MigrationManager(db).up(table_type="schedules")
    assert set(SCHEDULE_PROVENANCE_COLUMNS) <= _table_columns(schema)
    assert PROVENANCE_INDEXES <= _table_indexes(schema)


@pytest.mark.asyncio
async def test_postgres_revert_tolerates_a_partly_migrated_table(schema):
    """up() adds each column only when it is missing, so half-migrated tables exist."""
    db = PostgresDb(db_url=DB_URL, db_schema=schema)
    db._get_table(table_type="schedules", create_table_if_not_found=True)
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        for column in ("target_id", "disabled_reason", "updated_by_run_id"):
            conn.execute(text(f'ALTER TABLE "{schema}".{SCHEDULES_TABLE} DROP COLUMN {column}'))
        conn.commit()
    engine.dispose()

    await MigrationManager(db).down(target_version="2.5.6", table_type="schedules")

    assert not _table_columns(schema) & set(SCHEDULE_PROVENANCE_COLUMNS)
    assert not _table_indexes(schema) & PROVENANCE_INDEXES
