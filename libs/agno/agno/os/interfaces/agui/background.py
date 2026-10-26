"""Resumable background runs for the AG-UI interface.

A foreground AG-UI run streams straight out of the entity: when the client goes
away the run goes with it. A background run instead hands execution to Agno's
detached background streamer, which keeps executing after the client
disconnects and appends every event to the process event stream under a
monotonic index. This module is the bridge: it starts (or attaches to) such a
run and translates the buffered Agno events into AG-UI events.

Because every AG-UI event is derived from a buffered Agno event, each one can
be addressed by the position of its source event plus its position within the
events that source event produced. That pair is the resume cursor: a client
echoes the last pair it saw and receives everything after it, exactly once, in
the same order it would have seen on an uninterrupted connection.

Reproducing the same AG-UI events on a later connection requires the
translation to be a pure function of the buffered events, which drives two
choices here. ``StreamState`` is seeded with a namespace so message ids are
derived rather than random. And the translator works from its own copy of the
session state, so a run that was sent one is bracketed by a snapshot at each
end and emits no deltas in between, while one that was not is left alone. A
client that resumes has to keep sending state the same way it did, or the shape
of the run's last events shifts under it.

Three limits are inherited rather than introduced here. The event stream's
index is monotonic but not gapless. Its buffer is finite, so a run long enough
to be trimmed replays from wherever the buffer now starts, and a client whose
own next event has been trimmed away is told to start over rather than handed a
renumbered stream. And a custom event whose class declares its own fields
reaches every background connection as its base class, so its own fields are
gone and its AG-UI name is the base name, because the buffer stores the wire
form rather than the object.
"""

import asyncio
import contextlib
import copy
import json
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple, Union

from ag_ui.core import (
    BaseEvent,
    EventType,
    RawEvent,
    RunAgentInput,
    RunErrorEvent,
    RunStartedEvent,
    StateSnapshotEvent,
)

from agno.agent import Agent, RemoteAgent
from agno.os.event_streams import get_event_stream
from agno.os.event_streams.base import BaseEventStream
from agno.os.interfaces.agui.handlers import is_completion_event, process_completion, process_event
from agno.os.interfaces.agui.input import (
    extract_context,
    extract_media,
    extract_user_input,
    parse_client_tools,
    validate_state,
)
from agno.os.interfaces.agui.state import StreamState
from agno.run.agent import RunCompletedEvent, RunEvent
from agno.run.agent import RunErrorEvent as AgnoRunErrorEvent
from agno.run.base import BaseRunOutputEvent, RunStatus
from agno.run.team import team_run_output_event_from_dict
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.utils.log import log_debug, log_error, log_warning

# The forwarded_props key a client opts in with, and the event metadata key the
# server answers on. A client that sees the metadata knows the server honored
# the request and that reconnecting is safe; a server without this module
# simply never emits it, so the client stays on a single connection.
BACKGROUND_KEY = "agnoBackground"

# Cursor for the events emitted before the first buffered event exists.
_PREFIX_INDEX = -1

Cursor = Tuple[int, int]

# The events that end a run for a client. Everything else in a terminal group
# is either closing a span the client may already have been sent, or, for a run
# that paused, opening the ones its pending tool calls need.
_RUN_TERMINALS = (EventType.RUN_FINISHED, EventType.RUN_ERROR)

# Detached drains hold the only strong reference to the producer generator for
# the life of the run; without it a garbage collection between two client
# connections would close the run the client is about to come back for.
_DRAIN_TASKS: set = set()

# Run ids this process is between registering and starting. Two requests naming
# the same new run id would otherwise both pass the started-probe and start two
# producers into one buffer. This narrows that window to the gap between the
# probe and this set, which no await crosses. Across processes nothing
# arbitrates it, so two replicas handed the same new run id at the same moment
# can still both start one.
_STARTING_RUNS: Set[str] = set()

# Runs this process started, and the entity, session and user each belongs to.
# The detached streamer writes the run row from inside its own task, so a client
# that reconnects immediately can arrive before that write lands. This record
# answers that without widening what a caller may attach to, and is written
# before the run is registered so nothing can wait past it. The entry goes when
# the drain finishes, so the map holds only runs still in flight here.
_STARTED_RUNS: Dict[str, Tuple[str, str, Optional[str]]] = {}

