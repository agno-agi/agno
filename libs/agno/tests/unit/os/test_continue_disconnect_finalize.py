"""A client disconnect mid-inline-continue-stream must not abandon the
terminal-sync obligation.

The disconnecting client cancels the response task. The streamer's finally
then owed two writes - close the stream view with the run's real final
status, and settle a paused durable ticket - but its first unshielded await
leaked the cancellation (suppress(Exception) does not catch CancelledError),
so both were skipped: the stream view stayed RUNNING with no producer
(immortal on Redis, whose TTL refresher had enrolled the run - /resume
tails heartbeat forever) and the retention-exempt paused ticket said paused
forever. The obligation now runs as one shielded unit that completes even
while the response task is being cancelled - and under cancellation it
stamps the KNOWN cancelled status rather than racing the core's own
detached cancelled-row persist with a fresh session read.

These tests drive the REAL agents continue streamer with a continuation
that blocks mid-stream, then cancel the consumer exactly like a disconnect.
"""

import asyncio
from types import SimpleNamespace

import pytest

import agno.os.event_streams as es_mod
from agno.db.schemas.jobs import QueuedJob
from agno.job_queue.store import InMemoryQueueStore
from agno.os.event_streams import InMemoryEventStream, set_event_stream
from agno.os.managers import EventsBuffer, SSESubscriberManager
from agno.run.base import RunStatus

RUN_ID = "r-disc"
SESSION_ID = "s-disc"


@pytest.fixture()
def stream_harness():
    original = es_mod._event_stream
    stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    set_event_stream(stream)
    yield stream
    es_mod._event_stream = original


class ContinueFakeAgent:
    """Yields chunks like a real continuation; optionally blocks after the
    first chunk (the long tool call whose client walks away). The session
    read reports the run COMPLETED - the durable truth the finalizer must
    propagate to the stream and ticket."""

    id = "agent-1"

    def __init__(self, hang: bool = True):
        self.hang = hang
        self._never = asyncio.Event()

    def acontinue_run(self, **kwargs):
        def make_chunk():
            # format_sse_event needs to_json; a bare namespace would error
            # out of the streamer's try and finalize BEFORE any disconnect,
            # making the whole test vacuous
            chunk = SimpleNamespace(event="chunk", content="hello")
            chunk.to_dict = lambda: {"event": "chunk", "content": "hello"}
            chunk.to_json = lambda **kw: '{"event": "chunk", "content": "hello"}'
            return chunk

        async def gen():
            yield make_chunk()
            if self.hang:
                await self._never.wait()

        return gen()

    async def aget_session(self, session_id=None, **kwargs):
        # Slow enough that a level-based cancellation lands mid-read
        await asyncio.sleep(0.05)
        run = SimpleNamespace(status=RunStatus.completed, events=None)
        return SimpleNamespace(get_run=lambda rid: run)


async def seed_paused_ticket(store: InMemoryQueueStore) -> None:
    job = QueuedJob(
        id=RUN_ID,
        component_type="agent",
        component_id="agent-1",
        session_id=SESSION_ID,
        payload={"input": "hi", "kwargs": {}},
    ).to_dict()
    await store.enqueue_job(job)
    claimed = await store.claim_job("w1")
    assert await store.complete_job(RUN_ID, "w1", claimed["attempt"], "paused")


@pytest.mark.asyncio
async def test_disconnect_mid_stream_still_closes_stream_and_settles_ticket(stream_harness):
    from agno.os.routers.agents.router import agent_continue_response_streamer

    store = InMemoryQueueStore()
    await seed_paused_ticket(store)
    agent = ContinueFakeAgent(hang=True)
    gen = agent_continue_response_streamer(
        agent, RUN_ID, session_id=SESSION_ID, queue_worker=SimpleNamespace(store=store)
    )

    consumed: list = []

    async def consume():
        async for frame in gen:
            consumed.append(frame)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.2)
    assert consumed, "the stream must have produced its first frame before the disconnect"

    # The client walks away. Starlette's disconnect cancellation is
    # LEVEL-based (anyio cancel scopes re-raise at every await until the
    # scope exits), not a single edge - simulate that by re-cancelling
    # until the response task actually ends. This is exactly what defeats
    # an unshielded finally: each await inside it takes the cancellation
    # again.
    for _ in range(50):
        if task.done():
            break
        task.cancel()
        await asyncio.sleep(0.01)
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0.3)  # the shielded obligation completes in the background

    status = await stream_harness.get_run_status(RUN_ID)
    assert status == RunStatus.cancelled, (
        f"stream view finalized as {status} - a disconnect cancels the inline continue, and the "
        "finalizer must stamp that KNOWN status instead of racing the core's own cancelled-row "
        "persist with a session read (which can observe the stale paused/running row)"
    )
    job = await store.get_job(RUN_ID)
    assert job["status"] == "cancelled", f"the paused ticket must settle as cancelled: {job['status']}"


@pytest.mark.asyncio
async def test_clean_completion_still_finalizes(stream_harness):
    """The non-disconnect path must be unchanged: stream closed with the
    run's final status, ticket settled."""
    from agno.os.routers.agents.router import agent_continue_response_streamer

    store = InMemoryQueueStore()
    await seed_paused_ticket(store)
    agent = ContinueFakeAgent(hang=False)
    gen = agent_continue_response_streamer(
        agent, RUN_ID, session_id=SESSION_ID, queue_worker=SimpleNamespace(store=store)
    )

    frames = [frame async for frame in gen]
    assert frames

    assert await stream_harness.get_run_status(RUN_ID) == RunStatus.completed
    assert (await store.get_job(RUN_ID))["status"] == "completed"
