"""Unit tests for the shared durable-continue seam helper.

acontinue_via_queue is the one path all four seams (HTTP agents/teams/
workflows + WS continue-workflow) go through: outcome mapping, cancellation-
intent clearing, and the PAUSED -> PENDING stream-status flip live here, so
the seams cannot diverge on them.
"""

import pytest

from agno.db.schemas.jobs import QueuedJob
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os.job_queue import QueueWorker, acontinue_via_queue


def make_job(job_id: str = "r1", stream: bool = False) -> dict:
    payload = {"input": "hello", "kwargs": {}}
    if stream:
        payload["stream"] = True
    return QueuedJob(
        id=job_id,
        component_type="workflow",
        component_id="wf-1",
        session_id="s1",
        payload=payload,
    ).to_dict()


def make_worker(store: InMemoryQueueStore) -> QueueWorker:
    return QueueWorker(
        store=store,
        resolve_component=lambda t, i: None,
        config=QueueConfig(durable=True, poll_interval=0.05, lock_grace_seconds=60),
        worker_id="seam-test-worker",
    )


async def _pause(store: InMemoryQueueStore, job_id: str = "r1", stream: bool = False) -> None:
    await store.enqueue_job(make_job(job_id, stream=stream))
    claimed = await store.claim_job("w1")
    assert await store.complete_job(job_id, "w1", claimed["attempt"], "paused")


class TestOutcomeMapping:
    @pytest.mark.asyncio
    async def test_no_ticket_returns_none_for_detached_fallback(self):
        worker = make_worker(InMemoryQueueStore())
        assert await acontinue_via_queue(worker, "ghost", {}) is None

    @pytest.mark.asyncio
    async def test_paused_ticket_accepts(self):
        store = InMemoryQueueStore()
        await _pause(store)
        result = await acontinue_via_queue(make_worker(store), "r1", {"step_requirements": [{"step_id": "s"}]})
        assert result["outcome"] == "queued"
        assert result["job"]["payload"]["continue"] == {"step_requirements": [{"step_id": "s"}]}

    @pytest.mark.asyncio
    async def test_queued_after_continue_attaches(self):
        store = InMemoryQueueStore()
        await _pause(store)
        worker = make_worker(store)
        await acontinue_via_queue(worker, "r1", {"a": 1})
        result = await acontinue_via_queue(worker, "r1", {"a": 2})
        assert result["outcome"] == "attach"

    @pytest.mark.asyncio
    async def test_queued_fresh_submission_returns_none(self):
        """A queued ticket with no continue block is a not-yet-executed
        submission: continuing it is a state error the detached path reports;
        the seam must NOT attach a continue response to it."""
        store = InMemoryQueueStore()
        await store.enqueue_job(make_job())
        assert await acontinue_via_queue(make_worker(store), "r1", {}) is None

    @pytest.mark.asyncio
    async def test_running_ticket_is_settling(self):
        store = InMemoryQueueStore()
        await store.enqueue_job(make_job())
        await store.claim_job("w1")
        result = await acontinue_via_queue(make_worker(store), "r1", {})
        assert result["outcome"] == "settling"

    @pytest.mark.asyncio
    async def test_terminal_ticket_returns_none(self):
        store = InMemoryQueueStore()
        await store.enqueue_job(make_job())
        claimed = await store.claim_job("w1")
        await store.complete_job("r1", "w1", claimed["attempt"], "completed")
        assert await acontinue_via_queue(make_worker(store), "r1", {}) is None

    @pytest.mark.asyncio
    async def test_cancelled_ticket_returns_none_not_resurrect(self):
        """Cancel-while-paused then continue: the ticket is terminal, the
        durable path declines, and the detached path's own not-paused check
        reports the state - the run is never silently resurrected."""
        store = InMemoryQueueStore()
        await _pause(store)
        assert await store.cancel_job("r1")
        assert await acontinue_via_queue(make_worker(store), "r1", {}) is None


class TestAcceptSideEffects:
    @pytest.mark.asyncio
    async def test_stale_cancellation_intent_cleared_on_accept(self):
        """The requeue-endpoint fix, mirrored: intent registered during the
        paused stretch must not kill the new leg at its first checkpoint."""
        from agno.run.cancel import acancel_run, ais_cancelled, aregister_run

        store = InMemoryQueueStore()
        await _pause(store)
        await aregister_run("r1")
        await acancel_run("r1")
        assert await ais_cancelled("r1")
        result = await acontinue_via_queue(make_worker(store), "r1", {})
        assert result["outcome"] == "queued"
        assert not await ais_cancelled("r1"), "stale intent must be cleared on accept"

    @pytest.mark.asyncio
    async def test_stream_status_flipped_to_pending_on_accept(self):
        """PAUSED is tail-terminal: without the flip, a tail attached between
        accept and claim replays the settled pause and closes."""
        import agno.os.event_streams as es_mod
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.managers import EventsBuffer, SSESubscriberManager
        from agno.run.base import RunStatus

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:
            store = InMemoryQueueStore()
            await _pause(store, stream=True)
            await stream.register_run("r1", RunStatus.pending)
            await stream.complete_run("r1", RunStatus.paused)
            assert await stream.get_run_status("r1") == RunStatus.paused

            result = await acontinue_via_queue(make_worker(store), "r1", {})
            assert result["outcome"] == "queued"
            assert await stream.get_run_status("r1") == RunStatus.pending
        finally:
            es_mod._event_stream = original

    @pytest.mark.asyncio
    async def test_non_stream_submission_does_not_touch_stream_status(self):
        import agno.os.event_streams as es_mod
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.managers import EventsBuffer, SSESubscriberManager

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:
            store = InMemoryQueueStore()
            await _pause(store, stream=False)
            result = await acontinue_via_queue(make_worker(store), "r1", {})
            assert result["outcome"] == "queued"
            assert await stream.get_run_status("r1") is None, "non-stream runs have no stream view to touch"
        finally:
            es_mod._event_stream = original
