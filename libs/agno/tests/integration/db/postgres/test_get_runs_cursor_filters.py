"""get_runs cursor filters, has_unindexed_runs and get_session(include_runs) against a real Postgres (:5532)."""

import asyncio

import pytest
from sqlalchemy import create_engine, text

from agno.db.postgres import AsyncPostgresDb, PostgresDb
from tests.unit.db.run_cursor_contract import SESSION_ID, check_contract, seed

SYNC_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
ASYNC_URL = "postgresql+psycopg_async://ai:ai@localhost:5532/ai"
TEST_SCHEMA = "runs_cursor_test"


@pytest.fixture
def engine():
    try:
        engine = create_engine(SYNC_URL)
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("Postgres unavailable on localhost:5532")
    with engine.connect() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        c.commit()
    yield engine
    with engine.connect() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        c.commit()
    engine.dispose()


def test_sync_contract(engine):
    asyncio.run(check_contract(PostgresDb(db_engine=engine, db_schema=TEST_SCHEMA)))


def test_async_contract(engine):
    async def run() -> None:
        db = AsyncPostgresDb(db_url=ASYNC_URL, db_schema=TEST_SCHEMA)
        try:
            await check_contract(db)
        finally:
            await db.db_engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("blob, expected", [('[{"run_id": "x"}]', True), ("[]", False), (None, False)])
def test_legacy_blob_is_unindexed(engine, blob, expected):
    db = PostgresDb(db_engine=engine, db_schema=TEST_SCHEMA)
    asyncio.run(seed(db))
    # Only a db migrated from v2 keeps the legacy runs column, so add it as the migration leaves it.
    with engine.begin() as c:
        c.execute(text(f"ALTER TABLE {TEST_SCHEMA}.agno_sessions ADD COLUMN runs JSONB"))
        c.execute(
            text(f"UPDATE {TEST_SCHEMA}.agno_sessions SET runs = CAST(:runs AS JSONB) WHERE session_id = :sid"),
            {"runs": blob, "sid": SESSION_ID},
        )
    assert PostgresDb(db_engine=engine, db_schema=TEST_SCHEMA).has_unindexed_runs(SESSION_ID) is expected


def test_null_run_index_is_unindexed(engine):
    db = PostgresDb(db_engine=engine, db_schema=TEST_SCHEMA)
    asyncio.run(seed(db))
    with engine.begin() as c:
        c.execute(text(f"UPDATE {TEST_SCHEMA}.agno_runs SET run_index = NULL WHERE run_id = 'r3'"))
    assert db.has_unindexed_runs(SESSION_ID) is True
