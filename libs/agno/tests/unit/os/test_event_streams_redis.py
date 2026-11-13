"""Unit tests for the Redis Streams event stream (via fakeredis)."""

import asyncio
import contextlib

import pytest

fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")

import pytest_asyncio  # noqa: E402

from agno.os.event_streams.redis import RedisEventStream  # noqa: E402
from agno.run.agent import RunContentEvent  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402


@pytest_asyncio.fixture()
async def stream():
    # Short block_ms keeps idle-recheck loops fast in tests
    s = RedisEventStream(fakeredis.FakeAsyncRedis(), block_ms=100)
    yield s
    await s.aclose()


def make_event(run_id: str, content: str) -> RunContentEvent:
    return RunContentEvent(content=content, run_id=run_id)


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_register_and_status_transitions(self, stream: RedisEventStream):
        await stream.register_run("r1", RunStatus.pending)
        assert await stream.get_run_status("r1") == RunStatus.pending

        await stream.set_run_status("r1", RunStatus.running)
        assert await stream.get_run_status("r1") == RunStatus.running

        await stream.complete_run("r1", RunStatus.completed)
        assert await stream.get_run_status("r1") == RunStatus.completed

    @pytest.mark.asyncio
    async def test_register_is_idempotent(self, stream: RedisEventStream):
        await stream.register_run("r1", RunStatus.pending)
        await stream.set_run_status("r1", RunStatus.running)
        await stream.register_run("r1", RunStatus.pending)  # NX: must not reset
        assert await stream.get_run_status("r1") == RunStatus.running

    @pytest.mark.asyncio
    async def test_unknown_run_status_is_none(self, stream: RedisEventStream):
        assert await stream.get_run_status("nope") is None

    @pytest.mark.asyncio
    async def test_cleanup_removes_state(self, stream: RedisEventStream):
        await stream.register_run("r1")
        await stream.add_event("r1", make_event("r1", "a"))
        await stream.cleanup_run("r1")
        assert await stream.get_run_status("r1") is None
        assert await stream.get_event_count("r1") == 0
        assert await stream.get_last_index("r1") == -1


class TestEvents:
    @pytest.mark.asyncio
    async def test_add_event_returns_monotonic_indices(self, stream: RedisEventStream):
        assert await stream.add_event("r1", make_event("r1", "a")) == 0
        assert await stream.add_event("r1", make_event("r1", "b")) == 1
        assert await stream.get_last_index("r1") == 1
        assert await stream.get_event_count("r1") == 2

    @pytest.mark.asyncio
    async def test_replay_from_index_yields_sse_strings(self, stream: RedisEventStream):
        for content in ("a", "b", "c"):
            await stream.add_event("r1", make_event("r1", content))

        all_events = await stream.replay("r1")
        assert [idx for idx, _ in all_events] == [0, 1, 2]
        # Redis replay payloads are SSE wire strings carrying the index
        assert all('"event_index": 1' in sse or "event_index" in sse for _, sse in all_events)

        after_zero = await stream.replay("r1", last_event_index=0)
        assert [idx for idx, _ in after_zero] == [1, 2]

        assert await stream.replay("r1", last_event_index=2) == []

    @pytest.mark.asyncio
    async def test_terminal_sentinel_not_replayed_as_event(self, stream: RedisEventStream):
        await stream.add_event("r1", make_event("r1", "a"))
        await stream.complete_run("r1", RunStatus.completed)
        assert [idx for idx, _ in await stream.replay("r1")] == [0]
        # XLEN counts the sentinel; the client-facing count must not
        assert await stream.get_last_index("r1") == 0


