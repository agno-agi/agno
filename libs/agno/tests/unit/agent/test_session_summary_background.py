"""Session summary generation must not block streaming runs.

Verifies fix for https://github.com/agno-agi/agno/issues/8746: the summary is
generated in a background task/thread after the session store, so RunCompleted
is emitted without waiting on it — but the summary must still be persisted by
the time the stream is exhausted.
"""

import asyncio
import time
from typing import Any, AsyncIterator, Iterator

from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.db.in_memory import InMemoryDb
from agno.media import Image
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunCompletedEvent
from agno.session.summary import SessionSummary, SessionSummaryManager

SUMMARY_DELAY = 0.3


class MockModel(Model):
    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._mock_response = ModelResponse(
            content="Hello there",
            role="assistant",
            response_usage=MessageMetrics(),
        )

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._mock_response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


class MockModelWithImage(MockModel):
    def __init__(self):
        super().__init__()
        self._mock_response = ModelResponse(
            content="Here is your generated image",
            role="assistant",
            images=[Image(url="https://example.com/generated.png", id="img-1")],
            response_usage=MessageMetrics(),
        )


class SlowSummaryManager(SessionSummaryManager):
    """Stub manager whose summary generation sleeps, to expose blocking."""

    finished = False

    def create_session_summary(self, session, run_metrics=None):
        time.sleep(SUMMARY_DELAY)
        summary = SessionSummary(summary="stub summary")
        session.summary = summary
        self.finished = True
        return summary

    async def acreate_session_summary(self, session, run_metrics=None):
        await asyncio.sleep(SUMMARY_DELAY)
        summary = SessionSummary(summary="stub summary")
        session.summary = summary
        self.finished = True
        return summary


def _make_agent(db: InMemoryDb) -> Agent:
    return Agent(
        model=MockModel(),
        db=db,
        session_summary_manager=SlowSummaryManager(),
        telemetry=False,
    )


def _stored_summary(db: InMemoryDb, session_id: str):
    stored = db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    assert stored is not None
    return stored.summary


def test_sync_stream_run_completed_not_blocked_by_summary():
    db = InMemoryDb()
    agent = _make_agent(db)

    summary_finished_at_completed = None
    for event in agent.run("hello", stream=True, stream_events=True, session_id="s-sync", user_id="u1"):
        if isinstance(event, RunCompletedEvent):
            summary_finished_at_completed = agent.session_summary_manager.finished

    # RunCompleted was emitted before the summary finished...
    assert summary_finished_at_completed is False
    # ...but by stream exhaustion the summary is generated and persisted
    assert agent.session_summary_manager.finished is True
    summary = _stored_summary(db, "s-sync")
    assert summary is not None
    assert summary.summary == "stub summary"


async def test_async_stream_run_completed_not_blocked_by_summary():
    db = InMemoryDb()
    agent = _make_agent(db)

    summary_finished_at_completed = None
    async for event in agent.arun("hello", stream=True, stream_events=True, session_id="s-async", user_id="u1"):
        if isinstance(event, RunCompletedEvent):
            summary_finished_at_completed = agent.session_summary_manager.finished

    assert summary_finished_at_completed is False
    assert agent.session_summary_manager.finished is True
    summary = _stored_summary(db, "s-async")
    assert summary is not None
    assert summary.summary == "stub summary"


async def test_second_streaming_run_keeps_all_runs_and_summary():
    # The background summary save must not clobber runs stored by a later run
    # on the same session, so drive the same session twice.
    db = InMemoryDb()
    agent = _make_agent(db)

    for _ in range(2):
        async for _event in agent.arun("hello", stream=True, stream_events=True, session_id="s-twice", user_id="u1"):
            pass

    stored = db.get_session(session_id="s-twice", session_type=SessionType.AGENT)
    assert stored is not None
    assert stored.runs is not None
    assert len(stored.runs) == 2
    assert stored.summary is not None
    assert stored.summary.summary == "stub summary"


