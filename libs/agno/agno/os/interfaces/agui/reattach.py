"""Reattach support for background AG-UI runs.

A background run (started with ``forwarded_props: {"background": true}``)
keeps executing server-side after the client disconnects. A client that
reconnects can reattach with ``forwarded_props: {"reattach": true}`` on the
same thread_id/run_id: the buffered Agno events are replayed through the
AG-UI converter and collapsed into an idempotent MESSAGES_SNAPSHOT (AG-UI
events carry no sequence numbers, so replaying append-only text deltas would
double-render on clients that still hold partial content), then live events
continue streaming from the same converter state so message IDs stay
consistent. Runs whose buffer already expired are replayed from the database.
"""

import copy
import json
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union

from ag_ui.core import (
    BaseEvent,
    EventType,
    MessagesSnapshotEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from ag_ui.core.types import AssistantMessage, FunctionCall, ToolCall, ToolMessage
from ag_ui.core.types import Message as AGUIMessage

from agno.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.os.event_streams import get_event_stream
from agno.os.interfaces.agui.handlers import is_completion_event, process_completion, process_event
from agno.os.interfaces.agui.state import StreamState
from agno.run.agent import run_output_event_from_dict
from agno.run.base import BaseRunOutputEvent, RunStatus
from agno.run.team import team_run_output_event_from_dict
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.utils.log import log_debug, log_error

# Statuses where the run will produce no further events
_TERMINAL_STATUSES = (RunStatus.completed, RunStatus.error, RunStatus.cancelled, RunStatus.paused)


class _SnapshotBuilder:
    """Accumulates a replayed event prefix into a MESSAGES_SNAPSHOT.

    Runs replayed Agno events through the regular converter (so tool calls,
    reasoning lifecycle, and state deltas mutate StreamState exactly as they
    did live) and watches the converter's output to build full messages.
    """

    def __init__(self, thread_id: str, run_id: str, run_state: Optional[Dict[str, Any]] = None):
        self.state = StreamState(thread_id=thread_id, run_id=run_id, run_state=run_state)
        self.messages: List[AGUIMessage] = []
        self._assistant_by_id: Dict[str, AssistantMessage] = {}
        # tool_call_id -> [name, parent_message_id, args parts]
        self._tool_calls: Dict[str, Tuple[str, str, List[str]]] = {}
        self.finished = False
        self.last_event_index = -1
        self.latest_session_state: Optional[Dict[str, Any]] = copy.deepcopy(run_state) if run_state else None

    def consume(self, event: BaseRunOutputEvent, event_index: Optional[int] = None) -> None:
        if event_index is not None and event_index >= 0:
            self.last_event_index = max(self.last_event_index, event_index)
        if is_completion_event(event):
            output_events = process_completion(event, self.state)
        else:
            output_events = process_event(event, self.state)
        for out in output_events:
            self._watch(out)

    def _watch(self, event: BaseEvent) -> None:
        if isinstance(event, TextMessageStartEvent):
            message = AssistantMessage(id=event.message_id, content="")
            self._assistant_by_id[message.id] = message
            self.messages.append(message)
        elif isinstance(event, TextMessageContentEvent):
            existing = self._assistant_by_id.get(event.message_id)
            if existing is not None:
                existing.content = (existing.content or "") + event.delta
        elif isinstance(event, ToolCallStartEvent):
            self._tool_calls[event.tool_call_id] = (
                event.tool_call_name or "",
                event.parent_message_id or "",
                [],
            )
        elif isinstance(event, ToolCallArgsEvent):
            record = self._tool_calls.get(event.tool_call_id)
            if record is not None:
                record[2].append(event.delta or "")
        elif isinstance(event, ToolCallResultEvent):
            self.messages.append(
                ToolMessage(
                    id=event.message_id or event.tool_call_id,
                    content=event.content if isinstance(event.content, str) else json.dumps(event.content),
                    tool_call_id=event.tool_call_id,
                )
            )
        elif isinstance(event, StateSnapshotEvent):
            if isinstance(event.snapshot, dict):
                self.latest_session_state = copy.deepcopy(event.snapshot)
        elif isinstance(event, RunFinishedEvent):
            self.finished = True

    def snapshot_events(self) -> List[BaseEvent]:
        """Build the idempotent snapshot events for the replayed prefix."""
        # Attach accumulated tool calls to their parent assistant messages
        for tool_call_id, (name, parent_id, arg_parts) in self._tool_calls.items():
            parent = self._assistant_by_id.get(parent_id)
            if parent is None:
                continue
            call = ToolCall(id=tool_call_id, function=FunctionCall(name=name, arguments="".join(arg_parts)))
            parent.tool_calls = [*(parent.tool_calls or []), call]

        events: List[BaseEvent] = []
        if self.messages:
            events.append(MessagesSnapshotEvent(type=EventType.MESSAGES_SNAPSHOT, messages=self.messages))
        # Prefer the converter's live-tracked state (shared reference mutated
        # by the run) over snapshots captured along the way
        session_state = self.state.run_state if self.state.run_state is not None else self.latest_session_state
        if session_state is not None:
            events.append(StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copy.deepcopy(session_state)))
        return events


def _sse_payload_to_event(payload: str, is_team: bool) -> Optional[BaseRunOutputEvent]:
    """Recover an event object from a serialized SSE frame.

    The in-memory event stream replays raw event objects, but the Redis
    backend and all live tails carry SSE-formatted strings; the frame's data
    line is the event's own ``to_dict()`` JSON, so parsing it back is lossless
    for converter purposes. Unknown event types are skipped, never fatal.
    """
    data: Optional[Dict[str, Any]] = None
    for line in payload.splitlines():
        if line.startswith("data:"):
            try:
                data = json.loads(line[len("data:") :].strip())
            except json.JSONDecodeError:
                return None
            break
    if not isinstance(data, dict):
        return None
    try:
        if is_team:
            return team_run_output_event_from_dict(data)  # type: ignore[return-value]
        return run_output_event_from_dict(data)
    except Exception:
        log_debug(f"Reattach: skipping unserializable event of type '{data.get('event')}'")
        return None


