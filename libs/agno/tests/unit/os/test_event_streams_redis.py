"""Unit tests for the Redis Streams event stream (via fakeredis)."""

import asyncio

import pytest

fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")

from agno.os.event_streams.redis import RedisEventStream  # noqa: E402
from agno.run.agent import RunContentEvent  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402


@pytest.fixture()
def stream() -> RedisEventStream:
    # Short block_ms keeps idle-recheck loops fast in tests
    return RedisEventStream(fakeredis.FakeAsyncRedis(), block_ms=100)


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