class TestTail:
    @pytest.mark.asyncio
    async def test_tail_replays_then_streams_live_without_dups(self, stream: RedisEventStream):
        await stream.register_run("r1", RunStatus.running)
        await stream.add_event("r1", make_event("r1", "a"))
        await stream.add_event("r1", make_event("r1", "b"))

        received: list = []
        done = asyncio.Event()

        async def consume():
            async for idx, _sse in stream.tail("r1"):
                received.append(idx)
            done.set()

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.2)

        await stream.add_event("r1", make_event("r1", "c"))
        await asyncio.sleep(0.2)
        await stream.complete_run("r1", RunStatus.completed)

        await asyncio.wait_for(done.wait(), timeout=5)
        assert received == [0, 1, 2]
        await consumer

    @pytest.mark.asyncio
    async def test_tail_resumes_after_last_event_index(self, stream: RedisEventStream):
        await stream.register_run("r1", RunStatus.running)
        for content in ("a", "b", "c"):
            await stream.add_event("r1", make_event("r1", content))
        await stream.complete_run("r1", RunStatus.completed)

        received = [idx async for idx, _sse in stream.tail("r1", last_event_index=0)]
        assert received == [1, 2]

    @pytest.mark.asyncio
    async def test_tail_of_completed_run_terminates(self, stream: RedisEventStream):
        await stream.add_event("r1", make_event("r1", "a"))
        await stream.complete_run("r1", RunStatus.completed)

        received = [idx async for idx, _sse in stream.tail("r1")]
        assert received == [0]

    @pytest.mark.asyncio
    async def test_tail_exits_when_producer_dies_without_sentinel(self, stream: RedisEventStream):
        """A dead producer writes no terminal sentinel; the idle status
        re-check must end the tail rather than block forever."""
        await stream.register_run("r1", RunStatus.running)
        await stream.add_event("r1", make_event("r1", "a"))

        received: list = []
        done = asyncio.Event()

        async def consume():
            async for idx, _sse in stream.tail("r1"):
                received.append(idx)
            done.set()

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.2)

        # Simulate the watchdog flipping the status with no sentinel written
        await stream.set_run_status("r1", RunStatus.error)

        await asyncio.wait_for(done.wait(), timeout=5)
        assert received == [0]
        await consumer

    @pytest.mark.asyncio
    async def test_concurrent_tails_both_receive_all_events(self, stream: RedisEventStream):
        await stream.register_run("r1", RunStatus.running)

        async def consume():
            return [idx async for idx, _sse in stream.tail("r1")]

        t1 = asyncio.create_task(consume())
        t2 = asyncio.create_task(consume())
        await asyncio.sleep(0.2)

        await stream.add_event("r1", make_event("r1", "a"))
        await stream.add_event("r1", make_event("r1", "b"))
        await asyncio.sleep(0.2)
        await stream.complete_run("r1", RunStatus.completed)

        r1, r2 = await asyncio.wait_for(asyncio.gather(t1, t2), timeout=5)
        assert r1 == [0, 1]
        assert r2 == [0, 1]


class TestTtlRefresh:
    @pytest.mark.asyncio
    async def test_ttl_refreshed_on_time_basis_not_index(self, stream: RedisEventStream):
        """A slow producer (long gaps, index never hits a modulo boundary)
        must still get TTL refreshes: the refresh is time-based."""
        await stream.register_run("r1")
        await stream.add_event("r1", make_event("r1", "a"))  # first event: refresh due

        # Age the bookkeeping so the next event is past the refresh window
        stream._last_ttl_refresh["r1"] -= stream._ttl
        await stream.add_event("r1", make_event("r1", "b"))  # index 1: would NOT hit %20

        ttl = await stream._redis.ttl(stream._stream_key("r1"))
        assert ttl > 0, "stream key must carry a TTL refreshed by the second event"
        counter_ttl = await stream._redis.ttl(stream._counter_key("r1"))
        assert counter_ttl > 0

    @pytest.mark.asyncio
    async def test_no_refresh_inside_window(self, stream: RedisEventStream):
        await stream.register_run("r1")
        await stream.add_event("r1", make_event("r1", "a"))
        before = stream._last_ttl_refresh["r1"]
        await stream.add_event("r1", make_event("r1", "b"))  # inside window: no refresh
        assert stream._last_ttl_refresh["r1"] == before

    @pytest.mark.asyncio
    async def test_cleanup_drops_refresh_bookkeeping(self, stream: RedisEventStream):
        await stream.register_run("r1")
        await stream.add_event("r1", make_event("r1", "a"))
        await stream.cleanup_run("r1")
        assert "r1" not in stream._last_ttl_refresh