def _normalize_payload(payload: Any, is_team: bool) -> Optional[BaseRunOutputEvent]:
    """Normalize an event-stream payload (raw object or SSE string) to an event."""
    if isinstance(payload, str):
        return _sse_payload_to_event(payload, is_team)
    return payload


async def find_active_run_id(
    entity: Union[Agent, Team],
    thread_id: str,
    user_id: Optional[str] = None,
) -> Optional[str]:
    """Resolve the thread's in-progress run for sentinel reattach (run_id="").

    A client that never held the original run_id (fresh window, new device,
    incognito) can reattach with an empty run_id; the server finds the run
    itself. Only PENDING/RUNNING runs qualify — PAUSED runs wait on HITL
    input and follow the resume flow instead.

    Candidates come from the stored session (already scoped to session_id +
    user_id, so the lookup doubles as the run-thread binding check), then
    each is probed against the event stream: a PENDING/RUNNING row the buffer
    no longer knows (e.g. the server restarted, or the run died without a
    terminal write) is skipped, so callers get None and the client falls back
    to loading history. Runs are stored oldest-first, so scan in reverse.
    """
    if getattr(entity, "db", None) is None:
        return None
    session = await entity.aget_session(session_id=thread_id, user_id=user_id)
    if session is None or not session.runs:
        return None
    event_stream = get_event_stream()
    for run in reversed(session.runs):
        if getattr(run, "status", None) not in (RunStatus.pending, RunStatus.running):
            continue
        run_id = getattr(run, "run_id", None)
        if run_id and await event_stream.get_run_status(run_id) is not None:
            return run_id
    return None


async def find_reattach_target(
    entity: Union[Agent, Team],
    run_id: str,
    session_id: str,
    user_id: Optional[str] = None,
) -> Tuple[Optional[RunStatus], Optional[Any]]:
    """Locate a reattachable run. Returns (buffer_status, stored_run_output).

    (None, None) means the run exists in neither the event buffer nor the
    database — the caller answers 404 before any streaming starts.
    """
    event_stream = get_event_stream()
    buffer_status = await event_stream.get_run_status(run_id)
    if buffer_status is not None:
        return buffer_status, None
    if isinstance(entity, (RemoteAgent, RemoteTeam)) or getattr(entity, "db", None) is None:
        return None, None
    run_output = await entity.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)
    return None, run_output


async def reattach_run_events(
    entity: Union[Agent, Team],
    thread_id: str,
    run_id: str,
    user_id: Optional[str] = None,
    buffer_status: Optional[RunStatus] = None,
    stored_run: Optional[Any] = None,
) -> AsyncIterator[BaseEvent]:
    """Reattach to a background run: snapshot the missed prefix, then go live.

    ``buffer_status``/``stored_run`` come pre-fetched from
    ``find_reattach_target`` so the route handler could 404 before streaming.
    """
    is_team = isinstance(entity, Team)
    yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=thread_id, run_id=run_id)

    event_stream = get_event_stream()

    # Path 1: run not in the buffer — replay the stored terminal run from the DB
    if buffer_status is None:
        if stored_run is None:
            yield RunErrorEvent(type=EventType.RUN_ERROR, message=f"Run {run_id} not found")
            return
        builder = _SnapshotBuilder(
            thread_id=thread_id, run_id=run_id, run_state=getattr(stored_run, "session_state", None)
        )
        for position, event in enumerate(getattr(stored_run, "events", None) or []):
            builder.consume(event, event_index=position)
        for event in builder.snapshot_events():
            yield event
        status = getattr(stored_run, "status", None)
        status_value = status.value if status is not None and hasattr(status, "value") else status
        if builder.finished or status_value == "completed":
            yield RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=run_id)
        else:
            yield RunErrorEvent(type=EventType.RUN_ERROR, message=f"Run ended with status: {status_value or 'unknown'}")
        return

    # Path 2: run in the buffer — replay the buffered prefix into a snapshot
    builder = _SnapshotBuilder(thread_id=thread_id, run_id=run_id)
    try:
        replayed = await event_stream.replay(run_id, last_event_index=None)
    except Exception as e:
        log_error(f"Reattach: event stream replay failed for run {run_id}: {e}")
        yield RunErrorEvent(type=EventType.RUN_ERROR, message="event stream unavailable")
        return
    for event_index, payload in replayed:
        event = _normalize_payload(payload, is_team)
        if event is not None:
            builder.consume(event, event_index=event_index)

    # Terminal runs end right after the snapshot
    if buffer_status in _TERMINAL_STATUSES:
        for event in builder.snapshot_events():
            yield event
        if builder.finished or buffer_status in (RunStatus.completed, RunStatus.paused):
            yield RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=run_id)
        else:
            yield RunErrorEvent(type=EventType.RUN_ERROR, message=f"Run ended with status: {buffer_status.value}")
        return

    # Path 3: run still active — snapshot, then stream live events through the
    # same converter state so message IDs continue consistently
    for event in builder.snapshot_events():
        yield event

    async for event_index, payload in event_stream.tail(run_id, last_event_index=builder.last_event_index):
        event = _normalize_payload(payload, is_team)
        if event is None:
            continue
        if is_completion_event(event):
            for out in process_completion(event, builder.state):
                yield out
        else:
            for out in process_event(event, builder.state):
                yield out
