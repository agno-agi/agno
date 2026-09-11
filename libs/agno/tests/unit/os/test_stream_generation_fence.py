"""Per-run stream writer generations.

``begin_attempt`` records the newest attempt as the stream's writer
generation (monotonic CAS); ``add_event(generation=...)`` from an older
generation is REFUSED - a zombie attempt's output can no longer interleave
into the live attempt's stream. Redis does the check atomically in Lua
(gen-check+INCR, gen-check+XADD); in-memory checks under the event loop; a
Redis server without scripting degrades fail-open to unfenced publishing
with a warning (the stream is coordination, not truth).
"""

import socket
import uuid

import pytest

from agno.run.agent import RunContentEvent
from agno.run.base import RunStatus


def make_event(run_id: str, content: str) -> RunContentEvent:
    return RunContentEvent(content=content, run_id=run_id)


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("localhost", port), timeout=2):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# In-memory backend
# ---------------------------------------------------------------------------


@pytest.fixture()
def mem_stream():
    from agno.os.event_streams import InMemoryEventStream
    from agno.os.managers import EventsBuffer, SSESubscriberManager

    return InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())


class TestInMemoryGenerationFence:
    @pytest.mark.asyncio
    async def test_stale_generation_is_refused(self, mem_stream):
        await mem_stream.register_run("r1", RunStatus.running)
        await mem_stream.begin_attempt("r1", 1)
        assert await mem_stream.add_event("r1", make_event("r1", "live-1"), generation=1) == 0

        await mem_stream.begin_attempt("r1", 2)  # the reclaim
        assert await mem_stream.add_event("r1", make_event("r1", "zombie"), generation=1) == -1, (
            "attempt 1's event landed after attempt 2 took the stream"
        )
        assert await mem_stream.add_event("r1", make_event("r1", "live-2"), generation=2) >= 0

        replayed = await mem_stream.replay("r1")
        contents = [getattr(e, "content", None) for _, e in replayed]
        assert "zombie" not in contents
        assert await mem_stream.get_event_count("r1") == 2

    @pytest.mark.asyncio
    async def test_old_begin_never_regresses(self, mem_stream):
        await mem_stream.begin_attempt("r1", 2)
        await mem_stream.begin_attempt("r1", 1)  # zombie's late begin
        assert await mem_stream.add_event("r1", make_event("r1", "z"), generation=1) == -1
        assert await mem_stream.add_event("r1", make_event("r1", "ok"), generation=2) >= 0

    @pytest.mark.asyncio
    async def test_unfenced_add_bypasses(self, mem_stream):
        """Inline single-writer producers pass no generation - legacy path."""
        await mem_stream.begin_attempt("r1", 5)
        assert await mem_stream.add_event("r1", make_event("r1", "inline")) == 0

    @pytest.mark.asyncio
    async def test_first_fenced_writer_establishes_generation(self, mem_stream):
        """No begin_attempt happened (e.g. process restart lost it): the
        first fenced add establishes the generation instead of refusing."""
        assert await mem_stream.add_event("r1", make_event("r1", "a"), generation=3) == 0
        assert await mem_stream.add_event("r1", make_event("r1", "b"), generation=2) == -1

    @pytest.mark.asyncio
    async def test_cleanup_clears_generation(self, mem_stream):
        await mem_stream.begin_attempt("r1", 9)
        await mem_stream.cleanup_run("r1")
        assert await mem_stream.add_event("r1", make_event("r1", "fresh"), generation=1) == 0


# ---------------------------------------------------------------------------
# Redis backend - Lua path on a real server
# ---------------------------------------------------------------------------

redis_required = pytest.mark.skipif(not _port_open(6379), reason="Redis not available on localhost:6379")