class TestQuietRunRefresher:
    @pytest.mark.asyncio
    async def test_quiet_active_run_keys_stay_alive(self):
        """A run producing NO events (long tool call) must keep its keys alive:
        the periodic refresher covers silence, not just slow event gaps."""
        s = RedisEventStream(fakeredis.FakeAsyncRedis(), ttl_seconds=2, block_ms=100)
        try:
            await s.register_run("r1")
            await s.add_event("r1", make_event("r1", "a"))
            # Sit silent past a full refresh interval (ttl/3 clamped to 1s min)
            await asyncio.sleep(1.3)
            assert await s._redis.ttl(s._status_key("r1")) > 0
            assert await s._redis.ttl(s._stream_key("r1")) > 0
            assert await s._redis.ttl(s._counter_key("r1")) > 0
        finally:
            await s.aclose()

    @pytest.mark.asyncio
    async def test_refresher_exits_when_no_active_runs(self):
        s = RedisEventStream(fakeredis.FakeAsyncRedis(), ttl_seconds=2, block_ms=100)
        try:
            await s.register_run("r1")
            # Accept-side registration must NOT start a refresher (only the
            # producing replica keeps keys alive)
            assert s._refresher_task is None or s._refresher_task.done()
            await s.set_run_status("r1", RunStatus.running)
            assert s._refresher_task is not None and not s._refresher_task.done()
            await s.complete_run("r1", RunStatus.completed)
            await asyncio.sleep(1.3)  # one tick with an empty active set
            assert s._refresher_task.done()
        finally:
            await s.aclose()


class TestPausedRefresherEviction:
    @pytest.mark.asyncio
    async def test_refresher_evicts_paused_run_finished_elsewhere(self):
        """complete_run(paused) enrolls the PAUSING replica in the refresher.
        When the continue lands on ANOTHER replica and finishes the run, this
        replica must notice the terminal status on its tick and evict - or
        the keys are refreshed forever and _active_runs grows without bound."""
        s = RedisEventStream(fakeredis.FakeAsyncRedis(), ttl_seconds=2, block_ms=100)
        try:
            await s.register_run("r1")
            await s.set_run_status("r1", RunStatus.running)
            await s.complete_run("r1", RunStatus.paused)
            assert "r1" in s._active_runs, "pausing replica keeps paused keys alive"

            # The continue executes ELSEWHERE: that replica writes the terminal
            # status straight into Redis (this process's stream object is not
            # involved)
            await s._redis.set(s._status_key("r1"), RunStatus.completed.value)

            await asyncio.sleep(1.3)  # one refresher tick
            assert "r1" not in s._active_runs, "refresher must evict a run that finished elsewhere"
        finally:
            await s.aclose()

    @pytest.mark.asyncio
    async def test_refresher_evicts_run_with_expired_keys(self):
        """A status key that vanished (TTL expiry / cleanup elsewhere) leaves
        nothing to keep alive: evict rather than refresh dead keys forever."""
        s = RedisEventStream(fakeredis.FakeAsyncRedis(), ttl_seconds=2, block_ms=100)
        try:
            await s.register_run("r1")
            await s.set_run_status("r1", RunStatus.running)
            await s.complete_run("r1", RunStatus.paused)
            await s._redis.delete(s._status_key("r1"), s._stream_key("r1"), s._counter_key("r1"))

            await asyncio.sleep(1.3)
            assert "r1" not in s._active_runs
        finally:
            await s.aclose()

    @pytest.mark.asyncio
    async def test_refresher_keeps_paused_run_alive(self):
        """The eviction check must not break the paused contract: a run still
        PAUSED keeps its keys refreshed until the approval arrives."""
        s = RedisEventStream(fakeredis.FakeAsyncRedis(), ttl_seconds=2, block_ms=100)
        try:
            await s.register_run("r1")
            await s.set_run_status("r1", RunStatus.running)
            await s.add_event("r1", make_event("r1", "a"))
            await s.complete_run("r1", RunStatus.paused)

            await asyncio.sleep(1.3)
            assert "r1" in s._active_runs
            assert await s._redis.ttl(s._status_key("r1")) > 0
            assert await s._redis.ttl(s._counter_key("r1")) > 0
        finally:
            await s.aclose()