# A background run persists its row before registering with the event stream,
# but this module registers the run first so that no event can be missed
# between starting and tailing. A reconnect landing inside that window would
# find no row yet, so the ownership read is retried briefly before refusing.
_OWNERSHIP_ATTEMPTS = 3
_OWNERSHIP_RETRY_SECONDS = 0.1

# How long a second connection waits for the first one's registration. Longer
# than the ownership budget: this is waiting on another request's work rather
# than on a write that has already been issued.
_REGISTRATION_ATTEMPTS = 20
_REGISTRATION_RETRY_SECONDS = 0.05


class _OwnershipCheckFailed(Exception):
    """The run's ownership could not be determined, as opposed to being denied."""


def background_requested(run_input: RunAgentInput) -> bool:
    """Whether this request asked for a resumable background run."""
    return _background_props(run_input) is not None


def background_cursor(run_input: RunAgentInput) -> Optional[Cursor]:
    """The last cursor the client received, or None on a first connection.

    Read whatever the request carries, including when it also says background
    is disabled: a resume position is a claim to be continuing an existing run,
    and the route has to see it to refuse rather than run the whole thing again.

    Raises:
        ValueError: the request carried a resume position that cannot be read.
            Ignoring it would silently replay the whole run as if the client
            had never connected.
    """
    props = _background_props(run_input, opted_in_only=False)
    if not isinstance(props, dict) or "lastEventIndex" not in props:
        return None
    event_index = props.get("lastEventIndex")
    sub_index = props.get("lastSubIndex", 0)
    if not _is_index(event_index) or not _is_index(sub_index):
        raise ValueError(f"Unreadable background resume position: {props!r}")
    return (int(event_index), int(sub_index))  # type: ignore[arg-type]


def supports_background(entity: Any) -> bool:
    """Whether this entity can run detached in this process.

    Remote entities execute in another process, so their events never reach
    this process's event stream and there is nothing here to replay. Detached
    execution also needs a database to persist run status, and a readable run
    history, without which there is no way to tell whose run a reconnection is
    naming.
    """
    if isinstance(entity, (RemoteAgent, RemoteTeam)):
        return False
    if getattr(entity, "db", None) is None:
        return False
    return callable(getattr(entity, "aget_run_output", None))


async def run_entity_background(
    entity: Union[Agent, Team],
    run_input: RunAgentInput,
    user_id: Optional[str] = None,
) -> AsyncIterator[BaseEvent]:
    """Run an Agent or Team detached, streaming its buffered events as AG-UI events.

    Starts the run when this process has never seen it, and attaches to the
    existing stream otherwise. Either way the events come from the buffer, so a
    first connection and a reconnection produce the same sequence.
    """
    run_id = run_input.run_id or str(uuid.uuid4())
    event_stream = get_event_stream()
    cursor: Optional[Cursor] = None
    highest: Optional[Cursor] = None

    try:
        cursor = background_cursor(run_input)
        session_state = validate_state(run_input.state, run_input.thread_id)
        already_started = await event_stream.get_run_status(run_id) is not None

        starting_here = run_id in _STARTING_RUNS

        if already_started or starting_here or cursor is not None:
            # Every path that attaches to a run rather than starting one goes
            # through the same check: the run id is client-supplied, so without
            # it a caller could name any run and read its events.
            try:
                owned = await _caller_owns_run(entity, run_id, run_input.thread_id, user_id)
            except _OwnershipCheckFailed:
                yield _stamp_refusal(f"Could not verify run {run_id}; try again", cursor)
                return
            if not owned:
                yield _stamp_refusal(f"Run {run_id} not found in this session", cursor)
                return
            if starting_here and not already_started:
                # Another request in this process is between registering this
                # run and starting it. Attaching is what a second connection
                # wants anyway, so wait rather than refuse.
                if not await _wait_for_registration(event_stream, run_id):
                    yield _stamp_refusal(f"Run {run_id} did not start", cursor)
                    return
            elif not already_started:
                # The run exists but its events do not, so there is nothing to
                # resume from. Saying so beats a silent empty stream.
                yield _stamp_refusal(f"Run {run_id} is no longer available for replay", cursor)
                return
        else:
            _STARTING_RUNS.add(run_id)
            _STARTED_RUNS[run_id] = (_entity_key(entity), run_input.thread_id, user_id)
            handed_over = False
            try:
                await event_stream.register_run(run_id, RunStatus.pending)
                await _start_detached_run(
                    entity, run_input, run_id=run_id, user_id=user_id, session_state=session_state
                )
                handed_over = True
            finally:
                _STARTING_RUNS.discard(run_id)
                if not handed_over:
                    # Includes cancellation: a run registered but never handed
                    # over is one no producer will ever finish, and a tail
                    # attached to it would wait out the stream's idle recheck.
                    _STARTED_RUNS.pop(run_id, None)
                    await _abandon_run(event_stream, run_id)

        async for event in _stream_buffered_run(
            event_stream=event_stream,
            run_id=run_id,
            thread_id=run_input.thread_id,
            session_state=session_state,
            cursor=cursor,
        ):
            delivered = _cursor_of(event)
            if delivered is not None and (highest is None or delivered > highest):
                highest = delivered
            yield event

    except Exception as e:
        log_error(f"Background AG-UI run {run_id} failed", exc_info=True)
        yield _stamp_refusal(str(e)[:200], highest if highest is not None else cursor)