@redis_required
class TestRedisGenerationFence:
    @pytest.fixture()
    async def redis_stream(self):
        import redis.asyncio as aioredis

        from agno.os.event_streams.redis import RedisEventStream

        client = aioredis.Redis.from_url("redis://localhost:6379")
        stream = RedisEventStream(client, key_prefix=f"agno:test:fence:{uuid.uuid4().hex[:8]}:", block_ms=100)
        yield stream
        for rid in ("r1",):
            await stream.cleanup_run(rid)
        await stream.aclose()
        await client.aclose()

    @pytest.mark.asyncio
    async def test_stale_generation_is_refused_atomically(self, redis_stream):
        await redis_stream.register_run("r1", RunStatus.running)
        await redis_stream.begin_attempt("r1", 1)
        assert await redis_stream.add_event("r1", make_event("r1", "live-1"), generation=1) == 0

        await redis_stream.begin_attempt("r1", 2)
        assert await redis_stream.add_event("r1", make_event("r1", "zombie"), generation=1) == -1
        live_idx = await redis_stream.add_event("r1", make_event("r1", "live-2"), generation=2)
        assert live_idx >= 1

        replayed = await redis_stream.replay("r1")
        assert all("zombie" not in (sse or "") for _, sse in replayed), replayed
        assert await redis_stream.get_event_count("r1") == 2

    @pytest.mark.asyncio
    async def test_old_begin_never_regresses(self, redis_stream):
        await redis_stream.begin_attempt("r1", 2)
        await redis_stream.begin_attempt("r1", 1)
        assert await redis_stream.add_event("r1", make_event("r1", "z"), generation=1) == -1
        assert await redis_stream.add_event("r1", make_event("r1", "ok"), generation=2) >= 0

    @pytest.mark.asyncio
    async def test_unfenced_add_unchanged(self, redis_stream):
        await redis_stream.begin_attempt("r1", 5)
        assert await redis_stream.add_event("r1", make_event("r1", "inline")) == 0

    @pytest.mark.asyncio
    async def test_newer_writer_self_heals_generation(self, redis_stream):
        """A fenced add from a NEWER generation than stored (its begin was
        lost) updates the stored generation and lands."""
        await redis_stream.begin_attempt("r1", 1)
        assert await redis_stream.add_event("r1", make_event("r1", "new"), generation=4) == 0
        assert await redis_stream.add_event("r1", make_event("r1", "old"), generation=1) == -1


# ---------------------------------------------------------------------------
# Degradation: a server without scripting fails OPEN
# ---------------------------------------------------------------------------


class TestScriptingUnavailableDegradation:
    @pytest.mark.asyncio
    async def test_fenced_add_publishes_unfenced_on_fakeredis(self):
        fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")
        from agno.os.event_streams.redis import RedisEventStream

        stream = RedisEventStream(fakeredis.FakeAsyncRedis(), block_ms=100)
        try:
            await stream.register_run("r1", RunStatus.running)
            # fakeredis has no EVAL: the fence must degrade to publishing
            # unfenced (fail-open), never to dropping the event
            idx = await stream.add_event("r1", make_event("r1", "a"), generation=1)
            assert idx == 0
            assert stream._scripting_unavailable is True
            # And it stays on the legacy path afterwards
            assert await stream.add_event("r1", make_event("r1", "b"), generation=99) == 1
        finally:
            await stream.aclose()


# ---------------------------------------------------------------------------
# Worker wiring: the attempt is the generation
# ---------------------------------------------------------------------------


class TestWorkerStampsGeneration:
    @pytest.mark.asyncio
    async def test_execute_streaming_takes_generation_and_fences_zombie(self):
        import agno.os.event_streams as es_mod
        from agno.job_queue.config import QueueConfig
        from agno.job_queue.store import InMemoryQueueStore
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.job_queue import QueueWorker
        from agno.os.managers import EventsBuffer, SSESubscriberManager

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:

            class FakeOutput:
                run_id = "sr1"
                status = RunStatus.completed

            class FakeAgent:
                id = "a1"
                db = None

                async def arun(self, **kwargs):
                    yield make_event("sr1", "live")
                    yield FakeOutput()

            worker = QueueWorker(
                store=InMemoryQueueStore(),
                resolve_component=lambda t, i: FakeAgent(),
                config=QueueConfig(durable=True),
            )
            job = {"id": "sr1", "attempt": 2, "session_id": "s1", "payload": {"input": "x", "stream": True}}
            await worker._execute_streaming(FakeAgent(), job)

            # The leg took generation 2; a zombie publish from attempt 1 is
            # refused while the leg's own event landed
            assert await stream.add_event("sr1", make_event("sr1", "zombie"), generation=1) == -1
            replayed = await stream.replay("sr1")
            contents = [getattr(e, "content", None) for _, e in replayed]
            assert contents == ["live"]
        finally:
            es_mod._event_stream = original


