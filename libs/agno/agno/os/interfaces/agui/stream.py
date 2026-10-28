from collections.abc import Iterator
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union

from ag_ui.core import BaseEvent

from agno.os.interfaces.agui.handlers import (
    _readable as readable_value,
)
from agno.os.interfaces.agui.handlers import (
    close_open_spans,
    is_completion_event,
    is_subagent_completion_event,
    process_completion,
    process_event,
    validate_subagent_visibility,
)
from agno.os.interfaces.agui.interrupts import validate_interrupt_outcome
from agno.os.interfaces.agui.state import StreamState
from agno.run.agent import RunCompletedEvent, RunOutputEvent
from agno.run.base import BaseRunOutputEvent
from agno.run.team import TeamRunOutputEvent
from agno.utils.log import log_exception


def _failure_message(error: Exception) -> str:
    """What a failed stream tells the client: the exception's text, or its type name.

    The text is read through the same guard every other label is. Rendering an
    exception runs its own ``__str__``, which can raise, and this runs before the
    cleanup's try: unguarded, an exception that cannot describe itself would
    close no span and no subagent lane, and would replace the run's real failure
    with the one raised while naming it.
    """
    return readable_value(error, "a stream failure message") or type(error).__name__


def _failure_detail(error: Exception) -> str:
    """The failure as an operator needs it: what raised, and its text when it has any.

    Guarded exactly as the message above is, and for the same reason: this is
    what the failure is recorded with, so raising here would lose the record too.
    """
    message = readable_value(error, "a stream failure detail")
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


def _run_terminal(
    root_terminal: Optional[BaseRunOutputEvent], subagent_terminal: Optional[BaseRunOutputEvent]
) -> BaseRunOutputEvent:
    """The chunk the run terminal is built from.

    The top-level entity's own terminal is it whenever the stream carried one. A
    stream that ended on a subagent's terminal instead reported no other account
    of how the run ended, so that one is read as the run's: a run that died
    inside a subagent must not reach the client as a success. A stream that
    reported no terminal at all completed, which is what it was before subagent
    lineage existed.

    Which subagent terminal, when the stream carried more than one, is simply
    the last of them: nothing here ranks a failure above a later completion. A
    subagent that fails and is then followed by another subagent completing
    therefore ends the run as a completion, the failure surviving as that
    subagent's own ``SUBAGENT_ERROR`` and the line recording it. The pause
    variant is the same shape: a subagent pause followed by another subagent's
    completion loses the pending call, because the completion is what the run
    terminal is then built from and a completion has no pending call to prompt
    with. Both hold under every visibility, the default included, which has no
    other account of how the run ended either.
    """
    return root_terminal or subagent_terminal or RunCompletedEvent()


def _cleanup_events(state: StreamState, run_id: str, error_message: str) -> List[BaseEvent]:
    """The spans a failed stream still has to close, for a cleanup that cannot fail.

    The caller re-raises the run's own failure straight after this, and that
    failure is what the run terminal is built from. A raise from in here would
    replace it with one from the cleanup and skip the re-raise, so a cleanup
    that fails is recorded and yields what it can.
    """
    try:
        return close_open_spans(state, error_message)
    except Exception as error:
        log_exception(f"AG-UI stream for run {run_id} could not close its open spans: {_failure_detail(error)}")
        return []


def _run_terminal_events(
    state: StreamState,
    run_id: str,
    root_terminal: Optional[BaseRunOutputEvent],
    subagent_terminal: Optional[BaseRunOutputEvent],
) -> Tuple[List[BaseEvent], Optional[Exception]]:
    """The run terminal, or the span closes a terminal that could not be built owes.

    Building the terminal is failable work: it renders a paused run's own words,
    serializes the arguments of every call the pause prompts for, and copies the
    session state the run ends holding. Outside a guard, a raise from any of
    that sent no span end and no terminal, leaving the client spinning on a
    message and a tool call with the caller's own in-band error as the only
    account of how the run stopped.

    Guarded apart from the event loop rather than with it, because the two are
    different faults and the record has to say which happened: a source stream
    that died is the run's, a terminal that cannot be built is this interface's
    own. One guard could name only one of them, and would report a bug here as a
    dead source stream.

    The failure is returned rather than raised so the caller can send the closes
    before it propagates, and it does propagate: nothing may follow a run
    terminal, so a terminal written from here would leave the caller writing a
    second one, and a failure that is loud today must not go quiet because the
    stream around it was tidied up.
    """
    try:
        return process_completion(_run_terminal(root_terminal, subagent_terminal), state), None
    except Exception as error:
        log_exception(
            f"AG-UI stream for run {run_id} could not build its run terminal, closing open spans: "
            f"{_failure_detail(error)}"
        )
        return _cleanup_events(state, run_id, _failure_message(error)), error


