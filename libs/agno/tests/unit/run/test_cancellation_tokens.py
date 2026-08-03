"""Token-scoped cancellation cleanup (generation-scoped intent).

Every cancel mints an opaque token; cleanup-if-token is an atomic
compare-and-delete on that token. A cleanup delayed arbitrarily (stalled
coroutine, resumed process) holds an OLD token and provably cannot erase a
NEWER cancel - equality, not ordering, so no clocks and no counters.
"""

import pytest

from agno.run.cancellation_management.in_memory_cancellation_manager import InMemoryRunCancellationManager


class TestInMemoryTokens:
    @pytest.mark.asyncio
    async def test_token_exists_only_with_intent(self):
        m = InMemoryRunCancellationManager()
        assert await m.aget_cancellation_token("r1") is None
        await m.aregister_run("r1")
        assert await m.aget_cancellation_token("r1") is None, "registered-not-cancelled has no token"
        await m.acancel_run("r1")
        assert await m.aget_cancellation_token("r1") is not None

    @pytest.mark.asyncio
    async def test_every_cancel_mints_a_fresh_token(self):
        m = InMemoryRunCancellationManager()
        await m.acancel_run("r1")
        first = await m.aget_cancellation_token("r1")
        await m.acancel_run("r1")
        second = await m.aget_cancellation_token("r1")
        assert first != second

    @pytest.mark.asyncio
    async def test_conditional_cleanup_removes_only_the_observed_intent(self):
        m = InMemoryRunCancellationManager()
        await m.acancel_run("r1")
        token = await m.aget_cancellation_token("r1")
        assert await m.acleanup_run_if_token("r1", token) is True
        assert not await m.ais_cancelled("r1")

    @pytest.mark.asyncio
    async def test_delayed_cleanup_declines_against_a_newer_cancel(self):
        """The load-bearing property: an old token can never delete new intent."""
        m = InMemoryRunCancellationManager()
        await m.acancel_run("r1")
        stale_token = await m.aget_cancellation_token("r1")
        await m.acancel_run("r1")  # newer, legitimate cancel
        assert await m.acleanup_run_if_token("r1", stale_token) is False
        assert await m.ais_cancelled("r1"), "the newer cancel must survive the delayed cleanup"

    def test_sync_variants_mirror_async(self):
        m = InMemoryRunCancellationManager()
        m.cancel_run("r1")
        stale = m.get_cancellation_token("r1")
        m.cancel_run("r1")
        assert m.cleanup_run_if_token("r1", stale) is False
        assert m.is_cancelled("r1")
        fresh = m.get_cancellation_token("r1")
        assert m.cleanup_run_if_token("r1", fresh) is True
        assert not m.is_cancelled("r1")


fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")


def _redis_manager():
    from agno.run.cancellation_management.redis_cancellation_manager import RedisRunCancellationManager

    server = fakeredis.FakeServer()  # ONE store behind both clients
    return RedisRunCancellationManager(
        redis_client=fakeredis.FakeRedis(server=server, decode_responses=True),
        async_redis_client=fakeredis.FakeAsyncRedis(server=server, decode_responses=True),
        key_prefix="test:cancel:",
    )


class TestRedisTokens:
    @pytest.mark.asyncio
    async def test_cancel_value_carries_token_and_reads_cancelled(self):
        m = _redis_manager()
        await m.aregister_run("r1")
        assert not await m.ais_cancelled("r1")
        assert await m.aget_cancellation_token("r1") is None, "'0' (registered) is not intent"
        await m.acancel_run("r1")
        assert await m.ais_cancelled("r1"), "token-carrying value must still read as cancelled"
        assert await m.aget_cancellation_token("r1") is not None

    @pytest.mark.asyncio
    async def test_delayed_cleanup_declines_against_a_newer_cancel(self):
        m = _redis_manager()
        await m.acancel_run("r1")
        stale_token = await m.aget_cancellation_token("r1")
        await m.acancel_run("r1")
        assert await m.acleanup_run_if_token("r1", stale_token) is False
        assert await m.ais_cancelled("r1")

    @pytest.mark.asyncio
    async def test_conditional_cleanup_removes_matching_intent(self):
        m = _redis_manager()
        await m.acancel_run("r1")
        token = await m.aget_cancellation_token("r1")
        assert await m.acleanup_run_if_token("r1", token) is True
        assert not await m.ais_cancelled("r1")

    def test_sync_variants_mirror_async(self):
        m = _redis_manager()
        m.cancel_run("r1")
        stale = m.get_cancellation_token("r1")
        m.cancel_run("r1")
        assert m.cleanup_run_if_token("r1", stale) is False
        assert m.is_cancelled("r1")
        fresh = m.get_cancellation_token("r1")
        assert m.cleanup_run_if_token("r1", fresh) is True
        assert not m.is_cancelled("r1")

    @pytest.mark.asyncio
    async def test_legacy_bare_1_value_still_reads_cancelled(self):
        """Values written by older builds ('1' with no token) must keep
        reading as cancelled, and their token is the raw value - so even
        legacy intent participates in conditional cleanup."""
        m = _redis_manager()
        m.redis_client.set("test:cancel:r1", "1")
        assert await m.ais_cancelled("r1")
        token = await m.aget_cancellation_token("r1")
        assert token == "1"
        assert await m.acleanup_run_if_token("r1", token) is True
