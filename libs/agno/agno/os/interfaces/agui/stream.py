from collections.abc import Iterator
from typing import Any, AsyncIterator, Dict, Optional, Union

from ag_ui.core import BaseEvent

from agno.os.interfaces.agui.handlers import RunTerminalTracker, close_open_spans, process_event
from agno.os.interfaces.agui.state import StreamState
from agno.run.agent import RunOutputEvent
from agno.run.team import TeamRunOutputEvent
from agno.run.workflow import WorkflowRunOutputEvent


def stream_agno_response_as_agui_events(
    response_stream: Iterator[Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent]],
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]] = None,
) -> Iterator[BaseEvent]:
    """Map the Agno response stream to AG-UI format."""
    state = StreamState(thread_id=thread_id, run_id=run_id, run_state=run_state)

    if run_state is not None:
        state.set_state_snapshot(run_state)

    terminal = RunTerminalTracker()

    try:
        for chunk in response_stream:
            if terminal.observe(chunk):
                continue
            for event in process_event(chunk, state):
                yield event

        terminal_events = terminal.emit(state)
    except Exception:
        # The route ends a failed run with RUN_ERROR, and it cannot close what this
        # stream left open because the state lives here. Close it on the way out, so
        # the client is not holding a step, a message or a tool call at the terminal
        # event, and let the exception carry on to the route that reports it.
        for event in close_open_spans(state):
            yield event
        raise

    for event in terminal_events:
        yield event


async def async_stream_agno_response_as_agui_events(
    response_stream: AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent]],
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[BaseEvent]:
    """Map the Agno response stream to AG-UI format."""
    state = StreamState(thread_id=thread_id, run_id=run_id, run_state=run_state)

    if run_state is not None:
        state.set_state_snapshot(run_state)

    terminal = RunTerminalTracker()

    try:
        async for chunk in response_stream:
            if terminal.observe(chunk):
                continue
            for event in process_event(chunk, state):
                yield event

        terminal_events = terminal.emit(state)
    except Exception:
        # As in the sync mapper above: the route reports the failure, this stream is the
        # only thing that knows what the client still has open.
        for event in close_open_spans(state):
            yield event
        raise

    for event in terminal_events:
        yield event