def _entity_key(entity: Any) -> str:
    """A stable name for the entity a run was started on."""
    return str(getattr(entity, "id", None) or f"object:{id(entity)}")


def _is_index(value: Any) -> bool:
    # bool is an int subclass, and a JSON true reaching here as index 1 would
    # silently resume from the wrong place.
    return isinstance(value, int) and not isinstance(value, bool)


def _stamp_refusal(message: str, after: Optional[Cursor]) -> BaseEvent:
    """An error that ends the stream, positioned past everything before it.

    Stamped like any other event: the marker is what tells a client the server
    honors background runs, and a client that filters by cursor would drop an
    unmarked one. ``after`` is the last position the client is known to hold,
    which is what it has already been sent on this connection when there is
    one, and the resume position it asked from otherwise.
    """
    event_index = (after[0] + 1) if after is not None else _PREFIX_INDEX
    return _stamp(RunErrorEvent(type=EventType.RUN_ERROR, message=message), event_index, 0)


def background_error_event(message: str, after: Optional[Cursor]) -> BaseEvent:
    """A stamped terminal error, for callers outside this module's own stream."""
    return _stamp_refusal(message, after)


def background_cursor_of(event: BaseEvent) -> Optional[Cursor]:
    """The position a background event was delivered at, if it carries one."""
    return _cursor_of(event)


def _cursor_of(event: BaseEvent) -> Optional[Cursor]:
    marker = (event.metadata or {}).get(BACKGROUND_KEY)
    if not isinstance(marker, dict):
        return None
    event_index, sub_index = marker.get("eventIndex"), marker.get("subIndex")
    if not _is_index(event_index) or not _is_index(sub_index):
        return None
    return (int(event_index), int(sub_index))  # type: ignore[arg-type]


def _background_props(run_input: RunAgentInput, *, opted_in_only: bool = True) -> Optional[Union[Dict[str, Any], bool]]:
    """The background payload, or None when the request carries none."""
    forwarded = getattr(run_input, "forwarded_props", None)
    if not isinstance(forwarded, dict):
        return None
    props = forwarded.get(BACKGROUND_KEY)
    if props is True:
        return props
    if isinstance(props, dict) and (props.get("enabled", True) or not opted_in_only):
        return props
    return None


async def _wait_for_registration(event_stream: BaseEventStream, run_id: str) -> bool:
    for _ in range(_REGISTRATION_ATTEMPTS):
        if await event_stream.get_run_status(run_id) is not None:
            return True
        await asyncio.sleep(_REGISTRATION_RETRY_SECONDS)
    log_warning(f"Background AG-UI run {run_id} never registered while starting")
    return False


async def _caller_owns_run(entity: Any, run_id: str, thread_id: str, user_id: Optional[str]) -> bool:
    """Whether ``run_id`` belongs to the session the caller is authorized for.

    The thread id is checked before streaming starts, but the run id is
    separately client-supplied: without this an authorized caller could name
    any run id and read another session's events back out of the buffer.
    """
    if _STARTED_RUNS.get(run_id) == (_entity_key(entity), thread_id, user_id):
        return True
    reader = getattr(entity, "aget_run_output", None)
    if not callable(reader):
        log_warning(f"Cannot verify ownership of run {run_id}; refusing to attach")
        return False
    for attempt in range(_OWNERSHIP_ATTEMPTS):
        try:
            if await reader(run_id, session_id=thread_id, user_id=user_id) is not None:
                return True
        except Exception as e:
            # A storage failure is not a denial. Reporting it as one sends the
            # client off to restart a run that is still executing, so it is
            # retried like a missing row and only then reported as its own
            # kind of answer.
            log_error(f"Ownership check failed for run {run_id}: {e}")
            if attempt + 1 == _OWNERSHIP_ATTEMPTS:
                raise _OwnershipCheckFailed(str(e)) from e
        if attempt + 1 < _OWNERSHIP_ATTEMPTS:
            await asyncio.sleep(_OWNERSHIP_RETRY_SECONDS)
    return False