class TestEventCountParity:
    @pytest.mark.asyncio
    async def test_completed_run_count_excludes_sentinel(self, stream):
        """Redis XLEN counts the terminal sentinel entry; the client-facing
        count must not (parity with the in-memory implementation)."""
        await stream.add_event("r1", make_event("r1", "a"))
        await stream.add_event("r1", make_event("r1", "b"))
        assert await stream.get_event_count("r1") == 2
        await stream.complete_run("r1", RunStatus.completed)
        assert await stream.get_event_count("r1") == 2


class TestTailResilience:
    @pytest.mark.asyncio
    async def test_tail_survives_client_socket_timeout(self):
        """A client-level socket timeout below block_ms (redis-py >= 8 defaults
        Redis(...) to 5s) must be treated as an idle pass, not kill the tail."""
        from redis.exceptions import TimeoutError as RedisTimeoutError

        s = RedisEventStream(fakeredis.FakeAsyncRedis(), block_ms=100)
        await s.register_run("r1", RunStatus.running)

        real_xread = s._redis.xread
        fail_once = {"n": 2}

        async def flaky_xread(*args, **kwargs):
            if fail_once["n"] > 0:
                fail_once["n"] -= 1
                raise RedisTimeoutError("socket timeout")
            return await real_xread(*args, **kwargs)

        s._redis.xread = flaky_xread
        try:
            received = []

            async def consume():
                async for idx, _sse in s.tail("r1"):
                    received.append(idx)

            task = asyncio.create_task(consume())
            await asyncio.sleep(0.3)  # survive the two injected timeouts
            await s.add_event("r1", make_event("r1", "a"))
            await asyncio.sleep(0.3)
            await s.complete_run("r1", RunStatus.completed)
            await asyncio.wait_for(task, timeout=5)
            assert received == [0]
        finally:
            await s.aclose()

    @pytest.mark.asyncio
    async def test_stale_paused_sentinel_does_not_end_resumed_tail(self, stream):
        """A HITL pause writes a sentinel; the continue appends behind it. A
        tail attached after the continue must skip the stale sentinel and keep
        streaming, ending only at the run's actual terminal state."""
        await stream.register_run("r1", RunStatus.running)
        await stream.add_event("r1", make_event("r1", "before-pause"))
        await stream.complete_run("r1", RunStatus.paused)

        # Continue: status back to running, more events behind the sentinel
        await stream.set_run_status("r1", RunStatus.running)
        await stream.add_event("r1", make_event("r1", "after-approval"))
        await stream.complete_run("r1", RunStatus.completed)

        received = [idx async for idx, _sse in stream.tail("r1")]
        assert received == [0, 1], "post-approval events must not be lost to the stale sentinel"

    @pytest.mark.asyncio
    async def test_reopened_tail_stays_open_before_first_leg_event(self, stream):
        """Review-round-2 P1: after a continue is accepted, the PAUSED
        sentinel is still the LAST stream entry until the leg's first event.
        A tail started in that window must stay open (reopen_run appends a
        sentinel-invalidating marker), not close empty."""
        await stream.register_run("r1", RunStatus.running)
        await stream.add_event("r1", make_event("r1", "before-pause"))
        await stream.complete_run("r1", RunStatus.paused)

        assert await stream.reopen_run("r1") is True
        assert await stream.get_run_status("r1") == RunStatus.pending

        received = []

        async def consume():
            async for idx, _sse in stream.tail("r1"):
                received.append(idx)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.3)  # past the replay + one XREAD block window
        assert not task.done(), "tail must wait for the continuation, not end on the stale pause sentinel"
        await stream.add_event("r1", make_event("r1", "after-approval"))
        await asyncio.sleep(0.2)
        await stream.complete_run("r1", RunStatus.completed)
        await asyncio.wait_for(task, timeout=5)
        assert received == [0, 1]

    @pytest.mark.asyncio
    async def test_reopen_declines_on_terminal_status(self, stream):
        """A racing worker may finish the whole leg before the reopen runs:
        the CAS must decline and never overwrite the terminal status."""
        await stream.register_run("r1", RunStatus.running)
        await stream.complete_run("r1", RunStatus.completed)
        assert await stream.reopen_run("r1") is False
        assert await stream.get_run_status("r1") == RunStatus.completed

    @pytest.mark.asyncio
    async def test_worker_redrive_reopens_from_error_but_never_completed(self, stream):
        """include_error is the claim-holding worker's redrive variant: a
        requeued continuation leg must re-liven the failed leg's ERROR view
        (continuations never reset the stream, so the ERROR sentinel would
        close early tails) - but COMPLETED stays untouchable either way."""
        await stream.register_run("r1", RunStatus.running)
        await stream.complete_run("r1", RunStatus.error)
        assert await stream.reopen_run("r1") is False, "seam-side reopen must not resurrect an errored stream"
        assert await stream.reopen_run("r1", include_error=True) is True
        assert await stream.get_run_status("r1") == RunStatus.pending

        await stream.complete_run("r1", RunStatus.completed)
        assert await stream.reopen_run("r1", include_error=True) is False
        assert await stream.get_run_status("r1") == RunStatus.completed

    @pytest.mark.asyncio
    async def test_reopen_marker_invisible_to_replay_and_index(self, stream):
        await stream.register_run("r1", RunStatus.running)
        await stream.add_event("r1", make_event("r1", "a"))
        await stream.complete_run("r1", RunStatus.paused)
        last_before = await stream.get_last_index("r1")
        assert await stream.reopen_run("r1")
        assert await stream.get_last_index("r1") == last_before, "markers must not consume indices"
        assert [idx for idx, _ in await stream.replay("r1")] == [0], "markers must not appear in replay"

    @pytest.mark.asyncio
    async def test_unknown_status_value_reads_as_running_not_missing(self, stream):
        await stream.register_run("r1", RunStatus.running)
        await stream._redis.set(stream._status_key("r1"), "SOME_FUTURE_STATUS")
        assert await stream.get_run_status("r1") == RunStatus.running

    @pytest.mark.asyncio
    async def test_paused_run_stays_on_ttl_refresher(self, stream):
        await stream.register_run("r1", RunStatus.running)
        await stream.add_event("r1", make_event("r1", "a"))
        await stream.complete_run("r1", RunStatus.paused)
        assert "r1" in stream._active_runs, "paused runs must keep their keys refreshed until the approval"
        await stream.complete_run("r1", RunStatus.completed)
        assert "r1" not in stream._active_runs

    @pytest.mark.asyncio
    async def test_refresher_drops_run_finished_on_another_replica(self):
        """Review-round-2 P2: the replica that parked a run as PAUSED keeps
        refreshing its keys, but the continuation may finish on ANOTHER
        replica. The Redis status is the shared truth: once it is terminal,
        the parker's refresher must drop the run so the TTL can reap the
        keys instead of renewing them forever."""
        s = RedisEventStream(fakeredis.FakeAsyncRedis(), ttl_seconds=2, block_ms=100)
        try:
            await s.register_run("r1", RunStatus.running)
            await s.add_event("r1", make_event("r1", "a"))
            await s.complete_run("r1", RunStatus.paused)
            assert "r1" in s._active_runs

            # Another replica's worker executes the continuation and finishes:
            # only the SHARED status key changes; this process is not told
            await s._redis.set(s._status_key("r1"), RunStatus.completed.value)

            await asyncio.sleep(1.3)  # one refresher tick
            assert "r1" not in s._active_runs, "refresher must drop runs whose shared status moved to terminal"
        finally:
            await s.aclose()

    @pytest.mark.asyncio
    async def test_refresher_keeps_reopened_run_alive(self):
        """The reopened (PENDING, awaiting claim) phase is exactly what the
        parker's refresher exists for - it must NOT drop those."""
        s = RedisEventStream(fakeredis.FakeAsyncRedis(), ttl_seconds=2, block_ms=100)
        try:
            await s.register_run("r1", RunStatus.running)
            await s.add_event("r1", make_event("r1", "a"))
            await s.complete_run("r1", RunStatus.paused)
            assert await s.reopen_run("r1")
            await asyncio.sleep(1.3)  # one refresher tick
            assert "r1" in s._active_runs
            assert await s._redis.ttl(s._status_key("r1")) > 0
        finally:
            await s.aclose()