class TestInMemoryLifecycleFence:
    """The fence covers lifecycle mutations too: a zombie's terminal sentinel
    must not close the live attempt's tails, and a pre-entry-stalled zombie's
    reset must not delete the reclaim's events."""

    @pytest.mark.asyncio
    async def test_stale_complete_run_refused(self, mem_stream):
        await mem_stream.register_run("r1", RunStatus.running)
        await mem_stream.begin_attempt("r1", 2)
        await mem_stream.add_event("r1", make_event("r1", "b-1"), generation=2)
        await mem_stream.complete_run("r1", RunStatus.error, generation=1)  # zombie sentinel
        assert await mem_stream.get_run_status("r1") == RunStatus.running, (
            "the zombie's terminal write closed the live attempt's stream"
        )
        await mem_stream.complete_run("r1", RunStatus.completed, generation=2)
        assert await mem_stream.get_run_status("r1") == RunStatus.completed

    @pytest.mark.asyncio
    async def test_same_generation_complete_passes(self, mem_stream):
        """Finished-work-wins: a same-attempt late completion (worker falsely
        swept, then finishing) overwrites the sweeper's ERROR close."""
        await mem_stream.register_run("r1", RunStatus.running)
        await mem_stream.begin_attempt("r1", 1)
        await mem_stream.complete_run("r1", RunStatus.error, generation=1)  # the sweep
        await mem_stream.complete_run("r1", RunStatus.completed, generation=1)  # the "dead" worker finishing
        assert await mem_stream.get_run_status("r1") == RunStatus.completed

    @pytest.mark.asyncio
    async def test_stale_reset_refused(self, mem_stream):
        await mem_stream.register_run("r1", RunStatus.running)
        await mem_stream.begin_attempt("r1", 2)
        await mem_stream.add_event("r1", make_event("r1", "b-1"), generation=2)
        await mem_stream.reset_run_events("r1", generation=1)  # pre-entry-stalled zombie waking
        assert await mem_stream.get_event_count("r1") == 1, "the zombie's reset deleted the reclaim's events"

    @pytest.mark.asyncio
    async def test_stale_set_run_status_refused(self, mem_stream):
        await mem_stream.register_run("r1", RunStatus.running)
        await mem_stream.begin_attempt("r1", 2)
        await mem_stream.complete_run("r1", RunStatus.completed, generation=2)
        await mem_stream.set_run_status("r1", RunStatus.running, generation=1)  # zombie's leg entry
        assert await mem_stream.get_run_status("r1") == RunStatus.completed, (
            "the zombie's RUNNING flip re-opened a completed stream (tails would hang)"
        )


@redis_required
class TestRedisLifecycleFence:
    @pytest.fixture()
    async def redis_stream(self):
        import redis.asyncio as aioredis

        from agno.os.event_streams.redis import RedisEventStream

        client = aioredis.Redis.from_url("redis://localhost:6379")
        stream = RedisEventStream(client, key_prefix=f"agno:test:fence:{uuid.uuid4().hex[:8]}:", block_ms=100)
        yield stream
        await stream.cleanup_run("r1")
        await stream.aclose()
        await client.aclose()

    @pytest.mark.asyncio
    async def test_stale_complete_run_refused(self, redis_stream):
        await redis_stream.register_run("r1", RunStatus.running)
        await redis_stream.begin_attempt("r1", 2)
        await redis_stream.add_event("r1", make_event("r1", "b-1"), generation=2)
        await redis_stream.complete_run("r1", RunStatus.error, generation=1)
        assert await redis_stream.get_run_status("r1") == RunStatus.running

    @pytest.mark.asyncio
    async def test_same_generation_complete_passes(self, redis_stream):
        await redis_stream.register_run("r1", RunStatus.running)
        await redis_stream.begin_attempt("r1", 1)
        await redis_stream.complete_run("r1", RunStatus.error, generation=1)
        await redis_stream.complete_run("r1", RunStatus.completed, generation=1)
        assert await redis_stream.get_run_status("r1") == RunStatus.completed

    @pytest.mark.asyncio
    async def test_stale_reset_refused(self, redis_stream):
        await redis_stream.register_run("r1", RunStatus.running)
        await redis_stream.begin_attempt("r1", 2)
        await redis_stream.add_event("r1", make_event("r1", "b-1"), generation=2)
        await redis_stream.reset_run_events("r1", generation=1)
        assert await redis_stream.get_event_count("r1") == 1

    @pytest.mark.asyncio
    async def test_stale_set_run_status_refused(self, redis_stream):
        await redis_stream.register_run("r1", RunStatus.running)
        await redis_stream.begin_attempt("r1", 2)
        await redis_stream.complete_run("r1", RunStatus.completed, generation=2)
        await redis_stream.set_run_status("r1", RunStatus.running, generation=1)
        assert await redis_stream.get_run_status("r1") == RunStatus.completed
