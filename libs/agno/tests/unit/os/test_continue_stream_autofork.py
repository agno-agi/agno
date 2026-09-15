"""The inline continue streamers must not publish an auto-fork under the parent's stream.

Continuing a COMPLETED run forks a sibling with a fresh run_id, and it does so with
``fork=False`` - so the streamers' fork/regenerate gate cannot see it. The route decides
from the stored row with the same predicate the background streamer uses
(``take_over_in_place``): a COMPLETED or CANCELLED row is never registered under its own
id, and an in-place row is registered BEFORE the first chunk so a /resume that lands
before it still attaches. When the row was not read (factory components)
the decision waits for the opening chunk, which carries the executing id.

The streamers are driven directly with a fake component, the way
test_continue_disconnect_finalize.py does: the fake's ``acontinue_run`` yields chunks
stamped with whichever run_id the test wants to be "executing".
"""

import asyncio
from types import SimpleNamespace
from typing import Type

import pytest

import agno.os.event_streams as es_mod
from agno.os.event_streams import InMemoryEventStream, set_event_stream
from agno.os.managers import EventsBuffer, SSESubscriberManager
from agno.run.agent import RunContentEvent as AgentRunContentEvent
from agno.run.base import RunStatus
from agno.run.team import RunContentEvent as TeamRunContentEvent

PARENT_RUN_ID = "r-parent"
FORK_RUN_ID = "r-fork"
SESSION_ID = "s-autofork"


@pytest.fixture()
def stream_harness():
    original = es_mod._event_stream
    stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    set_event_stream(stream)
    yield stream
    es_mod._event_stream = original


class _ContinueFake:
    """Yields two content chunks stamped with ``executing_run_id``. ``release`` gates the
    first chunk so a test can observe the stream between the streamer's start and its
    first frame - the window a /resume can land in. The session
    read reports the parent COMPLETED, which is what the finalizer sees on an in-place
    continue that has already settled."""

    id = "component-1"

    def __init__(self, event_cls: Type, executing_run_id: str):
        self.event_cls = event_cls
        self.executing_run_id = executing_run_id
        self.release = asyncio.Event()
        self.release.set()

    def acontinue_run(self, **kwargs):
        async def gen():
            await self.release.wait()
            yield self.event_cls(content="first", run_id=self.executing_run_id)
            yield self.event_cls(content="second", run_id=self.executing_run_id)

        return gen()

    async def aget_session(self, session_id=None, **kwargs):
        run = SimpleNamespace(status=RunStatus.completed, events=None)
        return SimpleNamespace(get_run=lambda rid: run)


async def _drain(gen) -> list:
    return [frame async for frame in gen]


def _streamers():
    from agno.os.routers.agents.router import agent_continue_response_streamer
    from agno.os.routers.teams.router import team_continue_response_streamer

    def agent_stream(component, run_id, **kwargs):
        return agent_continue_response_streamer(component, run_id, session_id=SESSION_ID, **kwargs)

    def team_stream(component, run_id, **kwargs):
        return team_continue_response_streamer(component, run_id, requirements=[], session_id=SESSION_ID, **kwargs)

    return [
        pytest.param(agent_stream, AgentRunContentEvent, id="agent"),
        pytest.param(team_stream, TeamRunContentEvent, id="team"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("streamer,event_cls", _streamers())
async def test_a_completed_row_is_not_published_under_the_parent(stream_harness, streamer, event_cls):
    """The route read the stored row and it was COMPLETED: the continuation will auto-fork,
    so the parent must never be registered and none of the fork's events may land under it."""
    fake = _ContinueFake(event_cls, FORK_RUN_ID)
    frames = await _drain(streamer(fake, PARENT_RUN_ID, take_over_in_place=False))

    assert len(frames) == 2, "the client must still receive the continuation's frames"
    assert await stream_harness.get_run_status(PARENT_RUN_ID) is None, (
        "the parent was registered on the event stream for a continuation that executed under another run_id"
    )
    assert await stream_harness.get_event_count(PARENT_RUN_ID) == 0, (
        "the fork's events were appended under the parent's stream key"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("streamer,event_cls", _streamers())
async def test_an_in_place_row_is_registered_before_the_first_chunk(stream_harness, streamer, event_cls):
    """The route read the stored row and it was continuable in place: the parent is
    registered BEFORE the first chunk, so a /resume that lands before it attaches
    instead of falling back to a closed db replay."""
    fake = _ContinueFake(event_cls, PARENT_RUN_ID)
    fake.release.clear()
    gen = streamer(fake, PARENT_RUN_ID, take_over_in_place=True)

    consumed: list = []

    async def consume():
        async for frame in gen:
            consumed.append(frame)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    assert not consumed, "no frame may have been produced yet"
    assert await stream_harness.get_run_status(PARENT_RUN_ID) == RunStatus.running, (
        "the in-place continuation was not registered before its first chunk"
    )

    fake.release.set()
    await task
    assert len(consumed) == 2
    assert await stream_harness.get_event_count(PARENT_RUN_ID) == 2, "the in-place continuation was not mirrored"
    assert await stream_harness.get_run_status(PARENT_RUN_ID) == RunStatus.completed, (
        "the in-place continuation's stream was not finalized"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("streamer,event_cls", _streamers())
async def test_an_unread_row_defers_to_the_opening_chunk(stream_harness, streamer, event_cls):
    """Factory components skip the stored-row read, so the streamer has no verdict: it
    waits for the opening chunk and reads the executing id off it."""
    frames = await _drain(streamer(_ContinueFake(event_cls, FORK_RUN_ID), PARENT_RUN_ID, take_over_in_place=None))
    assert len(frames) == 2
    assert await stream_harness.get_run_status(PARENT_RUN_ID) is None
    assert await stream_harness.get_event_count(PARENT_RUN_ID) == 0

    frames = await _drain(streamer(_ContinueFake(event_cls, PARENT_RUN_ID), PARENT_RUN_ID, take_over_in_place=None))
    assert len(frames) == 2
    assert await stream_harness.get_event_count(PARENT_RUN_ID) == 2
    assert await stream_harness.get_run_status(PARENT_RUN_ID) == RunStatus.completed


@pytest.mark.asyncio
@pytest.mark.parametrize("streamer,event_cls", _streamers())
async def test_a_wrong_verdict_stops_mirroring_but_still_closes_the_stream(stream_harness, streamer, event_cls):
    """The safety net: the row said in place, so the parent was registered, but the leg
    executes under another id. Mirroring stops so the fork's events never land under the
    parent, and the stream this streamer opened is still finalized rather than left RUNNING."""
    frames = await _drain(streamer(_ContinueFake(event_cls, FORK_RUN_ID), PARENT_RUN_ID, take_over_in_place=True))

    assert len(frames) == 2
    assert await stream_harness.get_event_count(PARENT_RUN_ID) == 0, (
        "the fork's events were appended under the parent's stream key"
    )
    assert await stream_harness.get_run_status(PARENT_RUN_ID) == RunStatus.completed, (
        "a stream this streamer registered must be finalized even when mirroring was stopped"
    )
