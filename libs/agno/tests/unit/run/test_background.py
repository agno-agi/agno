"""Unit tests for the shared background run helpers."""

import asyncio

import pytest

from agno.os.utils import format_sse_event_with_index, sse_error_frame
from agno.run import background
from agno.run.agent import RunContentEvent, RunErrorEvent, RunOutput, RunPausedEvent
from agno.run.background import _spawn_background, await_background_runs, map_background_stream_to_run_events
from agno.run.base import RunStatus


@pytest.mark.asyncio
async def test_await_background_runs_waits_for_spawned_tasks():
    finished = []

    async def work():
        await asyncio.sleep(0.05)
        finished.append("done")

    _spawn_background(work())
    _spawn_background(work())
    assert finished == []
    await await_background_runs()
    assert finished == ["done", "done"]
    assert not [task for task in background._background_tasks if not task.done()]


@pytest.mark.asyncio
async def test_await_background_runs_returns_when_nothing_is_pending():
    await await_background_runs()


@pytest.mark.asyncio
async def test_await_background_runs_honours_timeout():
    release = asyncio.Event()

    async def work():
        await release.wait()

    _spawn_background(work())
    await await_background_runs(timeout=0.05)
    assert [task for task in background._background_tasks if not task.done()], "task should still be running"
    release.set()
    await await_background_runs()


@pytest.mark.asyncio
async def test_map_background_stream_to_run_events_parses_sse_and_stops_at_pause():
    async def stream():
        yield format_sse_event_with_index(RunContentEvent(run_id="r1", content="hi"), event_index=0)
        yield ": keepalive\n\n"
        yield RunOutput(run_id="r1")
        yield format_sse_event_with_index(RunPausedEvent(run_id="r1", session_id="s1"), event_index=1)

    class Entity:
        async def aget_run_output(self, run_id, session_id):
            raise AssertionError("a stream that ends at its own pause is not looked up")

    events = [event async for event in map_background_stream_to_run_events(stream(), Entity(), "r1", "s1")]
    assert [type(event) for event in events] == [RunContentEvent, RunPausedEvent]
    assert events[0].content == "hi"


@pytest.mark.asyncio
async def test_map_background_stream_to_run_events_reads_an_iterator_without_aclose():
    class Stream:
        # An AsyncIterator that is not a generator has no aclose
        def __init__(self):
            self.frames = iter(
                [format_sse_event_with_index(RunPausedEvent(run_id="r1", session_id="s1"), event_index=0)]
            )

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.frames)
            except StopIteration:
                raise StopAsyncIteration

    events = [event async for event in map_background_stream_to_run_events(Stream(), object(), "r1", "s1")]
    assert [type(event) for event in events] == [RunPausedEvent]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "frame",
    [
        sse_error_frame("lost"),
        'event: stream_expired\ndata: {"event": "stream_expired", "run_id": "r1", "status": "ERROR"}\n\n',
    ],
)
async def test_map_background_stream_to_run_events_ends_at_a_transport_frame(frame):
    async def stream():
        yield frame
        raise AssertionError("the stream is not read past a transport frame")

    class Entity:
        async def aget_run_output(self, run_id, session_id):
            return RunOutput(run_id=run_id, session_id=session_id, status=RunStatus.error, content="boom")

    events = [event async for event in map_background_stream_to_run_events(stream(), Entity(), "r1", "s1")]
    assert len(events) == 1 and isinstance(events[0], RunErrorEvent)
    assert events[0].content == "boom"
