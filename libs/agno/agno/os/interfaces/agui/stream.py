"""Stream adapters for AG-UI protocol.

Provides sync and async iterators that transform Agno run streams into AG-UI events.
This is the main entry point for event translation — router.py calls these functions.
"""

from collections.abc import Iterator
from typing import Any, AsyncIterator, Dict, Optional, Union

from ag_ui.core import BaseEvent

from agno.os.interfaces.agui.handlers import is_completion_event, process_completion, process_event
from agno.os.interfaces.agui.state import StreamState
from agno.run.agent import RunCompletedEvent, RunOutputEvent
from agno.run.team import TeamRunOutputEvent


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

    completion_chunk = None

    for chunk in response_stream:
        if is_completion_event(chunk):
            completion_chunk = chunk
        else:
            for event in process_event(chunk, state):
                yield event

    # Process completion (or synthesize one if stream ended naturally)
    final_chunk = completion_chunk or RunCompletedEvent()
    for event in process_completion(final_chunk, state):
        yield event


async def async_stream_agno_response_as_agui_events(
    response_stream: AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent]],
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[BaseEvent]:
    """Map the Agno response stream to AG-UI format."""
    state = StreamState(thread_id=thread_id, run_id=run_id, run_state=run_state)

    if run_state is not None:
        state.set_state_snapshot(run_state)

    completion_chunk = None

    async for chunk in response_stream:
        if is_completion_event(chunk):
            completion_chunk = chunk
        else:
            for event in process_event(chunk, state):
                yield event

    # Process completion (or synthesize one if stream ended naturally)
    final_chunk = completion_chunk or RunCompletedEvent()
    for event in process_completion(final_chunk, state):
        yield event
