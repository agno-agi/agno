"""Queue listings propagate failures when requested across all built-in stores."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.redis import RedisDb
from agno.job_queue.store import InMemoryQueueStore
from agno.os.job_queue import _SyncStoreAdapter


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["postgres", "async_postgres", "redis", "memory"])
@pytest.mark.parametrize("raise_on_error", [False, True])
async def test_list_jobs_error_policy(kind, raise_on_error, monkeypatch):
    error = RuntimeError("Injected queue read failure")
    if kind == "postgres":
        db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:59999/ai")
        monkeypatch.setattr(db, "_get_table", MagicMock(side_effect=error))
        store = _SyncStoreAdapter(db)
    elif kind == "async_postgres":
        store = AsyncPostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:59999/ai")
        monkeypatch.setattr(store, "_get_table", AsyncMock(side_effect=error))
    elif kind == "redis":
        client = MagicMock()
        client.zrevrange.side_effect = error
        store = _SyncStoreAdapter(RedisDb(redis_client=client))
    else:
        store = InMemoryQueueStore()
        lock = MagicMock()
        lock.__aenter__ = AsyncMock(side_effect=error)
        monkeypatch.setattr(store, "_lock", lock)

    # PostgreSQL's default fallback remains compatible; the other stores
    # already propagate errors even when callers do not require it.
    if not raise_on_error and kind in {"postgres", "async_postgres"}:
        assert await store.list_jobs(raise_on_error=raise_on_error) == ([], 0)
    else:
        with pytest.raises(RuntimeError) as raised:
            await store.list_jobs(raise_on_error=raise_on_error)
        assert raised.value is error


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs_adapter", [False, True])
async def test_purge_legacy_queue_filter_falls_back_to_complete_list(kwargs_adapter):
    from types import SimpleNamespace

    from agno.company.execution import _TaskRunConflict, _verify_task_purge
    from agno.db.schemas.jobs import QueuedJob

    store = InMemoryQueueStore()
    for index in range(102):
        await store.enqueue_job(
            QueuedJob(
                id=str(index),
                component_type="agent",
                component_id="a1",
                session_id="other",
                payload={"company_task_id": "task"} if index == 0 else {},
                created_at=index,
            ).to_dict()
        )
    calls = []

    async def legacy(status=None, limit=20, raise_on_error=False):
        calls.append(limit)
        assert raise_on_error
        return await store.list_jobs(status=status, limit=limit, raise_on_error=raise_on_error)

    async def permissive(**kwargs):
        assert "company_task_id" not in kwargs and "session_id" not in kwargs
        return await legacy(**kwargs)

    queue = SimpleNamespace(store=SimpleNamespace(list_jobs=permissive if kwargs_adapter else legacy))
    # Known empty history lets these queue-only checks reach the queue verifier.
    task = {
        "id": "task",
        "status": "backlog",
        "metadata": {"_agno_execution_provenance": {"complete": True, "stores": []}},
    }
    with pytest.raises(_TaskRunConflict, match="Cancel live Task executions"):
        await _verify_task_purge(None, [task], queue)
    assert calls == [100, 200]


@pytest.mark.asyncio
async def test_purge_filtered_queue_read_failure_blocks_deletion():
    from types import SimpleNamespace

    from agno.company.execution import _TaskRunUnavailable, _verify_task_purge

    async def unavailable(*, company_task_id=None, session_id=None, **kwargs):
        assert kwargs["limit"] == 1
        assert kwargs["raise_on_error"]
        raise RuntimeError("queue read failed")

    queue = SimpleNamespace(store=SimpleNamespace(list_jobs=unavailable))
    task = {
        "id": "task",
        "status": "backlog",
        "metadata": {"_agno_execution_provenance": {"complete": True, "stores": []}},
    }
    with pytest.raises(_TaskRunUnavailable, match="queue is unavailable") as raised:
        await _verify_task_purge(None, [task], queue)
    assert str(raised.value.__cause__) == "queue read failed"