async def _start_detached_run(
    entity: Union[Agent, Team],
    run_input: RunAgentInput,
    *,
    run_id: str,
    user_id: Optional[str],
    session_state: Optional[Dict[str, Any]],
) -> None:
    """Hand the run to Agno's detached background streamer.

    The returned generator is drained and discarded: its SSE strings are a
    convenience for the connection that started the run, while the events this
    interface streams always come from the buffer so that the starting
    connection and every later one agree.
    """
    from agno.run.base import RunContext

    event_stream = get_event_stream()
    messages = run_input.messages or []
    images, audio, videos, files = extract_media(messages)
    client_tools = parse_client_tools(run_input.tools) or None
    ui_deps = extract_context(run_input.context)

    run_context = RunContext(
        run_id=run_id,
        session_id=run_input.thread_id,
        user_id=user_id,
        client_tools=client_tools,
        dependencies=ui_deps,
        session_state=session_state,
    )

    run_kwargs: Dict[str, Any] = {"run_context": run_context}
    if ui_deps:
        run_kwargs["add_dependencies_to_context"] = True

    producer = entity.arun(  # type: ignore[call-overload]
        input=extract_user_input(messages),
        stream=True,
        stream_events=True,
        background=True,
        session_id=run_input.thread_id,
        user_id=user_id,
        run_id=run_id,
        images=images or None,
        audio=audio or None,
        videos=videos or None,
        files=files or None,
        **run_kwargs,
    )

    async def _drain() -> None:
        try:
            async for _ in producer:
                pass
        except asyncio.CancelledError:
            # Whatever cancelled this, nothing else is going to end the run for
            # the clients attached to it.
            with contextlib.suppress(Exception):
                await asyncio.shield(event_stream.complete_run(run_id, RunStatus.error))
            raise
        except Exception:
            log_error(f"Background AG-UI run {run_id} failed", exc_info=True)
            # The producer is gone, so nothing else will end the run for the
            # clients attached to it.
            try:
                await event_stream.complete_run(run_id, RunStatus.error)
            except Exception:
                log_error(f"Failed to mark background AG-UI run {run_id} as errored", exc_info=True)

    task = asyncio.create_task(_drain())
    _DRAIN_TASKS.add(task)

    def _forget(finished: "asyncio.Task[None]") -> None:
        _DRAIN_TASKS.discard(finished)
        _STARTED_RUNS.pop(run_id, None)

    task.add_done_callback(_forget)
    log_debug(f"Started detached AG-UI run {run_id}")


async def _abandon_run(event_stream: BaseEventStream, run_id: str) -> None:
    """Finish and forget a run that was registered but never handed over.

    The terminal comes first so anything already attached ends rather than
    waiting out the stream's idle recheck. Forgetting it afterwards frees the
    id to be tried again, instead of answering "already ended" for the life of
    the process.
    """
    try:
        await event_stream.complete_run(run_id, RunStatus.error)
    except Exception:
        log_error(f"Failed to mark background AG-UI run {run_id} as errored", exc_info=True)
    try:
        await event_stream.cleanup_run(run_id)
    except Exception:
        log_error(f"Failed to drop the registration of background AG-UI run {run_id}", exc_info=True)


