"""Unit tests for QueueConfig wiring (transports from queue.redis)."""

import pytest

fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")

import agno.os.event_streams as event_streams_module  # noqa: E402
from agno.os.event_streams import (  # noqa: E402
    InMemoryEventStream,
    RedisEventStream,
    get_event_stream,
    set_event_stream,
)
from agno.os.queue import apply_queue_config  # noqa: E402
from agno.queue.config import QueueConfig, RedisCoordination  # noqa: E402
from agno.run.cancel import get_cancellation_manager, set_cancellation_manager  # noqa: E402
from agno.run.cancellation_management.in_memory_cancellation_manager import (  # noqa: E402
    InMemoryRunCancellationManager,
)
from agno.run.cancellation_management.redis_cancellation_manager import RedisRunCancellationManager  # noqa: E402
from agno.run.concurrency import get_background_max_concurrency, set_background_max_concurrency  # noqa: E402


@pytest.fixture(autouse=True)
def reset_globals():
    original_manager = get_cancellation_manager()
    original_stream = event_streams_module._event_stream
    set_cancellation_manager(InMemoryRunCancellationManager())
    event_streams_module._event_stream = None
    try:
        yield
    finally:
        set_cancellation_manager(original_manager)
        event_streams_module._event_stream = original_stream
        set_background_max_concurrency(None)


def make_coordination() -> RedisCoordination:
    return RedisCoordination(
        url=None,
        sync_client=fakeredis.FakeRedis(),
        async_client=fakeredis.FakeAsyncRedis(),
    )


class TestRedisCoordinationValidation:
    def test_url_alone_is_valid(self):
        RedisCoordination(url="redis://localhost:6379")

    def test_clients_alone_are_valid(self):
        make_coordination()

    def test_partial_clients_without_url_raise(self):
        with pytest.raises(ValueError):
            RedisCoordination(sync_client=fakeredis.FakeRedis())


class TestApplyQueueConfig:
    def test_concurrency_applied(self):
        apply_queue_config(QueueConfig(max_concurrency=7))
        assert get_background_max_concurrency() == 7

    def test_no_redis_keeps_in_memory_transports(self):
        apply_queue_config(QueueConfig())
        assert isinstance(get_cancellation_manager(), InMemoryRunCancellationManager)
        assert isinstance(get_event_stream(), InMemoryEventStream)

    def test_redis_wires_both_transports(self):
        apply_queue_config(QueueConfig(redis=make_coordination()))
        assert isinstance(get_cancellation_manager(), RedisRunCancellationManager)
        assert isinstance(get_event_stream(), RedisEventStream)

    def test_url_string_accepted(self):
        # from_url constructs lazily; no connection is made at wiring time
        apply_queue_config(QueueConfig(redis="redis://localhost:6399"))
        assert isinstance(get_cancellation_manager(), RedisRunCancellationManager)
        assert isinstance(get_event_stream(), RedisEventStream)

    def test_custom_cancellation_manager_not_clobbered(self):
        """A non-in-memory manager configured before wiring must survive it."""
        custom = RedisRunCancellationManager(
            redis_client=fakeredis.FakeRedis(), async_redis_client=fakeredis.FakeAsyncRedis()
        )
        set_cancellation_manager(custom)
        apply_queue_config(QueueConfig(redis=make_coordination()))
        assert get_cancellation_manager() is custom

    def test_custom_event_stream_not_clobbered(self):
        class CustomStream(RedisEventStream):
            pass

        custom = CustomStream(fakeredis.FakeAsyncRedis())
        set_event_stream(custom)
        apply_queue_config(QueueConfig(redis=make_coordination()))
        assert get_event_stream() is custom


class TestSyncStoreAdapter:
    @pytest.mark.asyncio
    async def test_sync_store_methods_become_awaitable(self):
        from agno.os.queue import resolve_queue_store
        from agno.queue.config import QueueConfig

        class SyncStore:
            def claim_job(self, worker_id, lock_grace_seconds=60):
                return {"id": "r1", "worker": worker_id}

            def count_queued_jobs(self):
                return 3

        store = resolve_queue_store(QueueConfig(durable=True), SyncStore())
        claimed = await store.claim_job("w1")
        assert claimed == {"id": "r1", "worker": "w1"}
        assert await store.count_queued_jobs() == 3

    @pytest.mark.asyncio
    async def test_async_store_passes_through_unwrapped(self):
        from agno.os.queue import resolve_queue_store
        from agno.queue.config import QueueConfig
        from agno.queue.store import InMemoryQueueStore

        native = InMemoryQueueStore()
        assert resolve_queue_store(QueueConfig(durable=True), native) is native

    @pytest.mark.asyncio
    async def test_durable_with_nonconforming_store_hard_fails(self):
        """durable=True is a durability promise: a db that cannot honor it must
        raise at startup, never silently degrade to an in-memory queue."""
        from agno.os.queue import resolve_queue_store
        from agno.queue.config import QueueConfig

        class NotAQueueStore:
            pass

        with pytest.raises(ValueError, match="durable"):
            resolve_queue_store(QueueConfig(durable=True), NotAQueueStore())
