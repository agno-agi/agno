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

    @pytest.mark.asyncio
    async def test_async_compare_and_delete_holds_the_threading_lock(self):
        """The asyncio lock only orders coroutines on one loop: a sync
        cancel_run on ANOTHER THREAD serializes via the threading lock, so
        the async compare-and-delete must run under it - otherwise a token
        written between compare and delete is erased."""
        import threading

        m = InMemoryRunCancellationManager()
        await m.acancel_run("r1")
        token = await m.aget_cancellation_token("r1")

        real_lock = m._lock
        held_during_delete = []

        class RecordingLock:
            def __enter__(self):
                real_lock.acquire()
                return self

            def __exit__(self, *exc):
                held_during_delete.append(True)
                real_lock.release()

        m._lock = RecordingLock()  # type: ignore[assignment]
        assert await m.acleanup_run_if_token("r1", token) is True
        assert held_during_delete, "compare-and-delete must run inside the shared threading lock"
        m._lock = real_lock

        # Threaded stress: a newer cancel from another thread must always
        # survive a concurrent stale-token cleanup
        await m.acancel_run("r2")
        stale = await m.aget_cancellation_token("r2")
        thread = threading.Thread(target=m.cancel_run, args=("r2",))
        thread.start()
        thread.join()
        assert await m.acleanup_run_if_token("r2", stale) is False
        assert await m.ais_cancelled("r2"), "the thread's newer cancel must survive"

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
    async def test_wire_value_stays_exactly_1_for_old_replicas(self):
        """Rolling-upgrade contract: OLD replicas compare the intent value to
        exactly "1". A new replica's cancel must therefore write "1" verbatim
        (token in a sidecar key), or mixed-version workers ignore it."""
        m = _redis_manager()
        await m.acancel_run("r1")
        raw = m.redis_client.get("test:cancel:r1")
        assert raw == "1", "the intent wire value must remain exactly '1' for old replicas"
        assert m.redis_client.get("test:cancel:r1:token"), "token lives in the sidecar key"
        # And an OLD replica reading with strict equality sees the cancel
        assert await m.ais_cancelled("r1")

    @pytest.mark.asyncio
    async def test_old_replica_cancel_without_token_is_uncleanable_but_visible(self):
        """Intent written by an OLD replica has no sidecar token: the token
        read returns None, callers skip conditional cleanup (safe direction),
        and the cancel stays visible."""
        m = _redis_manager()
        m.redis_client.set("test:cancel:r1", "1")  # old-replica cancel
        assert await m.ais_cancelled("r1")
        assert await m.aget_cancellation_token("r1") is None

    @pytest.mark.asyncio
    async def test_unconditional_cleanup_drops_the_sidecar_too(self):
        m = _redis_manager()
        await m.acancel_run("r1")
        await m.acleanup_run("r1")
        assert m.redis_client.get("test:cancel:r1") is None
        assert m.redis_client.get("test:cancel:r1:token") is None
