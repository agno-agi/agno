import asyncio
from collections.abc import Iterator
from typing import Any, AsyncGenerator, AsyncIterator, Dict, List, Optional, Tuple, Union

from ag_ui.core import BaseEvent

from agno.os.interfaces.agui.a2ui_stream import A2UIRenderStream
from agno.os.interfaces.agui.handlers import (
    is_completion_event,
    on_a2ui_render_stream,
    process_completion,
    process_event,
)
from agno.os.interfaces.agui.state import StreamState
from agno.run.agent import RunCompletedEvent, RunOutputEvent
from agno.run.team import TeamRunOutputEvent

#: What produced an item the mapper is about to translate: the agent's own run,
#: or the side channel carrying A2UI render progress.
_AGENT = "agent"
_A2UI = "a2ui"


def stream_agno_response_as_agui_events(
    response_stream: Iterator[Union[RunOutputEvent, TeamRunOutputEvent]],
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]] = None,
) -> Iterator[BaseEvent]:
    """Map the Agno response stream to AG-UI format."""
    state = StreamState(thread_id=thread_id, run_id=run_id, run_state=run_state)

    if run_state is not None:
        state.set_state_snapshot(run_state)

    terminal_chunk = None

    for chunk in response_stream:
        if is_completion_event(chunk):
            terminal_chunk = chunk
        else:
            for event in process_event(chunk, state):
                yield event

    # Process completion (or synthesize one if stream ended naturally)
    final_chunk = terminal_chunk or RunCompletedEvent()
    for event in process_completion(final_chunk, state):
        yield event


async def _close_stream(events: Any) -> None:
    """Close the agent's stream, if it is the kind that can be closed.

    Closing is what reaches the run's own cleanup. A plain async iterator has
    none to reach, so there is nothing to do for one.
    """
    aclose = getattr(events, "aclose", None)
    if aclose is not None:
        await aclose()


async def _agent_events_only(
    response_stream: AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent]],
) -> AsyncGenerator[Tuple[str, Any], None]:
    """Pass the agent's events through, and close its stream on the way out.

    Iterating never closes what it iterates, so closing this wrapper would
    otherwise stop here and leave the run behind it suspended.
    """
    events = response_stream.__aiter__()
    try:
        async for chunk in events:
            yield _AGENT, chunk
    finally:
        await _close_stream(events)


async def _drive_agent_stream(
    events: AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent]],
    chunks: List[Any],
    ready: asyncio.Event,
    taken: asyncio.Event,
) -> None:
    """Advance the agent's stream from one task, handing each event over in turn.

    The merge loop cannot await the next agent event itself: it has to stay free
    to emit a render fragment while that event is still being produced. Driving
    the whole stream from a single task, rather than a task per event, is what
    keeps the run in one context: a task copies the context it was created in
    and drops whatever the coroutine wrote to it, so a context variable the run
    set while producing one event would be gone by the next one.

    ``taken`` makes each handoff a rendezvous, so the run is never advanced past
    an event the merge loop has not emitted yet.
    """
    try:
        async for chunk in events:
            chunks.append(chunk)
            ready.set()
            await taken.wait()
            taken.clear()
    finally:
        # Exhausted, failed or cancelled: stop the merge loop from waiting for
        # an event that is never coming.
        ready.set()


async def _stop_agent_stream(
    events: AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent]],
    driver: "asyncio.Future",
) -> None:
    """Stop driving the agent's stream and let the run finalize.

    Cancelling is not enough on its own: closing an async generator raises
    while one of its steps is still in flight, so the cancellation has to have
    landed before the close. Awaiting it does not mean the run has finished
    finalizing, though, because a cancelled run is persisted on a task of its
    own that outlives this one. Closing is not enough either: a run suspended
    at one of its own events has nothing in flight to cancel, so only the close
    reaches its cleanup.
    """
    driver.cancel()
    await asyncio.wait({driver})
    if not driver.cancelled():
        # The consumer has gone away, so a failure here has nowhere left to be
        # reported. Take it off the task so asyncio does not log it as
        # unretrieved.
        driver.exception()

    await _close_stream(events)


async def _interleaved_with_a2ui(
    response_stream: AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent]],
    render_stream: A2UIRenderStream,
) -> AsyncGenerator[Tuple[str, Any], None]:
    """Merge the agent's events with A2UI render progress as each arrives.

    A generation tool holds the agent's event stream open while its render
    subagent works, so waiting only on the agent would hold every fragment back
    until the tool returned and the surface would appear all at once.
    """
    events = response_stream.__aiter__()
    chunks: List[Any] = []
    ready = asyncio.Event()
    taken = asyncio.Event()
    driver = asyncio.ensure_future(_drive_agent_stream(events, chunks, ready, taken))

    try:
        while True:
            waiters = [
                asyncio.ensure_future(ready.wait()),
                asyncio.ensure_future(render_stream.wait()),
            ]
            try:
                await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            finally:
                # Both are waits on a signal, and waiting on one consumes
                # nothing, so cancelling them cannot drop a fragment or an
                # agent event.
                for waiter in waiters:
                    waiter.cancel()

            # Fragments first: they were produced while the tool was running, so
            # they precede whatever the agent emitted once it returned.
            for payload in render_stream.drain():
                yield _A2UI, payload

            if chunks:
                chunk = chunks.pop(0)
                ready.clear()
                yield _AGENT, chunk
                taken.set()
                continue

            if driver.done():
                # Raises whatever ended the run; a clean end returns None.
                driver.result()
                break
    except Exception:
        # The run is over either way, so whatever of the surface was drawn
        # before the failure is all the client will ever get: hand the buffered
        # fragments over ahead of the error rather than dropping them.
        for payload in render_stream.drain():
            yield _A2UI, payload
        raise
    finally:
        await _stop_agent_stream(events, driver)

    for payload in render_stream.drain():
        yield _A2UI, payload


async def async_stream_agno_response_as_agui_events(
    response_stream: AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent]],
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]] = None,
    a2ui_render_stream: Optional[A2UIRenderStream] = None,
) -> AsyncGenerator[BaseEvent, None]:
    """Map the Agno response stream to AG-UI format.

    ``a2ui_render_stream`` is supplied only for a run that can generate an A2UI
    surface. Interleaving costs a wait on every streamed event, so a run that
    cannot generate one does not pay it. There is no equivalent on the
    synchronous mapper above: A2UI generation is asynchronous throughout.
    """
    state = StreamState(thread_id=thread_id, run_id=run_id, run_state=run_state)

    if run_state is not None:
        state.set_state_snapshot(run_state)

    terminal_chunk = None

    if a2ui_render_stream is None:
        source = _agent_events_only(response_stream)
    else:
        source = _interleaved_with_a2ui(response_stream, a2ui_render_stream)

    try:
        async for origin, item in source:
            if origin == _A2UI:
                for event in on_a2ui_render_stream(item, state):
                    yield event
            elif is_completion_event(item):
                terminal_chunk = item
            else:
                for event in process_event(item, state):
                    yield event
    finally:
        # Iterating does not close, so a client that leaves mid-run would leave
        # the source suspended and the run behind it unfinalized.
        await source.aclose()

    # Process completion (or synthesize one if stream ended naturally)
    final_chunk = terminal_chunk or RunCompletedEvent()
    for event in process_completion(final_chunk, state):
        yield event
