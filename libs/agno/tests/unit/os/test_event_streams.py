"""Unit tests for the pluggable event stream (in-memory implementation)."""

import asyncio

import pytest

from agno.os.event_streams import InMemoryEventStream, get_event_stream, set_event_stream
from agno.os.managers import EventsBuffer, SSESubscriberManager
from agno.run.agent import RunContentEvent
from agno.run.base import RunStatus


@pytest.fixture()
def stream() -> InMemoryEventStream:
    # Isolated buffer/manager per test — do not touch the module singletons
    return InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())


def make_event(run_id: str, content: str) -> RunContentEvent:
    return RunContentEvent(content=content, run_id=run_id)


class TestGlobalAccessor:
    def test_defaults_to_in_memory(self):
        import agno.os.event_streams as mod

        original = mod._event_stream
        mod._event_stream = None
        try:
            assert isinstance(get_event_stream(), InMemoryEventStream)
        finally:
            mod._event_stream = original

    def test_set_event_stream_swaps_instance(self):
        import agno.os.event_streams as mod

        original = mod._event_stream
        replacement = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        try:
            set_event_stream(replacement)
            assert get_event_stream() is replacement
        finally:
            mod._event_stream = original


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_register_and_status_transitions(self, stream: InMemoryEventStream):
        await stream.register_run("r1", RunStatus.pending)
        assert await stream.get_run_status("r1") == RunStatus.pending

        await stream.set_run_status("r1", RunStatus.running)
        assert await stream.get_run_status("r1") == RunStatus.running

        await stream.complete_run("r1", RunStatus.completed)
        assert await stream.get_run_status("r1") == RunStatus.completed

    @pytest.mark.asyncio
    async def test_register_is_idempotent(self, stream: InMemoryEventStream):
        await stream.register_run("r1", RunStatus.pending)
        await stream.set_run_status("r1", RunStatus.running)
        await stream.register_run("r1", RunStatus.pending)  # must not reset
        assert await stream.get_run_status("r1") == RunStatus.running

    @pytest.mark.asyncio
    async def test_unknown_run_status_is_none(self, stream: InMemoryEventStream):
        assert await stream.get_run_status("nope") is None

    @pytest.mark.asyncio
    async def test_cleanup_removes_state(self, stream: InMemoryEventStream):
        await stream.register_run("r1")
        await stream.add_event("r1", make_event("r1", "a"))
        await stream.cleanup_run("r1")
        assert await stream.get_run_status("r1") is None
        assert await stream.get_event_count("r1") == 0


class TestEvents:
    @pytest.mark.asyncio
    async def test_add_event_returns_monotonic_indices(self, stream: InMemoryEventStream):
        assert await stream.add_event("r1", make_event("r1", "a")) == 0
        assert await stream.add_event("r1", make_event("r1", "b")) == 1
        assert await stream.get_last_index("r1") == 1
        assert await stream.get_event_count("r1") == 2

    @pytest.mark.asyncio
    async def test_replay_from_index(self, stream: InMemoryEventStream):
        for content in ("a", "b", "c"):
            await stream.add_event("r1", make_event("r1", content))

        all_events = await stream.replay("r1")
        assert [idx for idx, _ in all_events] == [0, 1, 2]

        after_zero = await stream.replay("r1", last_event_index=0)
        assert [idx for idx, _ in after_zero] == [1, 2]

        caught_up = await stream.replay("r1", last_event_index=2)
        assert caught_up == []