def stream_agno_response_as_agui_events(
    response_stream: Iterator[Union[RunOutputEvent, TeamRunOutputEvent]],
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]] = None,
    subagent_visibility: Optional[str] = None,
    emit_interrupt_outcome: bool = False,
) -> Iterator[BaseEvent]:
    """Map the Agno response stream to AG-UI format."""
    state = StreamState(
        thread_id=thread_id,
        run_id=run_id,
        run_state=run_state,
        subagent_visibility=validate_subagent_visibility(subagent_visibility),
        emit_interrupt_outcome=validate_interrupt_outcome(emit_interrupt_outcome),
    )

    if run_state is not None:
        state.set_state_snapshot(run_state)

    terminal_chunk: Optional[BaseRunOutputEvent] = None
    subagent_terminal_chunk: Optional[BaseRunOutputEvent] = None

    try:
        for chunk in response_stream:
            if is_completion_event(chunk, state):
                terminal_chunk = chunk
            else:
                for event in process_event(chunk, state):
                    yield event
                # Read after the chunk was mapped, so the lane it decides
                # against is the one the mapper settled on for that chunk.
                if is_subagent_completion_event(chunk, state):
                    subagent_terminal_chunk = chunk
    except Exception as error:
        # A source stream that dies mid-run leaves every span this mapper opened
        # unclosed, so a client would keep spinning on a message, a tool call or
        # a member that never resolves. Close them and re-raise: the caller turns
        # the propagated failure into the run terminal, and nothing may follow a
        # terminal event. The failure is recorded first, with what raised and
        # where, because the cleanup that follows it is otherwise the only trace
        # that anything went wrong.
        log_exception(f"AG-UI stream for run {run_id} failed mid-run, closing open spans: {_failure_detail(error)}")
        for event in _cleanup_events(state, run_id, _failure_message(error)):
            yield event
        raise

    terminal, failure = _run_terminal_events(state, run_id, terminal_chunk, subagent_terminal_chunk)
    for event in terminal:
        yield event
    if failure is not None:
        raise failure


async def async_stream_agno_response_as_agui_events(
    response_stream: AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent]],
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]] = None,
    subagent_visibility: Optional[str] = None,
    emit_interrupt_outcome: bool = False,
) -> AsyncIterator[BaseEvent]:
    """Map the Agno response stream to AG-UI format."""
    state = StreamState(
        thread_id=thread_id,
        run_id=run_id,
        run_state=run_state,
        subagent_visibility=validate_subagent_visibility(subagent_visibility),
        emit_interrupt_outcome=validate_interrupt_outcome(emit_interrupt_outcome),
    )

    if run_state is not None:
        state.set_state_snapshot(run_state)

    terminal_chunk: Optional[BaseRunOutputEvent] = None
    subagent_terminal_chunk: Optional[BaseRunOutputEvent] = None

    try:
        async for chunk in response_stream:
            if is_completion_event(chunk, state):
                terminal_chunk = chunk
            else:
                for event in process_event(chunk, state):
                    yield event
                # Read after the chunk was mapped, so the lane it decides
                # against is the one the mapper settled on for that chunk.
                if is_subagent_completion_event(chunk, state):
                    subagent_terminal_chunk = chunk
    except Exception as error:
        # A source stream that dies mid-run leaves every span this mapper opened
        # unclosed, so a client would keep spinning on a message, a tool call or
        # a member that never resolves. Close them and re-raise: the caller turns
        # the propagated failure into the run terminal, and nothing may follow a
        # terminal event. The failure is recorded first, with what raised and
        # where, because the cleanup that follows it is otherwise the only trace
        # that anything went wrong.
        log_exception(f"AG-UI stream for run {run_id} failed mid-run, closing open spans: {_failure_detail(error)}")
        for event in _cleanup_events(state, run_id, _failure_message(error)):
            yield event
        raise

    terminal, failure = _run_terminal_events(state, run_id, terminal_chunk, subagent_terminal_chunk)
    for event in terminal:
        yield event
    if failure is not None:
        raise failure
