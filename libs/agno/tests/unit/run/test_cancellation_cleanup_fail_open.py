"""cleanup_run/acleanup_run must FAIL OPEN on Redis faults (parity with
is_cancelled): they run inside terminal paths (producers' finally blocks,
continue/requeue seams) where a coordination blip must not fail the
surrounding operation - a stale key just lives until its TTL."""

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("redis", reason="redis not installed")

from agno.run.cancellation_management.redis_cancellation_manager import (  # noqa: E402
    RedisRunCancellationManager,
)


def test_cleanup_run_fails_open_on_redis_fault():
    client = MagicMock()
    client.delete.side_effect = ConnectionError("redis down")
    manager = RedisRunCancellationManager(redis_client=client)
    manager.cleanup_run("r1")  # must not raise


@pytest.mark.asyncio
async def test_acleanup_run_fails_open_on_redis_fault():
    client = MagicMock()
    client.delete = AsyncMock(side_effect=ConnectionError("redis down"))
    manager = RedisRunCancellationManager(async_redis_client=client)
    await manager.acleanup_run("r1")  # must not raise
