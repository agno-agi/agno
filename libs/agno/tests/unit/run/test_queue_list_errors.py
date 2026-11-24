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
