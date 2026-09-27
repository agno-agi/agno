"""Provision optional queue storage before its heartbeat and poll tasks start."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os.job_queue import QueueWorker, _SyncStoreAdapter, araise_if_ticket_owns_continue


class FreshStore(InMemoryQueueStore):
    def __init__(self):
        super().__init__()
        self.ready = False
        self.prepared = 0

    async def ensure_jobs_table(self):
        self.prepared += 1
        self.ready = True

    async def get_job(self, job_id, strict=False):
        if not self.ready and strict:
            raise RuntimeError("jobs table unavailable")
        return await super().get_job(job_id)


def worker(store, **kwargs):
    return QueueWorker(store, lambda *_: None, QueueConfig(poll_interval=0.01), **kwargs)


@pytest.mark.asyncio
async def test_prepare_precedes_polling_and_unblocks_inline_continue(monkeypatch):
    from fastapi import HTTPException

    store = FreshStore()
    instance = worker(store)
    with pytest.raises(HTTPException) as error:
        await araise_if_ticket_owns_continue(instance, "inline-run")
    assert error.value.status_code == 503

    async def poll():
        assert store.ready

    monkeypatch.setattr(instance, "_poll_loop", poll)
    await instance.start()
    try:
        await instance.start()
        await asyncio.sleep(0)
        assert store.prepared == 1
        await araise_if_ticket_owns_continue(instance, "inline-run")
    finally:
        await instance.stop()


@pytest.mark.asyncio
async def test_external_provisioning_keeps_read_only_probe():
    store = FreshStore()
    instance = worker(store, auto_provision=False)
    await instance.start()
    try:
        assert store.prepared == 0
    finally:
        await instance.stop()


@pytest.mark.asyncio
async def test_store_without_hook_still_starts():
    instance = worker(InMemoryQueueStore())
    await instance.start()
    try:
        assert instance._task is not None
    finally:
        await instance.stop()


@pytest.mark.asyncio
async def test_prepare_failure_is_reported_once_and_keeps_lazy_fallback(caplog):
    store = FreshStore()
    store.ensure_jobs_table = AsyncMock(side_effect=PermissionError("private connection details"))
    instance = worker(store)
    await instance.start()
    try:
        await asyncio.sleep(0.025)
        warnings = [record.message for record in caplog.records if "storage preparation failed" in record.message]
        assert len(warnings) == 1
        assert "PermissionError" in warnings[0]
        assert "private connection details" not in warnings[0]
        assert instance._task is not None and not instance._task.done()
    finally:
        await instance.stop()


@pytest.mark.asyncio
async def test_sync_prepare_finishes_before_heartbeat_thread(monkeypatch):
    calls = []
    store = SimpleNamespace(ensure_jobs_table=lambda: calls.append("prepare"), heartbeat_jobs=lambda *_: 0)
    instance = worker(_SyncStoreAdapter(store))
    monkeypatch.setattr(instance, "_start_heartbeat_thread", lambda *_: calls.append("heartbeat"))
    monkeypatch.setattr(instance, "_poll_loop", AsyncMock())
    await instance.start()
    try:
        assert calls == ["prepare", "heartbeat"]
    finally:
        await instance.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("async_db", [False, True])
async def test_native_preparation_does_not_mask_non_race_errors(monkeypatch, async_db):
    from agno.db.postgres import AsyncPostgresDb, PostgresDb

    db_type = AsyncPostgresDb if async_db else PostgresDb
    db = db_type(db_url="postgresql+psycopg://unused:unused@localhost/unused")
    mock_type = AsyncMock if async_db else Mock
    monkeypatch.setattr(db, "_get_table", mock_type(side_effect=PermissionError("index creation denied")))
    monkeypatch.setattr(db, "table_exists", mock_type(return_value=True))
    try:
        with pytest.raises(PermissionError, match="index creation denied"):
            if async_db:
                await db.ensure_jobs_table()
            else:
                db.ensure_jobs_table()
    finally:
        if async_db:
            await db.close()
        else:
            db.close()
