"""The honest close.

A tail that ends because the stream state expired (run queued past the TTL,
or a dead producer) while the durable ticket still vouches for the run used
to close silently - indistinguishable from a finished stream, telling the
client a lie about a legitimately accepted run. The streamer now emits one
explicit ``stream_expired`` SSE event (a real event type - it must reach
client handlers; unknown types are ignored by standard consumers) and ends.
The ticket-consulting wrapper LOOP stays parked, evidence-gated.
"""

from types import SimpleNamespace

import pytest

from agno.db.schemas.jobs import QueuedJob
from agno.job_queue.store import InMemoryQueueStore

# Imported via the router module deliberately: the name exists there on
# both the fixed source (re-export of the shared implementation) and the
# unfixed source (the old local silent-close copy), so these tests fail
# BEHAVIORALLY on unfixed code instead of dying at collection.
from agno.os.routers.agents.router import queued_run_tail_streamer
from agno.run.base import RunStatus


@pytest.fixture()
def harness(monkeypatch):
    from agno.os.event_streams.in_memory import InMemoryEventStream
    from agno.os.job_queue import set_active_queue_worker
    from agno.os.managers import EventsBuffer, SSESubscriberManager

    stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    monkeypatch.setattr("agno.os.event_streams.get_event_stream", lambda: stream)
    # The in-memory tail re-checks status every 15s when idle; the expiry
    # tests exercise exactly that idle path - keep them fast
    monkeypatch.setattr("agno.os.event_streams.in_memory._TAIL_IDLE_RECHECK_SECONDS", 0.05)
    store = InMemoryQueueStore()
    set_active_queue_worker(SimpleNamespace(store=store))
    yield SimpleNamespace(stream=stream, store=store)
    set_active_queue_worker(None)


def seed_ticket(store, run_id, status="queued", **overrides):
    fields = dict(
        id=run_id,
        component_type="agent",
        component_id="a1",
        session_id="s1",
        payload={"input": "hi", "stream": True},
        status=status,
    )
    fields.update(overrides)
    store._jobs[run_id] = QueuedJob(**fields).to_dict()


async def collect(run_id):
    return [frame async for frame in queued_run_tail_streamer(run_id)]


class TestHonestClose:
    @pytest.mark.asyncio
    async def test_expired_stream_with_queued_ticket_emits_stream_expired(self, harness):
        """Stream state gone (expired), ticket still queued: the close must
        say so instead of looking like a finished stream."""
        seed_ticket(harness.store, "r-exp")
        frames = await collect("r-exp")
        expired = [f for f in frames if f.startswith("event: stream_expired")]
        assert expired, (
            f"tail ended silently over a still-queued ticket - frames: {frames!r}; "
            "the client was told a legitimately accepted run's stream is over"
        )
        assert '"status": "PENDING"' in expired[0]

    @pytest.mark.asyncio
    async def test_terminal_ticket_ends_silently(self, harness):
        seed_ticket(harness.store, "r-done", status="failed", error="worker lost")
        frames = await collect("r-done")
        assert not any(f.startswith("event: stream_expired") for f in frames)

    @pytest.mark.asyncio
    async def test_no_worker_ends_silently(self, harness, monkeypatch):
        from agno.os.job_queue import set_active_queue_worker

        set_active_queue_worker(None)
        frames = await collect("r-nobody")
        assert not any(f.startswith("event: stream_expired") for f in frames)

    @pytest.mark.asyncio
    async def test_normally_completed_run_ends_silently(self, harness):
        """A genuinely finished stream must not grow a spurious expired frame."""
        from agno.run.agent import RunContentEvent

        await harness.stream.register_run("r-ok", RunStatus.running)
        await harness.stream.add_event("r-ok", RunContentEvent(content="a", run_id="r-ok"))
        await harness.stream.complete_run("r-ok", RunStatus.completed)
        seed_ticket(harness.store, "r-ok", status="completed", completed_at=1)
        frames = await collect("r-ok")
        assert any("data:" in f for f in frames), "the real events must replay"
        assert not any(f.startswith("event: stream_expired") for f in frames)


class TestSettledTicketBoundsTheKeepalives:
    """A lost terminal write: the producer died between settling the ticket
    and closing the stream. Nothing would ever end the tail - it used to
    keepalive silently until the stream state expired (tens of minutes).
    The idle recheck now probes the ticket and closes truthfully."""

    @pytest.mark.asyncio
    async def test_terminal_ticket_with_running_stream_closes_honestly(self, monkeypatch):
        import asyncio

        import agno.os.job_queue as jq
        from agno.job_queue.store import InMemoryQueueStore
        from agno.os.event_streams.in_memory import InMemoryEventStream
        from agno.os.managers import EventsBuffer, SSESubscriberManager
        from agno.run.base import RunStatus

        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        monkeypatch.setattr("agno.os.event_streams.get_event_stream", lambda: stream)
        monkeypatch.setattr("agno.os.utils._TAIL_IDLE_RECHECK_SECONDS", 0.05, raising=False)

        # The stream believes the run is still RUNNING (terminal write lost)
        await stream.register_run("r-lost", RunStatus.pending)
        await stream.set_run_status("r-lost", RunStatus.running)

        # The ticket settled: the run actually finished
        store = InMemoryQueueStore()
        from agno.db.schemas.jobs import QueuedJob

        store._jobs["r-lost"] = QueuedJob(
            id="r-lost", component_type="agent", component_id="a1", session_id="s1", payload={}, status="completed"
        ).to_dict()
        original = jq.get_active_queue_worker()
        jq.set_active_queue_worker(SimpleNamespace(store=store))
        try:
            from agno.os.utils import queued_run_tail_streamer

            frames = []

            async def consume():
                async for frame in queued_run_tail_streamer("r-lost"):
                    frames.append(frame)
                    if len(frames) >= 5:
                        break

            await asyncio.wait_for(consume(), timeout=5)
        finally:
            jq.set_active_queue_worker(original)

        expired = [f for f in frames if f.startswith("event: stream_expired")]
        assert expired, f"a settled ticket over a running stream must close honestly, got {frames!r}"
        assert "poll the run" in expired[0]
        assert frames[-1] == expired[0], "the honest close must END the tail, not keep keepaliving"