class TestProducerOwnedRefresher:
    @pytest.mark.asyncio
    async def test_accept_side_register_does_not_enroll(self, stream):
        """An accepting replica registers PENDING for a job some other replica
        will execute: it must not become a key-refresher for that run (it
        would renew a finished run's keys forever)."""
        await stream.register_run("r1", RunStatus.pending)
        assert "r1" not in stream._active_runs

    @pytest.mark.asyncio
    async def test_running_transition_enrolls_producer(self, stream):
        await stream.register_run("r1", RunStatus.pending)
        await stream.set_run_status("r1", RunStatus.running)
        assert "r1" in stream._active_runs
        await stream.complete_run("r1", RunStatus.completed)
        assert "r1" not in stream._active_runs

    @pytest.mark.asyncio
    async def test_add_event_enrolls_publisher(self, stream):
        await stream.register_run("r1", RunStatus.running)
        assert "r1" not in stream._active_runs
        await stream.add_event("r1", make_event("r1", "a"))
        assert "r1" in stream._active_runs


class TestRetryIndexContinuity:
    @pytest.mark.asyncio
    async def test_reset_preserves_index_counter(self, stream):
        await stream.register_run("r1", RunStatus.running)
        for c in ("a", "b", "c"):
            await stream.add_event("r1", make_event("r1", c))
        await stream.reset_run_events("r1")
        assert await stream.get_event_count("r1") == 0
        # Retry attempt continues the monotonic index sequence
        idx = await stream.add_event("r1", make_event("r1", "retry"))
        assert idx == 3, "indices must not rewind across attempts"
        assert await stream.get_run_status("r1") == RunStatus.running

    @pytest.mark.asyncio
    async def test_reconnecting_client_sees_retry_events(self, stream):
        """A client that saw indices 0..2 on attempt 1 and reconnects with
        last_event_index=2 must receive attempt 2's events."""
        await stream.register_run("r1", RunStatus.running)
        for c in ("a", "b", "c"):
            await stream.add_event("r1", make_event("r1", c))
        await stream.reset_run_events("r1")
        await stream.add_event("r1", make_event("r1", "real-1"))
        await stream.add_event("r1", make_event("r1", "real-2"))
        await stream.complete_run("r1", RunStatus.completed)
        received = [idx async for idx, _sse in stream.tail("r1", last_event_index=2)]
        assert received == [3, 4], "retry output must not be filtered by the old client index"


