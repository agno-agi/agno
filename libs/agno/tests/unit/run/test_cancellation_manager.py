import pytest

from agno.run.cancellation_management.redis_cancellation_manager import RedisRunCancellationManager


def test_redis_parent_cancellation_cascades_to_child_runs():
    fakeredis = pytest.importorskip("fakeredis")

    manager = RedisRunCancellationManager(
        redis_client=fakeredis.FakeStrictRedis(decode_responses=False),
        key_prefix="test:agno:run:cancellation:",
        ttl_seconds=None,
    )

    parent_run_id = "redis-parent"
    child_run_id = "redis-child"
    grandchild_run_id = "redis-grandchild"

    manager.register_run(parent_run_id)
    manager.register_run(child_run_id)
    manager.register_run(grandchild_run_id)
    manager.register_child_run(parent_run_id, child_run_id)
    manager.register_child_run(child_run_id, grandchild_run_id)

    assert manager.cancel_run(parent_run_id) is True

    assert manager.is_cancelled(parent_run_id) is True
    assert manager.is_cancelled(child_run_id) is True
    assert manager.is_cancelled(grandchild_run_id) is True
    assert manager.get_active_runs() == {
        parent_run_id: True,
        child_run_id: True,
        grandchild_run_id: True,
    }


@pytest.mark.asyncio
async def test_redis_async_cancel_before_child_registration_cancels_child_immediately():
    pytest.importorskip("fakeredis")
    from fakeredis.aioredis import FakeRedis as AsyncFakeRedis

    manager = RedisRunCancellationManager(
        async_redis_client=AsyncFakeRedis(decode_responses=False),
        key_prefix="test:agno:async:run:cancellation:",
        ttl_seconds=None,
    )

    parent_run_id = "redis-async-parent"
    child_run_id = "redis-async-child"

    assert await manager.acancel_run(parent_run_id) is False
    await manager.aregister_run(child_run_id)
    await manager.aregister_child_run(parent_run_id, child_run_id)

    assert await manager.ais_cancelled(child_run_id) is True