async def _stream_buffered_run(
    *,
    event_stream: BaseEventStream,
    run_id: str,
    thread_id: str,
    session_state: Optional[Dict[str, Any]],
    cursor: Optional[Cursor],
) -> AsyncIterator[BaseEvent]:
    """Translate a run's buffered and live Agno events into AG-UI events."""
    # The state is copied rather than shared: a background run mutates its own
    # session state inside the detached task, and a translation that read those
    # live mutations would emit deltas a later replay could not reproduce. It is
    # otherwise the foreground treatment, so a request that sends no state gets
    # no snapshots invented for it. A client that resumes must keep sending
    # state the same way, or the shape of the run's last events shifts under it.
    run_state: Optional[Dict[str, Any]] = copy.deepcopy(session_state) if session_state is not None else None
    state = StreamState(thread_id=thread_id, run_id=run_id, run_state=run_state)
    state.id_namespace = f"{thread_id}/{run_id}"
    # A replay can begin in the middle of a run, where a tool call completes
    # whose start has been trimmed away. Ending a span that was never opened is
    # invalid rather than merely incomplete.
    state.require_started_tool_calls = True
    if run_state is not None:
        state.set_state_snapshot(run_state)

    terminal_chunk: Optional[BaseRunOutputEvent] = None
    terminal_index = _PREFIX_INDEX
    last_index = _PREFIX_INDEX
    first_index: Optional[int] = None
    opened = False

    tail = event_stream.tail(run_id, last_event_index=None)
    try:
        async for event_index, sse_data in tail:
            if event_index <= _PREFIX_INDEX:
                # The positions at or below this one belong to the events the
                # run emits before its first buffered one.
                log_warning(f"Skipping a background AG-UI frame for run {run_id} at index {event_index}")
                continue
            if first_index is None:
                first_index = event_index
                if first_index > 0:
                    log_warning(
                        f"Background AG-UI run {run_id} replays from event {first_index}; "
                        "earlier events have been trimmed from the buffer"
                    )
                    if cursor is not None:
                        # Any trim at all defeats a resume. The translation is
                        # rebuilt from whatever the buffer still holds, so a
                        # message whose start was trimmed is opened again under
                        # a new id while the client's own copy of it is never
                        # closed. Say so rather than corrupt the stream.
                        yield _stamp_refusal(
                            f"Run {run_id} cannot be resumed from that position; "
                            "the events after it are no longer buffered",
                            cursor,
                        )
                        return
            last_index = max(last_index, event_index)

            if not opened:
                opened = True
                for event in _after(cursor, _PREFIX_INDEX, _opening_events(thread_id, run_id, run_state)):
                    yield event

            payload = _parse_frame(sse_data)
            if payload is None:
                continue
            chunk = _event_from_payload(payload)
            if chunk is None:
                # The foreground translation turns an event it has no handler
                # for into a raw event rather than dropping it; match that.
                for event in _after(cursor, event_index, [_raw_event(payload)]):
                    yield event
                continue
            if is_completion_event(chunk):
                # Held rather than emitted, and the last one wins: a team run
                # buffers each member's completion before its own, so the first
                # is not the end of anything the client is watching.
                terminal_chunk, terminal_index = chunk, event_index
                continue
            state.set_id_seed(event_index)
            for event in _after(cursor, event_index, process_event(chunk, state)):
                yield event
    finally:
        closer = getattr(tail, "aclose", None)
        if callable(closer):
            await closer()

    if first_index is None and cursor is not None:
        # Nothing at all came back, so there is no telling this from a buffer
        # that lost everything the client is waiting for.
        yield _stamp_refusal(f"Run {run_id} has no buffered events to resume from", cursor)
        return

    if not opened:
        for event in _after(cursor, _PREFIX_INDEX, _opening_events(thread_id, run_id, run_state)):
            yield event

    status = await _run_status(event_stream, run_id)
    if terminal_chunk is not None and _contradicts(terminal_chunk, status):
        # A team run buffers its members' completions, so a held one can look
        # like a finished run while the run itself died. The status wins.
        log_warning(f"Background AG-UI run {run_id} ended with status {status.value if status else None}")
        terminal_chunk = None

    if terminal_chunk is not None:
        final_chunk: BaseRunOutputEvent = terminal_chunk
        # Normally the terminal is the last thing buffered and keeps its own
        # index. When something follows it, which a team run does because its
        # members complete before it, the group goes after everything instead:
        # reusing an index already emitted would hand two events one address.
        final_index = terminal_index if terminal_index >= last_index else last_index + 1
    else:
        # The tail ended without a terminal event: the producer died, or the
        # stream's record of the run expired. The run's own status is the only
        # honest account of how it ended, and anything short of completed is
        # not a success to report as one.
        if status == RunStatus.completed:
            final_chunk = RunCompletedEvent()
        else:
            named = status.value.lower() if status is not None else "unknown"
            final_chunk = AgnoRunErrorEvent(content=f"Run ended without a result, last known status {named}")
        final_index = last_index + 1

    state.set_id_seed(final_index)
    for event in _closing_events(cursor, final_index, process_completion(final_chunk, state)):
        yield event