class TestCancellationFailOpen:
    """A Redis fault during the cancellation check must never poison the run
    (the check re-fires at the next safe point)."""

    @pytest.mark.asyncio
    async def test_redis_fault_fails_open(self):
        from agno.run.cancellation_management.redis_cancellation_manager import RedisRunCancellationManager

        class BoomClient:
            def get(self, key):
                raise ConnectionError("redis down")

        class ABoomClient:
            async def get(self, key):
                raise ConnectionError("redis down")

        mgr = RedisRunCancellationManager(redis_client=BoomClient(), async_redis_client=ABoomClient())
        assert mgr.is_cancelled("r1") is False
        assert await mgr.ais_cancelled("r1") is False


class TestDeadProducerGate:
    @pytest.mark.asyncio
    async def test_pending_run_with_decayed_ttl_keeps_tail_alive(self):
        """F4: a long-queued (PENDING) run has no producer by design - TTL
        decay must not be read as producer death."""
        s = RedisEventStream(fakeredis.FakeAsyncRedis(), ttl_seconds=30, block_ms=50)
        try:
            await s.register_run("dp1", RunStatus.pending)
            # Decay the status key TTL into the dead-producer window (below
            # ttl//3 = 10) but well above actual expiry, so only the heuristic
            # - not real key death - could end the tail
            await s._redis.expire(s._status_key("dp1"), 5)
            agen = s.tail("dp1")
            task = asyncio.create_task(agen.__anext__())
            done, _ = await asyncio.wait([task], timeout=1.5)
            assert not done, "PENDING tail must keep waiting, not die on TTL decay"
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
        finally:
            await s.aclose()