class TestTail:
    @pytest.mark.asyncio
    async def test_tail_replays_then_streams_live_without_dups(self, stream: InMemoryEventStream):
        """Events added before tailing are replayed; events added during
        tailing arrive live; nothing is duplicated."""
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
        await asyncio.sleep(0.05)  # replay of [0, 1] happens, then live wait

        await stream.add_event("r1", make_event("r1", "c"))
        await asyncio.sleep(0.05)
        await stream.complete_run("r1", RunStatus.completed)

        await asyncio.wait_for(done.wait(), timeout=2)
        assert received == [0, 1, 2]
        await consumer

    @pytest.mark.asyncio
    async def test_tail_resumes_after_last_event_index(self, stream: InMemoryEventStream):
        await stream.register_run("r1", RunStatus.running)
        for content in ("a", "b", "c"):
            await stream.add_event("r1", make_event("r1", content))
        await stream.complete_run("r1", RunStatus.completed)

        received = [idx async for idx, _sse in stream.tail("r1", last_event_index=0)]
        assert received == [1, 2]

    @pytest.mark.asyncio
    async def test_tail_of_completed_run_terminates(self, stream: InMemoryEventStream):
        """Completion published before subscription must not hang the tail
        (the sentinel was pushed before our queue existed)."""
        await stream.register_run("r1", RunStatus.running)
        await stream.add_event("r1", make_event("r1", "a"))
        await stream.complete_run("r1", RunStatus.completed)

        received = [idx async for idx, _sse in stream.tail("r1")]
        assert received == [0]

    @pytest.mark.asyncio
    async def test_tail_ends_when_run_completes_with_no_events(self, stream: InMemoryEventStream):
        await stream.register_run("r1", RunStatus.running)

        done = asyncio.Event()
        received: list = []

        async def consume():
            async for idx, _sse in stream.tail("r1"):
                received.append(idx)
            done.set()

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        await stream.complete_run("r1", RunStatus.cancelled)

        await asyncio.wait_for(done.wait(), timeout=2)
        assert received == []
        await consumer

    @pytest.mark.asyncio
    async def test_concurrent_tails_both_receive_all_events(self, stream: InMemoryEventStream):
        await stream.register_run("r1", RunStatus.running)

        async def consume():
            return [idx async for idx, _sse in stream.tail("r1")]

        t1 = asyncio.create_task(consume())
        t2 = asyncio.create_task(consume())
        await asyncio.sleep(0.05)

        await stream.add_event("r1", make_event("r1", "a"))
        await stream.add_event("r1", make_event("r1", "b"))
        await asyncio.sleep(0.05)
        await stream.complete_run("r1", RunStatus.completed)

        r1, r2 = await asyncio.wait_for(asyncio.gather(t1, t2), timeout=2)
        assert r1 == [0, 1]
        assert r2 == [0, 1]


class TestInMemoryRetryIndexContinuity:
    @pytest.mark.asyncio
    async def test_reset_preserves_index_counter(self):
        import agno.os.event_streams as es_mod
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.managers import EventsBuffer, SSESubscriberManager
        from agno.run.agent import RunContentEvent
        from agno.run.base import RunStatus

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:
            await stream.register_run("r1", RunStatus.running)
            for c in ("a", "b", "c"):
                await stream.add_event("r1", RunContentEvent(content=c, run_id="r1"))
            await stream.reset_run_events("r1")
            assert await stream.get_event_count("r1") == 0
            idx = await stream.add_event("r1", RunContentEvent(content="retry", run_id="r1"))
            assert idx == 3, "indices must not rewind across attempts"
        finally:
            es_mod._event_stream = original


class TestReopenSeedsCounterFromFloor:
    """In-memory twin of the Redis floor-seeding tests: after a process restart the buffer
    comes up empty under a paused run's continue - the seeded floor keeps
    indices monotonic for resuming clients."""

    @pytest.mark.asyncio
    async def test_reopen_on_fresh_buffer_seeds_next_index(self):
        from agno.os.event_streams.in_memory import InMemoryEventStream
        from agno.os.managers import EventsBuffer, SSESubscriberManager
        from agno.run.base import RunStatus

        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        # Fresh buffer (post-restart): register PAUSED as the pre-continue
        # state, then reopen with the durable floor
        await stream.register_run("r1", RunStatus.paused)
        assert await stream.reopen_run("r1", floor=4) is True
        from agno.run.agent import RunContentEvent

        idx = await stream.add_event("r1", RunContentEvent(content="after", run_id="r1"))
        assert idx == 5, f"post-restart continuation must continue at floor+1, got {idx}"

    @pytest.mark.asyncio
    async def test_live_counter_never_regressed(self):
        from agno.os.event_streams.in_memory import InMemoryEventStream
        from agno.os.managers import EventsBuffer, SSESubscriberManager
        from agno.run.agent import RunContentEvent
        from agno.run.base import RunStatus

        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        await stream.register_run("r1", RunStatus.running)
        for c in ("a", "b", "c"):
            await stream.add_event("r1", RunContentEvent(content=c, run_id="r1"))
        await stream.complete_run("r1", RunStatus.paused)
        assert await stream.reopen_run("r1", floor=0) is True
        idx = await stream.add_event("r1", RunContentEvent(content="d", run_id="r1"))
        assert idx == 3