def _opening_events(thread_id: str, run_id: str, run_state: Optional[Dict[str, Any]]) -> List[BaseEvent]:
    events: List[BaseEvent] = [RunStartedEvent(type=EventType.RUN_STARTED, thread_id=thread_id, run_id=run_id)]
    if run_state is not None:
        events.append(StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copy.deepcopy(run_state)))
    return events


def _raw_event(payload: Dict[str, Any]) -> BaseEvent:
    return RawEvent(type=EventType.RAW, event=dict(payload), source="agno")


def _closing_events(cursor: Optional[Cursor], final_index: int, events: List[BaseEvent]) -> List[BaseEvent]:
    """The run's last events, filtered by the cursor but never left unfinished.

    Span-closing events the client already received are dropped like any other.
    The event that ends the run is not: a stream that closes without one leaves
    a client holding a connection that will never say anything again. So when
    the filter would take the terminal as well, only the terminal is re-issued,
    past whatever position the client sent.
    """
    delivered = _after(cursor, final_index, events)
    if any(event.type in _RUN_TERMINALS for event in delivered):
        return delivered
    reissue_index = max(final_index, cursor[0] if cursor is not None else _PREFIX_INDEX) + 1
    return delivered + [
        _stamp(event, reissue_index, sub_index)
        for sub_index, event in enumerate(event for event in events if event.type in _RUN_TERMINALS)
    ]


def _contradicts(terminal_chunk: BaseRunOutputEvent, status: Optional[RunStatus]) -> bool:
    """Whether the run's status says it ended worse than its last event claims."""
    if status not in (RunStatus.error, RunStatus.cancelled):
        return False
    event: Any = getattr(terminal_chunk, "event", None)
    event_value = str(event.value if hasattr(event, "value") else event)
    return event_value.removeprefix("Team") in (RunEvent.run_completed.value, RunEvent.run_paused.value)


async def _run_status(event_stream: BaseEventStream, run_id: str) -> Optional[RunStatus]:
    try:
        return await event_stream.get_run_status(run_id)
    except Exception:
        log_error(f"Could not read the status of background AG-UI run {run_id}", exc_info=True)
        return None


def _after(cursor: Optional[Cursor], event_index: int, events: List[BaseEvent]) -> List[BaseEvent]:
    """Stamp each event with its cursor and drop the ones already delivered."""
    out: List[BaseEvent] = []
    for sub_index, event in enumerate(events):
        if cursor is not None and (event_index, sub_index) <= cursor:
            continue
        out.append(_stamp(event, event_index, sub_index))
    return out


def _stamp(event: BaseEvent, event_index: int, sub_index: int) -> BaseEvent:
    metadata = dict(event.metadata) if event.metadata else {}
    metadata[BACKGROUND_KEY] = {"eventIndex": event_index, "subIndex": sub_index}
    event.metadata = metadata
    return event


def _parse_frame(sse_data: str) -> Optional[Dict[str, Any]]:
    """Read the event payload out of an SSE frame.

    The buffer hands back wire frames rather than objects on durable event
    streams, so the frame is the only shape both stream implementations share.
    """
    # Split on newlines only: the formatter writes non-ASCII through unescaped,
    # and str.splitlines would also break on characters that are legal inside a
    # JSON string, such as the line and paragraph separators.
    data_lines = [line[5:].strip() for line in sse_data.split("\n") if line.startswith("data:")]
    if not data_lines:
        log_warning("Skipping an AG-UI background frame with no data")
        return None
    try:
        payload = json.loads("\n".join(data_lines))
    except json.JSONDecodeError as e:
        log_warning(f"Skipping an unreadable AG-UI background frame: {e}")
        return None
    if not isinstance(payload, dict) or not payload.get("event"):
        log_warning("Skipping an AG-UI background frame that names no event")
        return None
    # Added when the event was written to the buffer rather than by the event
    # itself, so it is dropped here and neither translation path sees it.
    payload.pop("event_index", None)
    return payload


def _event_from_payload(payload: Dict[str, Any]) -> Optional[BaseRunOutputEvent]:
    """Rebuild the Agno event a frame was formatted from, or None if unknown."""
    try:
        return team_run_output_event_from_dict(dict(payload))
    except Exception as e:
        log_debug(f"No Agno event type for background frame {payload.get('event')}: {e}")
        return None