class TestEventCountExcludesMarkers:
    """Coordination markers - pause/terminal sentinels and
    reopen markers, including stale mid-stream ones - are stream entries but
    not client-facing events. The old XLEN-minus-trailing-sentinel count
    inflated by 2+ per pause/continue cycle; anything consuming the count for
    progress got fictional numbers."""

    @pytest.mark.asyncio
    async def test_pause_reopen_continue_cycle_counts_real_events_only(self, stream: RedisEventStream):
        await stream.register_run("r1", RunStatus.running)
        await stream.add_event("r1", make_event("r1", "a"))
        await stream.add_event("r1", make_event("r1", "b"))
        await stream.complete_run("r1", RunStatus.paused)  # sentinel entry
        await stream.reopen_run("r1")  # reopen marker entry
        await stream.add_event("r1", make_event("r1", "c"))
        await stream.complete_run("r1", RunStatus.completed)  # terminal entry

        assert await stream.get_event_count("r1") == 3, (
            "count must include only client-facing events, never pause/reopen/terminal markers"
        )

    @pytest.mark.asyncio
    async def test_two_pause_cycles_stay_accurate(self, stream: RedisEventStream):
        await stream.register_run("r1", RunStatus.running)
        for cycle in range(2):
            await stream.add_event("r1", make_event("r1", f"e{cycle}"))
            await stream.complete_run("r1", RunStatus.paused)
            await stream.reopen_run("r1")
        assert await stream.get_event_count("r1") == 2


class TestBatchBoundarySentinel:
    """XREAD reads count-bounded batches (100), and the old
    tail honored a sentinel that was merely BATCH-final - a lagging consumer
    whose batch happened to end exactly on a stale pause sentinel was closed
    even though the reopen marker and continuation events sat in the very
    next batch. Tail-side read bug: item 5's producer generation fencing
    would not have fixed it."""

    @pytest.mark.asyncio
    async def test_lagging_tail_survives_sentinel_at_exact_batch_boundary(self, stream: RedisEventStream):
        await stream.register_run("r1", RunStatus.running)

        # One-shot filler: bulk-load the stream between the tail's replay
        # phase (empty stream) and its first XREAD, so the first live batch
        # holds exactly 100 entries - 99 events + the pause sentinel as the
        # batch-final entry - with the reopen marker and the continuation
        # event stranded in batch two.
        orig_xread = stream._redis.xread
        filled = {}

        async def fill_then_read(streams, block=None, count=None):
            if not filled:
                filled["done"] = True
                for i in range(99):
                    await stream.add_event("r1", make_event("r1", f"e{i}"))
                await stream.complete_run("r1", RunStatus.paused)
                await stream.reopen_run("r1")
                await stream.add_event("r1", make_event("r1", "after-approval"))
            return await orig_xread(streams, block=block, count=count)

        stream._redis.xread = fill_then_read

        received: list = []
        done = asyncio.Event()

        async def consume():
            async for idx, _sse in stream.tail("r1"):
                received.append(idx)
            done.set()

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.5)

        assert not done.is_set(), (
            f"tail closed on the batch-final stale sentinel with {len(received)} events - "
            "the continuation behind the batch boundary was never delivered"
        )
        assert received == list(range(100)), f"expected all 100 events including the continuation, got {len(received)}"

        await stream.complete_run("r1", RunStatus.completed)
        await asyncio.wait_for(done.wait(), timeout=5)
        await consumer


class TestReopenSeedsCounterFromFloor:
    """A paused run outliving the TTL (HITL across a
    deploy) loses its counter; reopen_run accepted the missing state and
    INCR restarted indices at 0 - resuming clients, which dedup by index,
    silently discarded every post-approval event."""

    @pytest.mark.asyncio
    async def test_reopen_after_key_loss_seeds_next_index(self, stream: RedisEventStream):
        await stream.register_run("r1", RunStatus.running)
        for content in ("a", "b", "c"):
            await stream.add_event("r1", make_event("r1", content))  # indices 0..2
        await stream.complete_run("r1", RunStatus.paused)
        await stream.cleanup_run("r1")  # deterministic stand-in for TTL expiry

        assert await stream.reopen_run("r1", floor=2) is True
        idx = await stream.add_event("r1", make_event("r1", "after-approval"))
        assert idx == 3, (
            f"post-expiry continuation must continue at floor+1, got {idx} - "
            "index 0 is deduped away by clients holding the pause-event index"
        )

    @pytest.mark.asyncio
    async def test_live_counter_never_regressed(self, stream: RedisEventStream):
        await stream.register_run("r1", RunStatus.running)
        for content in ("a", "b", "c", "d", "e"):
            await stream.add_event("r1", make_event("r1", content))  # counter = 5
        await stream.complete_run("r1", RunStatus.paused)

        assert await stream.reopen_run("r1", floor=2) is True  # stale floor
        idx = await stream.add_event("r1", make_event("r1", "next"))
        assert idx == 5, f"a live counter must win over a stale floor, got {idx}"

    @pytest.mark.asyncio
    async def test_true_ttl_expiry_reseeds(self):
        """Real-clock expiry: 1s TTL, keys genuinely expire, reopen with the
        durable floor continues the numbering."""
        import asyncio

        short = RedisEventStream(fakeredis.FakeAsyncRedis(), ttl_seconds=1, block_ms=100)
        try:
            await short.register_run("r1", RunStatus.running)
            await short.add_event("r1", make_event("r1", "a"))
            await short.add_event("r1", make_event("r1", "b"))
            await short.complete_run("r1", RunStatus.paused)
            await asyncio.sleep(1.2)
            assert await short.get_last_index("r1") == -1, "keys should have expired"

            assert await short.reopen_run("r1", floor=1) is True
            idx = await short.add_event("r1", make_event("r1", "after"))
            assert idx == 2
        finally:
            await short.aclose()