async def test_consumer_task_cancelled_after_run_completed_keeps_summary():
    # The AgentOS/SSE disconnect pattern: the server consumes the stream in a
    # task and has already advanced past RunCompleted into the generator's
    # final summary wait when the client disconnect cancels it. Cancelling
    # that await must not cancel the summary task itself — it finishes
    # detached and persists the summary.
    db = InMemoryDb()
    agent = _make_agent(db)
    got_completed = asyncio.Event()

    async def consume():
        async for event in agent.arun("hello", stream=True, stream_events=True, session_id="s-cancel", user_id="u1"):
            if isinstance(event, RunCompletedEvent):
                got_completed.set()

    consumer = asyncio.create_task(consume())
    await got_completed.wait()
    # One tick is enough to land the consumer in the shielded summary wait because
    # nothing between RunCompleted and that wait suspends; if a suspending await is
    # ever added there, the cancel lands earlier and this test stops exercising
    # the shield.
    await asyncio.sleep(0)
    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass

    # The event loop stays alive (AgentOS server case): the detached task finishes
    await asyncio.sleep(SUMMARY_DELAY + 0.2)
    summary = _stored_summary(db, "s-cancel")
    assert summary is not None
    assert summary.summary == "stub summary"


async def test_abandoned_stream_summary_does_not_clobber_next_run():
    # The detached case the re-read protects: run 1's stream is abandoned at
    # RunCompleted while its summary is still generating, run 2 stores on the
    # same session before that summary lands. The delayed summary save must
    # re-read the stored session and keep run 2.
    db = InMemoryDb()
    gate = asyncio.Event()

    class GatedSummaryManager(SessionSummaryManager):
        calls = 0

        async def acreate_session_summary(self, session, run_metrics=None):
            GatedSummaryManager.calls += 1
            call = GatedSummaryManager.calls
            if call == 1:
                await gate.wait()
            summary = SessionSummary(summary=f"summary-{call}")
            session.summary = summary
            return summary

    agent = Agent(
        model=MockModel(),
        db=db,
        session_summary_manager=GatedSummaryManager(),
        telemetry=False,
    )

    # Run 1: abandon the stream at RunCompleted; its summary task stays gated
    gen = agent.arun("one", stream=True, stream_events=True, session_id="s-overlap", user_id="u1")
    async for event in gen:
        if isinstance(event, RunCompletedEvent):
            break
    await gen.aclose()
    await asyncio.sleep(0.05)  # let the abandonment persistence settle

    # Run 2 on the same session completes fully (its summary is ungated)
    async for _event in agent.arun("two", stream=True, stream_events=True, session_id="s-overlap", user_id="u1"):
        pass

    # Release run 1's summary; its save must not erase run 2 from the session,
    # and its stale result must not overwrite run 2's newer summary
    gate.set()
    await asyncio.sleep(0.3)

    stored = db.get_session(session_id="s-overlap", session_type=SessionType.AGENT)
    assert stored is not None
    assert stored.runs is not None
    assert len(stored.runs) == 2
    assert stored.summary is not None
    assert stored.summary.summary == "summary-2"


def test_background_summary_does_not_leak_scrubbed_media_cached_session():
    # With cache_session=True the summary task re-reads the cached session
    # object; it must not save unscrubbed run data (store_media=False) with it.
    db = InMemoryDb()
    agent = Agent(
        model=MockModelWithImage(),
        db=db,
        session_summary_manager=SlowSummaryManager(),
        cache_session=True,
        store_media=False,
        telemetry=False,
    )

    for _event in agent.run("make an image", stream=True, stream_events=True, session_id="s-scrub", user_id="u1"):
        pass

    stored = db.get_session(session_id="s-scrub", session_type=SessionType.AGENT)
    assert stored is not None
    assert stored.runs is not None
    assert not stored.runs[-1].images
    assert stored.summary is not None


async def test_background_summary_does_not_leak_scrubbed_media_cached_session_async():
    db = InMemoryDb()
    agent = Agent(
        model=MockModelWithImage(),
        db=db,
        session_summary_manager=SlowSummaryManager(),
        cache_session=True,
        store_media=False,
        telemetry=False,
    )

    async for _event in agent.arun(
        "make an image", stream=True, stream_events=True, session_id="s-scrub-a", user_id="u1"
    ):
        pass

    stored = db.get_session(session_id="s-scrub-a", session_type=SessionType.AGENT)
    assert stored is not None
    assert stored.runs is not None
    assert not stored.runs[-1].images
    assert stored.summary is not None
