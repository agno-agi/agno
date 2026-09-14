"""Fresh PostgreSQL queue startup, including concurrent replicas and no first enqueue."""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.job_queue.config import QueueConfig
from agno.os.job_queue import QueueWorker, araise_if_ticket_owns_continue, resolve_queue_store

PG_URL = os.getenv("AGNO_TEST_POSTGRES_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai")


@pytest.fixture
def database_schema():
    engine = create_engine(PG_URL)
    schema = "queue_startup_" + uuid4().hex[:12]
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    except Exception as exc:
        engine.dispose()
        pytest.skip(f"Local PostgreSQL unavailable: {type(exc).__name__}")
    try:
        yield schema
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("async_db", [False, True])
async def test_worker_start_provisions_idle_store_and_allows_continue(database_schema, async_db, caplog):
    db_type = AsyncPostgresDb if async_db else PostgresDb
    db = db_type(db_url=PG_URL, db_schema=database_schema)
    config = QueueConfig(poll_interval=0.01)
    store = resolve_queue_store(config, db)
    worker = QueueWorker(store, lambda *_: None, config)
    exists = await db.table_exists(db.job_table_name) if async_db else db.table_exists(db.job_table_name)
    assert not exists
    await worker.start()
    try:
        exists = await db.table_exists(db.job_table_name) if async_db else db.table_exists(db.job_table_name)
        assert exists
        await araise_if_ticket_owns_continue(worker, "inline-run")
        await asyncio.sleep(0.035)
        assert await store.count_queued_jobs() == 0
        assert not any("preparation failed" in record.message for record in caplog.records)
    finally:
        await worker.stop()
    # Restart should resolve the existing table and still admit ticketless continuations.
    await worker.start()
    try:
        await araise_if_ticket_owns_continue(worker, "another-inline-run")
    finally:
        await worker.stop()
        if async_db:
            await db.close()
        else:
            db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("async_db", [False, True])
async def test_concurrent_queue_provisioning(database_schema, async_db, caplog):
    db_type = AsyncPostgresDb if async_db else PostgresDb
    dbs = [db_type(db_url=PG_URL, db_schema=database_schema) for _ in range(2)]
    try:
        if async_db:
            await asyncio.gather(*(db.ensure_jobs_table() for db in dbs))
        else:
            await asyncio.gather(*(asyncio.to_thread(db.ensure_jobs_table) for db in dbs))
        stores = [resolve_queue_store(QueueConfig(), db) for db in dbs]
        assert await stores[0].get_job("no-ticket", strict=True) is None
        assert await stores[1].get_job("no-ticket", strict=True) is None
        assert not [record for record in caplog.records if record.levelno >= 30]
    finally:
        for db in dbs:
            if async_db:
                await db.close()
            else:
                db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("async_db", [False, True])
async def test_external_provisioning_does_not_create_queue_table(database_schema, async_db):
    db_type = AsyncPostgresDb if async_db else PostgresDb
    db = db_type(db_url=PG_URL, db_schema=database_schema)
    config = QueueConfig(poll_interval=0.01)
    worker = QueueWorker(resolve_queue_store(config, db), lambda *_: None, config, auto_provision=False)
    try:
        await worker.start()
        await asyncio.sleep(0.025)
        exists = await db.table_exists(db.job_table_name) if async_db else db.table_exists(db.job_table_name)
        assert not exists
    finally:
        await worker.stop()
        if async_db:
            await db.close()
        else:
            db.close()