class TestClusterRejection:
    """The stream's per-run keys are not hash-tagged, so its
    WATCH/MULTI and multi-key pipelines are cross-slot - reject cluster
    clients at construction like the job-queue store does, instead of
    failing confusingly at runtime mid-continuation. The cancellation
    manager deliberately stays cluster-tolerant (all pipelines single-key,
    audited; cluster support advertised there)."""

    def test_cluster_client_rejected_at_construction(self):
        cluster_client = type("RedisCluster", (), {})()
        with pytest.raises(ValueError, match="standalone"):
            RedisEventStream(cluster_client)

    def test_standalone_client_accepted(self):
        stream = RedisEventStream(fakeredis.FakeAsyncRedis(), block_ms=100)
        assert stream is not None


class TestIdleProbeResilience:
    """The status probe on the idle path was the one
    unguarded call in the tail loop - a Redis blip there escaped the loop
    (client sees an error close) instead of riding through like the same
    outage one line earlier at the XREAD. And when a connection fails FAST,
    block_ms never paces the loop, so the shared-counter backoff is what
    keeps an outage from becoming a busy loop."""

    @pytest.mark.asyncio
    async def test_probe_blip_does_not_kill_the_tail(self, stream: RedisEventStream):
        await stream.register_run("r1", RunStatus.running)
        await stream.add_event("r1", make_event("r1", "a"))

        real_get = stream._redis.get
        blips = {"left": 2}

        async def blipping_get(key):
            if blips["left"] > 0:
                blips["left"] -= 1
                from redis.exceptions import ConnectionError as RedisConnectionError

                raise RedisConnectionError("blip")
            return await real_get(key)

        stream._redis.get = blipping_get

        received: list = []
        done = asyncio.Event()

        async def consume():
            async for idx, _sse in stream.tail("r1"):
                received.append(idx)
            done.set()

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.8)  # several idle passes hit the blipping probe
        assert not done.is_set(), "a transient probe failure must not close the tail"

        await stream.add_event("r1", make_event("r1", "b"))
        await asyncio.sleep(0.3)
        await stream.complete_run("r1", RunStatus.completed)
        await asyncio.wait_for(done.wait(), timeout=5)
        assert received == [0, 1], f"the tail must survive the blip and deliver later events, got {received}"
        await consumer

    @pytest.mark.asyncio
    async def test_full_outage_is_paced_not_busy_looped(self, stream: RedisEventStream):
        from redis.exceptions import ConnectionError as RedisConnectionError

        await stream.register_run("r1", RunStatus.running)
        calls = {"xread": 0}

        async def dead_xread(*args, **kwargs):
            calls["xread"] += 1
            raise RedisConnectionError("redis down")

        async def dead_get(*args, **kwargs):
            raise RedisConnectionError("redis down")

        stream._redis.xread = dead_xread
        stream._redis.get = dead_get

        async def consume():
            async for _ in stream.tail("r1"):
                pass

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(1.0)
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        assert calls["xread"] <= 12, (
            f"{calls['xread']} XREAD attempts in 1s of full outage - the fast-failing connection "
            "bypassed block_ms pacing and the loop is spinning hot"
        )
