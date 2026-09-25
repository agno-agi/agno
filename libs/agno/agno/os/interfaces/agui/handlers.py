import copy
import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

try:
    import ag_ui.core  # noqa: F401
except ImportError as e:
    # The AG-UI interface is an optional extra; say which package is missing
    # rather than surfacing a bare ModuleNotFoundError from deep in the import.
    raise ImportError("`ag_ui` not installed. Please install it with `pip install -U ag-ui-protocol`") from e

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    EventType,
    RawEvent,
    ReasoningEndEvent,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    ReasoningStartEvent,
    RunFinishedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from ag_ui.core import (
    RunErrorEvent as AGUIRunErrorEvent,
)

try:
    from ag_ui.core import (
        SubagentErrorEvent,
        SubagentFinishedEvent,
        SubagentStartedEvent,
    )

    SUBAGENT_EVENTS_AVAILABLE = True
except ImportError:  # ag-ui-protocol older than the subagent lineage events
    from agno.utils.log import log_debug

    SUBAGENT_EVENTS_AVAILABLE = False
    log_debug(
        "AG-UI subagent lineage events (SUBAGENT_STARTED / SUBAGENT_FINISHED / SUBAGENT_ERROR) are "
        "missing from the installed ag_ui.core, so Team member attribution is unavailable. "
        "Please upgrade with `pip install -U ag-ui-protocol`."
    )

from agno.models.response import ToolExecution
from agno.os.interfaces.agui.state import (
    ROOT_LANE,
    SUBAGENT_VISIBILITY_ATTRIBUTED,
    SUBAGENT_VISIBILITY_INLINE,
    SUBAGENT_VISIBILITY_VALUES,
    StreamState,
)
from agno.os.interfaces.agui.utils import to_json_str
from agno.reasoning.step import ReasoningStep
from agno.run.agent import RunContentEvent, RunEvent
from agno.run.agent import RunPausedEvent as AgentRunPausedEvent
from agno.run.base import BaseRunOutputEvent
from agno.run.requirement import RunRequirement
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.run.team import TeamRunEvent
from agno.utils.log import log_error, log_warning
from agno.utils.message import get_text_from_message
from agno.utils.string import url_safe_string

EventHandler = Callable[[BaseRunOutputEvent, StreamState], List[BaseEvent]]

# The events that carry a ``subagent_run_id`` and are stamped with the lane of
# the chunk they were mapped from, so the stream is self-describing per event and
# a client never has to reconstruct attribution from an earlier event. Each type
# is kept against the class this interface builds it from, which is what lets
# the startup check feature-detect the field on every one of them.
# Run-lifecycle and SUBAGENT_* events are excluded: the former belong to the run
# as a whole, the latter carry their subagent id in a dedicated field. STATE_* is
# excluded too, because a team's session state is one shared document; a client
# filtering by lane must not lose state written during a delegation.
_ATTRIBUTABLE_EVENT_CLASSES: Dict[EventType, Type[BaseEvent]] = {
    EventType.TEXT_MESSAGE_START: TextMessageStartEvent,
    EventType.TEXT_MESSAGE_CONTENT: TextMessageContentEvent,
    EventType.TEXT_MESSAGE_END: TextMessageEndEvent,
    EventType.TOOL_CALL_START: ToolCallStartEvent,
    EventType.TOOL_CALL_ARGS: ToolCallArgsEvent,
    EventType.TOOL_CALL_END: ToolCallEndEvent,
    EventType.TOOL_CALL_RESULT: ToolCallResultEvent,
    EventType.REASONING_START: ReasoningStartEvent,
    EventType.REASONING_MESSAGE_START: ReasoningMessageStartEvent,
    EventType.REASONING_MESSAGE_CONTENT: ReasoningMessageContentEvent,
    EventType.REASONING_MESSAGE_END: ReasoningMessageEndEvent,
    EventType.REASONING_END: ReasoningEndEvent,
    EventType.CUSTOM: CustomEvent,
    EventType.RAW: RawEvent,
}

# Derived from the classes, so the set the stamp tests an event against and the
# classes the startup check feature-detects cannot drift apart.
_SUBAGENT_ATTRIBUTABLE_EVENT_TYPES = frozenset(_ATTRIBUTABLE_EVENT_CLASSES)

# The field those events carry the lane in.
_SUBAGENT_RUN_ID_FIELD = "subagent_run_id"

# The code a cancelled subagent's terminal carries, so a client can tell a
# cancellation from a failure.
_SUBAGENT_CANCELLED_CODE = "cancelled"

# The pending-call lists a paused run's terminal carries, in the order the pause
# prompt reads them. One pending call can be flagged for several of these at
# once, and is then listed by each of them; the prompt sends it once per
# listing, whichever visibility is set, which is what this interface has always
# done.
_PAUSE_TOOL_LISTS: Tuple[str, ...] = (
    "tools_awaiting_external_execution",
    "tools_requiring_confirmation",
    "tools_requiring_user_input",
)

# What the ``hidden`` record of a subagent terminal says about the text beside
# it. Such a terminal can be the only account the stream carries of how the run
# stopped, and is then read as the run's own, so the text is on the wire even
# though nothing on the wire names the subagent it came from. Written once and
# shared by every terminal that can end the run that way, so a record of one of
# them cannot claim the client was told nothing.
_REASON_STILL_REACHES_THE_CLIENT = "the run terminal still reports this reason if the run ends here"


def _chunk_run_ids(chunk: BaseRunOutputEvent) -> Tuple[Optional[str], Optional[str]]:
    """The chunk's own run id, and the run that delegated to it when there is one."""
    return getattr(chunk, "run_id", None), getattr(chunk, "parent_run_id", None)


def _readable(value: Any, described: str) -> Optional[str]:
    """A value as display text, or None when it is falsy or reading it raises.

    A name reaches the chunk straight off the caller's own Agent or Team, so
    rendering one can raise. A label is never worth ending a run for, so a value
    that cannot be read is recorded and treated as absent.

    Falsy is absent too, and deliberately: every caller is choosing a label, and
    the empty string, an empty mapping and zero are all nothing to show, so each
    of them falls through to whatever the caller offers next rather than
    reaching the wire as ``""`` or ``"0"``. A caller that has to tell an empty
    value from a missing one cannot use this.
    """
    try:
        return str(value) if value else None
    except Exception as error:
        log_warning(f"AG-UI could not read {described}: {error}")
        return None


def _member_id(chunk: BaseRunOutputEvent) -> Optional[str]:
    """The member id the framework's delegation tools name this run's entity by.

    Derived as ``agno.utils.team.get_member_id`` derives it: an explicit id
    verbatim, and otherwise the url-safe form of the member's name. Initializing
    a Team assigns an id to every Agent and Team member it holds, so a member of
    a locally built Team is matched by its id and never reaches the name branch.
    That branch is for the chunks that assignment does not stand behind: a
    remote entity's are rebuilt from what its stream sent rather than stamped by
    this process, and reading the id alone would leave a member arriving that
    way unmatched against the call that spawned it.
    """
    for id_attribute, name_attribute in (("agent_id", "agent_name"), ("team_id", "team_name")):
        explicit = _readable(getattr(chunk, id_attribute, None), f"a member id from {id_attribute}")
        if explicit:
            return explicit
        name = _readable(getattr(chunk, name_attribute, None), f"a member name from {name_attribute}")
        if name:
            return url_safe_string(name)
    return None


def _subagent_name(chunk: BaseRunOutputEvent, subagent_run_id: str) -> str:
    for attribute in ("agent_name", "team_name", "agent_id", "team_id"):
        name = _readable(getattr(chunk, attribute, None), f"a subagent name from {attribute}")
        if name:
            return name
    return subagent_run_id


def _stamp_lane(events: List[BaseEvent], lane: Optional[str]) -> List[BaseEvent]:
    """Attribute events to a subagent lane, leaving any explicit id in place.

    The protocol models accept extra attributes, so a plain write would succeed on
    an event type that does not declare the field and hand the client an
    undeclared one instead. Only a declared field is ever written. A protocol
    that declares none on an event this interface attributes is refused when the
    routes are mounted, so nothing reaches the skip below; it is a skip rather
    than a raise because this runs while a client is already reading the stream,
    where nothing may abort the run.
    """
    if lane is None:
        return events
    for event in events:
        if event.type not in _SUBAGENT_ATTRIBUTABLE_EVENT_TYPES:
            continue
        if _SUBAGENT_RUN_ID_FIELD not in type(event).model_fields:
            continue
        if getattr(event, _SUBAGENT_RUN_ID_FIELD, None) is None:
            setattr(event, _SUBAGENT_RUN_ID_FIELD, lane)
    return events


def _announce_subagent(chunk: BaseRunOutputEvent, state: StreamState, lane: Optional[str]) -> List[BaseEvent]:
    """Emit SUBAGENT_STARTED the first time a subagent's lane appears.

    A terminal is final for the id it names, so a lane that already closed is
    never announced again: trailing output from a finished subagent stays
    attributed to it without giving one invocation two lifecycles.

    The parent named here is always a member this stream has already announced.
    A parent link the client cannot resolve against an announcement it has
    already received is a forward reference, which a validating client rejects,
    so a grandchild whose first event outruns its parent's is announced with no
    parent and sits directly under the run. A parent whose own terminal has
    already gone out is left out for a different reason: it can no longer
    terminate after a child of its own, and its delegation call is no longer a
    link a client can follow.

    A parent left out takes the rest of the delegation with it: no parent tool
    call, no parent message and no description. Those are read from the
    delegating lane's own open calls, and a lane that cannot be named has none
    to read; falling back to the top-level entity's would announce this
    subagent with the leader's call, the leader's parent message and the
    leader's task text as its own description.
    """
    if lane is None or lane in state.open_subagents or lane in state.closed_subagents:
        return []

    member_id = _member_id(chunk)
    _, parent_run_id = _chunk_run_ids(chunk)
    parent_lane, delegation_call_id = state.delegating_lane_for(parent_run_id, member_id)
    name = _subagent_name(chunk, lane)

    state.open_subagent(lane, name=name, parent_lane=parent_lane)
    return [
        SubagentStartedEvent(
            type=EventType.SUBAGENT_STARTED,
            subagent_run_id=lane,
            name=name,
            description=state.delegation_task(parent_lane, delegation_call_id),
            parent_subagent_run_id=parent_lane,
            parent_tool_call_id=delegation_call_id,
            parent_message_id=state.delegation_parent_message_id(parent_lane, delegation_call_id),
        )
    ]


def _correlation(details: Optional[Dict[str, Any]]) -> str:
    """The identifiers that let an operator correlate a failure, absent ones omitted.

    Every value comes off the run that failed, so rendering one can raise, and
    each is read through the same guard every other label is: a value that
    cannot be read is left out. Building the line an operator reads is never
    worth ending a run for. That holds for both callers: the lane terminal,
    which has already closed the lane, and the withheld-failure record under
    ``hidden``, where the lane never reaches the wire at all and this line is
    the only trace of the failure.
    """
    rendered: List[str] = []
    for key, value in (details or {}).items():
        if value is None:
            continue
        text = _readable(value, f"the {key} of a subagent failure")
        if text is not None:
            rendered.append(f", {key}={text}")
    return "".join(rendered)


def _lane_finished(state: StreamState, lane: Optional[str], result: Any = None) -> List[BaseEvent]:
    """One lane's terminal event, and nothing at all when it already owns one.

    Only this lane is terminated, and only its own message and reasoning spans
    are closed, which is the same rule output trailing a terminal follows. A
    lane below this one belongs to a run that has not stopped, and a tool call
    still open here belongs to work that can still report its own end; ending
    either from here sends a terminal for a member that is still going and
    discards whatever it reports afterwards.

    No outcome is ever attached. The protocol pairs a suspended subagent with a
    run-level interrupt outcome, and this interface emits none, so a lone
    suspended half would tell a client the subagent is waiting while the run says
    it finished.
    """
    if lane is None:
        return []
    already_closed = lane in state.closed_subagents
    state.close_subagent(lane)
    if already_closed:
        return []
    return [
        *_close_lane_messages(state, lane),
        SubagentFinishedEvent(type=EventType.SUBAGENT_FINISHED, subagent_run_id=lane, result=result),
    ]


def _lane_errored(
    state: StreamState,
    lane: Optional[str],
    message: str,
    code: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> List[BaseEvent]:
    """One lane's error terminal, or the record of a failure that arrives too late.

    Closes and terminates exactly what the finish path does, for the same
    reasons, and the failure belongs to this lane alone: a member below it never
    failed and must not be made to report somebody else's error.

    A lane that already terminated gets no second terminal: a terminal is final
    for the id it names, and a second one would be a protocol violation. The
    failure is still recorded, saying that the lane had already terminated and
    that nothing about it reached the client, so a failure no client can be told
    about is not a failure nobody is told about.

    The failure is recorded here and nowhere else, once either way. The wire
    event carries only a message and a code, so whatever identifiers would let
    an operator correlate the failure travel in ``details``.
    """
    if lane is None:
        return []
    already_closed = lane in state.closed_subagents
    state.close_subagent(lane)
    correlation = _correlation(details)
    if already_closed:
        log_error(
            f"AG-UI subagent lane {lane} reported a failure after it had already terminated, so no "
            f"SUBAGENT_ERROR was sent for it (code={code}): {message}{correlation}"
        )
        return []
    log_error(f"AG-UI subagent lane {lane} ended in failure (code={code}): {message}{correlation}")
    return [
        *_close_lane_messages(state, lane),
        SubagentErrorEvent(type=EventType.SUBAGENT_ERROR, subagent_run_id=lane, message=message, code=code),
    ]


def _drain_subagents(state: StreamState) -> List[BaseEvent]:
    """Terminate every subagent still open when the run ends.

    A subagent's terminal comes from exactly two places: its own terminal event,
    and this drain. The drain covers one whose own terminal never arrived, for
    instance because the run paused inside it, or because it was still streaming
    when the run ended. A run that failed goes down the error path instead, which
    errors these lanes rather than finishing them. Deepest first, so a child's
    terminal precedes its parent's.
    """
    events: List[BaseEvent] = []
    for lane in state.subagents_deepest_first():
        events.extend(_lane_finished(state, lane))
    return events


def _error_open_subagents(state: StreamState, error_message: str) -> List[BaseEvent]:
    """Error every subagent still open when the run's stream failed.

    Deepest first, so a child's terminal precedes its parent's.
    """
    events: List[BaseEvent] = []
    for lane in state.subagents_deepest_first():
        events.extend(_lane_errored(state, lane, error_message))
    return events


def _extract_response_chunk_content(response: RunContentEvent) -> str:
    # RunContentEvent can carry text in .messages (list) or .content (direct)
    # AG-UI needs a plain string for TEXT_MESSAGE_CONTENT delta
    if hasattr(response, "messages") and response.messages:  # type: ignore
        for msg in reversed(response.messages):  # type: ignore
            if hasattr(msg, "role") and msg.role == "assistant" and hasattr(msg, "content") and msg.content:
                return get_text_from_message(msg.content)
    return get_text_from_message(response.content) if response.content is not None else ""


def _extract_team_response_chunk_content(response: TeamRunContentEvent) -> str:
    # Team responses nest member outputs — fold them into one text delta
    members_content = []
    if hasattr(response, "member_responses") and response.member_responses:  # type: ignore
        for member_resp in response.member_responses:  # type: ignore
            if isinstance(member_resp, RunContentEvent):
                member_content = _extract_response_chunk_content(member_resp)
                if member_content:
                    members_content.append(f"Team member: {member_content}")
            elif isinstance(member_resp, TeamRunContentEvent):
                member_content = _extract_team_response_chunk_content(member_resp)
                if member_content:
                    members_content.append(f"Team member: {member_content}")
    members_response = "\n".join(members_content) if members_content else ""
    main_content = get_text_from_message(response.content) if response.content is not None else ""
    return main_content + members_response


def _format_reasoning_step(step: Optional[ReasoningStep], step_number: int = 0) -> str:
    """Format a ReasoningStep as text for REASONING_MESSAGE_CONTENT."""
    if step is None:
        return ""
    parts: List[str] = []
    title = step.title or "Thinking"
    if step_number > 0:
        parts.append(f"## Step {step_number}: {title}")
    else:
        parts.append(f"## {title}")
    if step.reasoning:
        parts.append(step.reasoning)
    if step.action:
        parts.append(f"Action: {step.action}")
    if step.result:
        parts.append(f"Result: {step.result}")
    if step.confidence is not None:
        parts.append(f"Confidence: {step.confidence}")
    return "\n".join(parts) + "\n\n" if parts else ""


def _emit_state_delta(state: StreamState) -> List[BaseEvent]:
    if state.run_state is None:
        return []
    ops = state.compute_state_delta(state.run_state)
    if ops is None:
        return []
    state.set_state_snapshot(state.run_state)
    return [StateDeltaEvent(type=EventType.STATE_DELTA, delta=ops)]


def _end_lane_reasoning(state: StreamState, lane_key: Optional[str]) -> List[BaseEvent]:
    lane = state.lane(lane_key)
    if lane.reasoning_message_id is None:
        return []
    reasoning_id = lane.reasoning_message_id
    lane.reasoning_message_id = None
    lane.reasoning_step_count = 0
    return [
        ReasoningMessageEndEvent(type=EventType.REASONING_MESSAGE_END, message_id=reasoning_id),
        ReasoningEndEvent(type=EventType.REASONING_END, message_id=reasoning_id),
    ]


def _end_lane_tool_calls(state: StreamState, lane_key: Optional[str]) -> List[BaseEvent]:
    events: List[BaseEvent] = []
    # In the order the run opened them: these ends are swept out of a set of
    # open calls, whose iteration order would otherwise decide the wire order.
    for tool_call_id in state.active_tool_calls_in_order():
        if state.lane_of_tool_call(tool_call_id) != lane_key:
            continue
        if tool_call_id not in state.ended_tool_call_ids:
            events.append(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call_id))
            state.end_tool_call(tool_call_id)
    return events


def _end_lane_text_message(state: StreamState, lane_key: Optional[str]) -> List[BaseEvent]:
    lane = state.lane(lane_key)
    if not lane.text_message_open:
        return []
    lane.text_message_open = False
    return [TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=lane.text_message_id)]


def _close_lane_spans(state: StreamState, lane_key: Optional[str]) -> List[BaseEvent]:
    """End every reasoning, tool call and text message still open in one lane."""
    events = [
        *_end_lane_reasoning(state, lane_key),
        *_end_lane_tool_calls(state, lane_key),
        *_end_lane_text_message(state, lane_key),
    ]
    return _stamp_lane(events, lane_key)


def _close_lane_messages(state: StreamState, lane_key: Optional[str]) -> List[BaseEvent]:
    """End the reasoning and text spans open in one lane, leaving its tool calls open."""
    events = [*_end_lane_reasoning(state, lane_key), *_end_lane_text_message(state, lane_key)]
    return _stamp_lane(events, lane_key)


def _close_lane_tool_calls(state: StreamState, lane_key: Optional[str]) -> List[BaseEvent]:
    """End every tool call still open in one lane."""
    return _stamp_lane(_end_lane_tool_calls(state, lane_key), lane_key)


def _close_all_lane_spans(state: StreamState) -> List[BaseEvent]:
    """End every span still open in any lane, and every tool call still open.

    Every lane, not only the root and the ones still being drained: a text or
    reasoning span opened in a lane whose subagent already terminated would
    otherwise still be open when the run terminal arrives, and a conforming
    client rejects a run that ends inside a message. The lanes iterated include
    every lane that owns an open tool call, so no tool call reaches the run
    terminal without an end event. Children before parents.
    """
    events: List[BaseEvent] = []
    for lane_key in state.lanes_deepest_first():
        events.extend(_close_lane_spans(state, lane_key))
    return events


def _close_run_end_spans(
    state: StreamState,
    terminate_members: Callable[[], List[BaseEvent]],
    interlude: Optional[Callable[[], List[BaseEvent]]] = None,
) -> List[BaseEvent]:
    """The single closing order both run-ending paths use.

    Everything the run end emits after the sweep lands outside every span the
    stream had open, which is the one position that holds for all three
    visibilities. ``interlude`` is the pause prompt: it opens a message and tool
    calls of its own, so it goes out once no message and no tool call is still
    open, and before ``terminate_members``, because the calls it carries are
    stamped with the members it is prompting for and nothing may carry a member
    after that member's terminal. That leaves the member terminals last, outside
    the delegation call that spawned them rather than inside it.

    With member lanes on the wire the spans close in two passes, children before
    parents in each, so a member's terminal never lands inside another lane's
    message. With none there is no terminal to position, so one pass per lane
    closes everything and the emitted stream is exactly what it was before member
    attribution existed.
    """
    events: List[BaseEvent] = []
    if not state.announced_subagents:
        # No lane was ever announced, so no lane can be open and there is nothing
        # for ``terminate_members`` to produce.
        events.extend(_close_all_lane_spans(state))
        if interlude is not None:
            events.extend(interlude())
        return events

    for lane_key in state.lanes_deepest_first():
        events.extend(_close_lane_messages(state, lane_key))
    for lane_key in state.lanes_deepest_first():
        events.extend(_close_lane_tool_calls(state, lane_key))
    if interlude is not None:
        events.extend(interlude())
    events.extend(terminate_members())
    return events


def on_run_content(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []

    event = getattr(chunk, "event", None)
    if event == RunEvent.run_content:
        content = _extract_response_chunk_content(chunk)  # type: ignore
    elif event == TeamRunEvent.run_content:
        content = _extract_team_response_chunk_content(chunk)  # type: ignore
    else:
        content = ""

    if not state.text_message_open:
        message_id = state.open_text_message()
        state.clear_pending_tool_calls_parent_id()
        events.append(
            TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=message_id,
                role="assistant",
            )
        )

    if content:
        events.append(
            TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=state.text_message_id,
                delta=content,
            )
        )

    return events


def on_tool_call_started(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []
    tool = getattr(chunk, "tool", None)
    if tool is None:
        return events

    # Close open text message before tool call
    if state.text_message_open:
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id))
        state.set_pending_tool_calls_parent_id(state.text_message_id)
        state.close_text_message()

    parent_message_id = state.get_parent_message_id_for_tool_call()

    # Create empty parent message if none exists (AG-UI protocol requirement)
    if not parent_message_id:
        parent_message_id = str(uuid.uuid4())
        events.append(
            TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=parent_message_id,
                role="assistant",
            )
        )
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=parent_message_id))
        state.set_pending_tool_calls_parent_id(parent_message_id)

    events.append(
        ToolCallStartEvent(
            type=EventType.TOOL_CALL_START,
            tool_call_id=tool.tool_call_id,
            tool_call_name=tool.tool_name,
            parent_message_id=parent_message_id,
        )
    )

    events.append(
        ToolCallArgsEvent(
            type=EventType.TOOL_CALL_ARGS,
            tool_call_id=tool.tool_call_id,
            delta=json.dumps(tool.tool_args),
        )
    )

    state.start_tool_call(tool.tool_call_id)
    # A delegation is one of these calls; remembering the arguments and the parent
    # message lets a subagent be linked back to the exact call that spawned it
    # once its first event arrives.
    state.record_open_tool_call(tool.tool_call_id, tool.tool_name, tool.tool_args, parent_message_id)
    return events


def on_tool_call_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []
    tool = getattr(chunk, "tool", None)
    if tool is None:
        return events

    if tool.tool_call_id in state.ended_tool_call_ids:
        return events

    events.append(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool.tool_call_id))
    state.end_tool_call(tool.tool_call_id)

    if tool.result is not None:
        content = to_json_str(tool.result)
        events.append(
            ToolCallResultEvent(
                type=EventType.TOOL_CALL_RESULT,
                tool_call_id=tool.tool_call_id,
                content=content,
                role="tool",
                # Use tool_call_id as message_id so frontend can link result to the tool call
                message_id=tool.tool_call_id,
            )
        )

    events.extend(_emit_state_delta(state))
    return events


def on_reasoning_started(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []

    # Close open text message before reasoning
    if state.text_message_open:
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id))
        state.close_text_message()

    reasoning_id = state.start_reasoning()
    events.append(ReasoningStartEvent(type=EventType.REASONING_START, message_id=reasoning_id))
    events.append(
        ReasoningMessageStartEvent(type=EventType.REASONING_MESSAGE_START, message_id=reasoning_id, role="reasoning")
    )
    return events


def on_reasoning_content_delta(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []

    # Close open text message before reasoning
    if state.text_message_open:
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id))
        state.close_text_message()

    reasoning_id, is_new = state.ensure_reasoning_started()
    if is_new:
        events.append(ReasoningStartEvent(type=EventType.REASONING_START, message_id=reasoning_id))
        events.append(
            ReasoningMessageStartEvent(
                type=EventType.REASONING_MESSAGE_START, message_id=reasoning_id, role="reasoning"
            )
        )

    content = getattr(chunk, "reasoning_content", None)
    if content:
        events.append(
            ReasoningMessageContentEvent(
                type=EventType.REASONING_MESSAGE_CONTENT, message_id=reasoning_id, delta=content
            )
        )
    return events


def on_reasoning_step(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []

    # Close open text message before reasoning
    if state.text_message_open:
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id))
        state.close_text_message()

    reasoning_id, is_new = state.ensure_reasoning_started()
    if is_new:
        events.append(ReasoningStartEvent(type=EventType.REASONING_START, message_id=reasoning_id))
        events.append(
            ReasoningMessageStartEvent(
                type=EventType.REASONING_MESSAGE_START, message_id=reasoning_id, role="reasoning"
            )
        )

    step_num = state.next_reasoning_step()
    step_content = getattr(chunk, "content", None)
    delta = _format_reasoning_step(step_content, step_num)
    if delta:
        events.append(
            ReasoningMessageContentEvent(type=EventType.REASONING_MESSAGE_CONTENT, message_id=reasoning_id, delta=delta)
        )
    return events


def on_reasoning_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []

    if state.reasoning_message_id is not None:
        reasoning_id = state.reasoning_message_id
        events.append(ReasoningMessageEndEvent(type=EventType.REASONING_MESSAGE_END, message_id=reasoning_id))
        events.append(ReasoningEndEvent(type=EventType.REASONING_END, message_id=reasoning_id))
        state.end_reasoning()

    return events


def on_custom_event(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    try:
        custom_event_name = chunk.__class__.__name__
    except Exception:
        custom_event_name = str(getattr(chunk, "event", "CustomEvent"))

    try:
        custom_event_value: Any = chunk.to_dict()
    except Exception:
        custom_event_value = getattr(chunk, "content", None)

    return [CustomEvent(name=custom_event_name, value=custom_event_value)]


def on_unknown_event(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    try:
        raw_dict: Dict[str, Any] = chunk.to_dict()
    except Exception:
        raw_dict = {"event": str(getattr(chunk, "event", "unknown"))}
    return [RawEvent(type=EventType.RAW, event=raw_dict, source="agno")]


def close_open_spans(state: StreamState, error_message: str) -> List[BaseEvent]:
    """End every span and member lane the stream left open, without a run terminal.

    The open member lanes terminate as errored rather than finished, since the
    run they belonged to did not reach its own end. No run terminal is included:
    the caller owns that, and nothing may follow one on the wire.
    """
    return _close_run_end_spans(state, lambda: _error_open_subagents(state, error_message))


def _terminal_raw_event(chunk: BaseRunOutputEvent, state: StreamState) -> Optional[Dict[str, Any]]:
    """The failing chunk, verbatim, when it is the run's own account of the failure.

    A run that died inside a subagent has no terminal of its own, so the
    subagent's is read as the run's. The chunk itself is not: it is a subagent's
    record, and it names the subagent, its run and the run that delegated to it.
    Under ``hidden`` that is the identity the whole visibility withholds, put
    back on the wire by the event that follows the line recording the failure was
    kept off it; under ``attributed`` it is a subagent's own event dressed as the
    run's. Only the default embeds it, whose stream is what it was before member
    attribution existed.
    """
    if state.lane_for(*_chunk_run_ids(chunk)) is not ROOT_LANE:
        return None
    try:
        return chunk.to_dict()
    except Exception:
        return {"event": str(getattr(chunk, "event", "RunError"))}


def _terminal_failure(chunk: BaseRunOutputEvent, normalized: str) -> Tuple[str, Optional[str]]:
    """What a failed run terminal says, and the code it says it under.

    A cancellation is not a failure of the run's own making, so it reports the
    reason it was cancelled for under the same code a cancelled member's
    terminal carries. Only a subagent's cancellation ever reaches here: the
    top-level entity's is not read as a run terminal at all.
    """
    if normalized == RunEvent.run_cancelled.value:
        reason = _readable(getattr(chunk, "reason", None), "a cancelled run reason")
        return reason or "Run cancelled", _SUBAGENT_CANCELLED_CODE
    return str(getattr(chunk, "content", None) or "Run failed"), getattr(chunk, "error_type", None)


def on_run_error(chunk: BaseRunOutputEvent, state: StreamState, normalized: str) -> List[BaseEvent]:
    """Close open spans, then emit the terminal AG-UI error event. Nothing may follow RUN_ERROR.

    ``normalized`` is the chunk's event name, which says which kind of failed
    terminal this is. It is required rather than defaulted: a default would read
    every cancellation as a plain failure and report the wrong code for it.
    """
    raw_event = _terminal_raw_event(chunk, state)
    message, error_type = _terminal_failure(chunk, normalized)

    events: List[BaseEvent] = close_open_spans(state, message)
    events.append(
        AGUIRunErrorEvent(
            type=EventType.RUN_ERROR,
            message=message,
            code=error_type,
            rawEvent=raw_event,
        )
    )
    return events


@dataclass
class _PausedMemberLane:
    """A member lane a paused run needs on the wire, resolved but not yet announced."""

    run_id: str
    name: str
    parent_lane: Optional[str]
    delegation_call_id: Optional[str]


@dataclass
class _PausedToolCall:
    """One pending tool call a paused run can prompt the client with.

    The id and the name are both required rather than optional: an event cannot
    be built without the id and nothing can be rendered without the name, so a
    pending call missing either is dropped before it becomes one of these.
    """

    tool_call_id: str
    tool_name: str
    tool_args: Any
    lane: Optional[str]


@dataclass
class _PausedPrompt:
    """What a paused run's terminal asks the client to resolve.

    ``carried`` counts the pending calls the terminal listed before any were
    dropped or deduplicated, because whether the pause is announced at all
    turns on the terminal having listed one, never on what survived. ``dropped``
    counts the ones the client cannot be shown.

    ``content`` is the paused run's own text and ``content_lane`` the lane that
    text belongs to. A pause reported by a member carries the member's words, so
    they go out on the member's lane or not at all; the leader's own pause
    carries the leader's, on the root lane.
    """

    lanes: Dict[str, _PausedMemberLane]
    tool_calls: List[_PausedToolCall]
    carried: int
    dropped: int
    content: Optional[str]
    content_lane: Optional[str]


def _prompt_lane(state: StreamState, lane: Optional[str]) -> Optional[str]:
    """The lane a pause prompt may stamp, or the root lane when none can be named.

    Only ``attributed`` names members on the wire: ``inline`` has one lane, and
    ``hidden`` must not let a confirmation prompt reveal which member asked. A
    lane whose terminal has already gone out is not named either, since a
    terminal is final for the id it names and nothing may carry a member after
    it.
    """
    if lane is ROOT_LANE or state.subagent_visibility != SUBAGENT_VISIBILITY_ATTRIBUTED:
        return ROOT_LANE
    return lane if lane in state.open_subagents else ROOT_LANE


def _paused_member_lane(
    state: StreamState,
    requirement: RunRequirement,
    pending: Dict[str, _PausedMemberLane],
) -> Optional[str]:
    """The lane a paused member's tool call is stamped with, resolving a new one.

    Only ``attributed`` names members on the wire: ``inline`` has one lane, and
    ``hidden`` must not let a confirmation prompt reveal which member asked.

    A lane the client was never given a start for is unreadable, so a lane this
    is the first sight of is recorded in ``pending`` for the caller to announce.
    Nothing is announced from here: whether the prompt these lanes are for is
    emitted at all is not known until every paused tool has been read, and a
    lane announced for a prompt that is then dropped leaves the client a
    terminal for a member it never saw start.

    When no lane can be named, because the member's run is unknown or because
    its terminal has already gone out and a terminal is final for the id it
    names, the tool call falls back to the root lane instead of carrying an id
    the client cannot resolve.
    """
    member_run_id = requirement.member_run_id
    if member_run_id is None or member_run_id == state.root_run_id:
        return ROOT_LANE
    if state.subagent_visibility != SUBAGENT_VISIBILITY_ATTRIBUTED:
        return ROOT_LANE
    if member_run_id in state.open_subagents or member_run_id in pending:
        return member_run_id
    if member_run_id in state.closed_subagents:
        return ROOT_LANE

    # A member pauses inside the call that delegated to it, so the lane holding
    # that call is the parent, at whatever depth the pause was reported. Without
    # an open delegation naming this member there is nothing that establishes
    # either, so both are left out: reaching past for the leader's own open call
    # gives the member a parent it never had, the task text of somebody else's
    # delegation, and a depth that puts a grandchild level with the member that
    # really delegated to it.
    parent_lane: Optional[str] = ROOT_LANE
    delegation_call_id: Optional[str] = None
    delegation = state.find_member_delegation(requirement.member_agent_id)
    if delegation is not None:
        parent_lane, delegation_call_id = delegation

    # The member's name and id come off the paused run, so both are read through
    # the same guard every other label is: a lane whose name cannot be rendered
    # is announced under its run id rather than ending a run that is only
    # waiting for an answer.
    name = (
        _readable(requirement.member_agent_name, "a paused member name")
        or _readable(requirement.member_agent_id, "a paused member id")
        or member_run_id
    )
    pending[member_run_id] = _PausedMemberLane(
        run_id=member_run_id,
        name=name,
        parent_lane=parent_lane,
        delegation_call_id=delegation_call_id,
    )
    return member_run_id


def _announce_paused_lanes(state: StreamState, pending: Dict[str, _PausedMemberLane]) -> List[BaseEvent]:
    """Announce the member lanes a pause prompt is about to carry."""
    events: List[BaseEvent] = []
    for lane in pending.values():
        state.open_subagent(lane.run_id, name=lane.name, parent_lane=lane.parent_lane)
        events.append(
            SubagentStartedEvent(
                type=EventType.SUBAGENT_STARTED,
                subagent_run_id=lane.run_id,
                name=lane.name,
                description=state.delegation_task(lane.parent_lane, lane.delegation_call_id),
                parent_subagent_run_id=lane.parent_lane,
                parent_tool_call_id=lane.delegation_call_id,
                parent_message_id=state.delegation_parent_message_id(lane.parent_lane, lane.delegation_call_id),
            )
        )
    return events


def _active_requirements(chunk: BaseRunOutputEvent) -> List[RunRequirement]:
    """The requirements a paused run still needs resolved, on a release that reports them.

    Both paused event types declare the field, and one that does not is read as
    reporting none: a pause is what the client has to be told about, so a
    missing field withholds the attribution rather than the prompt.
    """
    requirements = getattr(chunk, "active_requirements", None)
    return list(requirements) if requirements else []


def _paused_tools_with_lanes(chunk: BaseRunOutputEvent, state: StreamState) -> _PausedPrompt:
    """The tool calls a paused run is waiting on, each with the lane that owns it.

    A tool can be reported twice, once on the terminal event's own lists, which
    carry copies of what its members are waiting on as well as the leader's own
    tools, and once on the requirement that names the member waiting on it. It
    is one pending call, so it is prompted once, on the member's lane. A call
    already on the wire under a member's lane is then not prompted at all: the
    client has a start for it and a second one would be a duplicate id. A call
    of the top-level entity's own is prompted whichever visibility is set, so a
    run with no member on the wire streams exactly what the default streams.
    Neither the merge nor the drop applies under the default itself, whose
    stream stays what it was before member attribution existed.

    Only a requirement's copy ever merges into one already recorded. The
    terminal's own lists are read as they are, so a pending call flagged for
    several of them, and therefore listed by each, is prompted once per listing
    under every visibility: that duplicate is the default's stream, and the
    default's stream is the one every setting has to match on a run with no
    member on the wire.

    The terminal's own lists belong to the run that reported the pause. That is
    the leader's for a leader's pause, and a member's where a member's pause was
    the last thing the stream carried and became the run terminal, so those
    tools are stamped with the run that is really waiting on them.

    A tool without both an id and a name is dropped and recorded: there is
    nothing the client could render and nothing to tell a duplicate by, and the
    resume then waits on a call nothing asked for. Lanes come back alongside,
    unannounced and only for the members a surviving tool call is stamped with,
    since a lane the prompt carries nothing for tells the client about a member
    it will never hear from again.
    """
    pending: Dict[str, _PausedMemberLane] = {}
    recorded: List[_PausedToolCall] = []
    carried = 0
    dropped = 0
    lineage = state.subagent_visibility != SUBAGENT_VISIBILITY_INLINE
    terminal_lane = state.lane_for(*_chunk_run_ids(chunk))
    reporting_lane = _prompt_lane(state, terminal_lane)

    def record(tool: ToolExecution, lane: Optional[str], merges: bool) -> None:
        nonlocal carried, dropped
        carried += 1
        if tool.tool_call_id is None or tool.tool_name is None:
            dropped += 1
            log_warning(
                f"AG-UI dropped a pending tool call from the pause of run {state.run_id} in session "
                f"{state.thread_id}, because the client cannot be shown it: tool_call_id={tool.tool_call_id}, "
                f"tool_name={tool.tool_name}. A resume waits on that call with nothing on the wire to resolve it."
            )
            return
        prompted = _PausedToolCall(
            tool_call_id=tool.tool_call_id, tool_name=tool.tool_name, tool_args=tool.tool_args, lane=lane
        )
        if merges:
            for index, already in enumerate(recorded):
                if already.tool_call_id == prompted.tool_call_id:
                    # The member's attribution wins over the unattributed copy,
                    # in the position the call was first reported in.
                    recorded[index] = prompted
                    return
        recorded.append(prompted)

    if isinstance(chunk, (AgentRunPausedEvent, TeamRunPausedEvent)):
        for list_name in _PAUSE_TOOL_LISTS:
            for tool in getattr(chunk, list_name, None) or ():
                record(tool, reporting_lane, merges=False)
        # A subagent's tools live in the requirements, which name the run waiting
        # on them, and that attribution wins over the unattributed copy above. An
        # agent that ran an inner agent reports them exactly as a team reports a
        # member's, so lineage reads both paused shapes: a pending call the client
        # is not shown is one the run can never be resumed past.
        # The default is the pre-change stream, which read this on a team's pause only: an agent's is lineage behavior.
        if lineage or isinstance(chunk, TeamRunPausedEvent):
            for requirement in _active_requirements(chunk):
                if not (requirement.member_agent_id and requirement.tool_execution):
                    continue
                record(
                    requirement.tool_execution,
                    _paused_member_lane(state, requirement, pending),
                    merges=lineage,
                )

    if lineage:
        # Read once every copy of a call has been merged, so a call the wire
        # already carries under its member's lane is dropped whichever of the two
        # places reported it first.
        recorded = [
            tool_call
            for tool_call in recorded
            if tool_call.lane is ROOT_LANE or not state.tool_call_started(tool_call.tool_call_id)
        ]

    stamped = {tool_call.lane for tool_call in recorded}
    return _PausedPrompt(
        lanes={run_id: lane for run_id, lane in pending.items() if run_id in stamped},
        tool_calls=recorded,
        carried=carried,
        dropped=dropped,
        content=_pause_content(chunk, terminal_lane, reporting_lane),
        content_lane=reporting_lane,
    )


def _pause_content(
    chunk: BaseRunOutputEvent,
    terminal_lane: Optional[str],
    reporting_lane: Optional[str],
) -> Optional[str]:
    """The paused run's own words, or None when there are none to send.

    A member's pause carries the member's words, so they go out on the member's
    lane. A visibility that will not name that lane withholds them instead of
    passing a member's prose off as the run's own reply.
    """
    content = getattr(chunk, "content", None)
    if not content:
        return None
    if terminal_lane is not ROOT_LANE and reporting_lane is ROOT_LANE:
        return None
    return str(content)


def _pause_prompt(
    state: StreamState,
    announcements: List[BaseEvent],
    prompt: _PausedPrompt,
) -> List[BaseEvent]:
    """The assistant messages and tool calls a paused run asks the client to resolve.

    One message per lane, each carrying that lane's own pending calls. A tool
    call belongs to the message that carries it, so the two must agree about
    which member they are: one message stamped for two members is unreadable,
    and an unstamped message carrying a member's call is a call a client cannot
    place. One pause can be waiting on several members at once, so one message
    is not enough and the split is per lane rather than one message with mixed
    calls under it.

    A pause with nothing left to show still says something when the client was
    never shown what the run is waiting on: a bare message tells it the run is
    waiting rather than finished. A call left out because the client already has
    a start for it is the case that needs nothing, being already on the wire to
    be acted on.
    """
    if not prompt.carried:
        return []

    events: List[BaseEvent] = list(announcements)
    blocks = _prompt_blocks(prompt)
    if not blocks:
        if not prompt.dropped:
            return events
        blocks = [(prompt.content_lane, [])]

    for lane, tool_calls in blocks:
        events.extend(_prompt_block(state, lane, tool_calls, prompt.content if lane == prompt.content_lane else None))
    return events


def _prompt_blocks(prompt: _PausedPrompt) -> List[Tuple[Optional[str], List[_PausedToolCall]]]:
    """The pause prompt split into one message per lane, in the order it was reported.

    The lane the paused run's own words belong to leads, since that message is
    the prompt's opening line whether or not any pending call is stamped with
    the same lane.
    """
    grouped: Dict[Optional[str], List[_PausedToolCall]] = {}
    if prompt.content is not None:
        grouped[prompt.content_lane] = []
    for tool_call in prompt.tool_calls:
        grouped.setdefault(tool_call.lane, []).append(tool_call)
    return list(grouped.items())


def _prompt_block(
    state: StreamState,
    lane: Optional[str],
    tool_calls: List[_PausedToolCall],
    content: Optional[str],
) -> List[BaseEvent]:
    """One lane's share of a pause prompt: its message, and the calls parented to it."""
    message_id = str(uuid.uuid4())
    events: List[BaseEvent] = [
        TextMessageStartEvent(
            type=EventType.TEXT_MESSAGE_START,
            message_id=message_id,
            role="assistant",
        )
    ]
    if content:
        events.append(
            TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=message_id,
                delta=content,
            )
        )
    events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id))

    for tool_call in tool_calls:
        events.extend(
            [
                ToolCallStartEvent(
                    type=EventType.TOOL_CALL_START,
                    tool_call_id=tool_call.tool_call_id,
                    tool_call_name=tool_call.tool_name,
                    parent_message_id=message_id,
                ),
                ToolCallArgsEvent(
                    type=EventType.TOOL_CALL_ARGS,
                    tool_call_id=tool_call.tool_call_id,
                    delta=json.dumps(tool_call.tool_args),
                ),
                ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call.tool_call_id),
            ]
        )
        # The client has been given an end for this call, so the run-end sweep
        # must not write a second one.
        state.end_tool_call(tool_call.tool_call_id)

    return _stamp_lane(events, lane)


def on_run_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    prompt = _paused_tools_with_lanes(chunk, state)
    # Announced here, before the closing order is chosen, because it is only now
    # certain which lanes the prompt really carries, and because a lane
    # announced needs the run end to terminate it.
    announcements = _announce_paused_lanes(state, prompt.lanes)
    if isinstance(chunk, (AgentRunPausedEvent, TeamRunPausedEvent)) and prompt.dropped == prompt.carried:
        # The run is waiting on something nobody can resolve, and the two ways
        # that happens reach the client differently, so they are recorded
        # differently. A call left out because the client already has a start
        # for it is neither of them: that one is on the wire to be acted on.
        if prompt.carried:
            log_warning(
                f"AG-UI run {state.run_id} in session {state.thread_id} paused on tool calls the client "
                "cannot be shown, so it is told the run is waiting with nothing on the wire to act on"
            )
        else:
            # No pending call was READ, which is not the same as none existing.
            # Under the default an Agent's active requirements are left unread,
            # so a pause whose only pending call arrives that way lands here.
            log_warning(
                f"AG-UI run {state.run_id} in session {state.thread_id} paused with no pending tool call "
                "this visibility reads, so the pause reaches the client as a plain finished run"
            )

    events = _close_run_end_spans(
        state,
        lambda: _drain_subagents(state),
        lambda: _pause_prompt(state, announcements, prompt),
    )

    # Emit final state snapshot
    if state.run_state is not None:
        authoritative_state = getattr(chunk, "session_state", None)
        final_state = authoritative_state if authoritative_state is not None else state.run_state
        events.append(StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copy.deepcopy(final_state)))

    events.append(RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=state.thread_id, run_id=state.run_id))
    return events


def _normalize_event(event: str) -> str:
    """Strip 'Team' prefix so agent and team events use the same handlers."""
    return event.removeprefix("Team")


# Maps normalized event names to handler functions
HANDLERS: Dict[str, EventHandler] = {
    RunEvent.run_content.value: on_run_content,
    RunEvent.tool_call_started.value: on_tool_call_started,
    RunEvent.tool_call_completed.value: on_tool_call_completed,
    RunEvent.reasoning_started.value: on_reasoning_started,
    RunEvent.reasoning_content_delta.value: on_reasoning_content_delta,
    RunEvent.reasoning_step.value: on_reasoning_step,
    RunEvent.reasoning_completed.value: on_reasoning_completed,
    RunEvent.custom_event.value: on_custom_event,
}

# Terminal events that trigger terminal handling
_COMPLETION_EVENTS = frozenset(
    {
        RunEvent.run_completed.value,
        RunEvent.run_error.value,
        RunEvent.run_paused.value,
        TeamRunEvent.run_completed.value,
        TeamRunEvent.run_error.value,
        TeamRunEvent.run_paused.value,
    }
)


def _subagent_result(content: Any) -> Optional[str]:
    """A member's output as its terminal's result, serialized when it is not text.

    A terminal event must never be the thing that fails a run that otherwise
    succeeded, so every step here falls back rather than raising: a model dump
    can raise on a partly-built object, and the JSON encoder raises on cyclic
    content. The last resort is the object's own text, and failing that a note
    naming its type.
    """
    if content is None or isinstance(content, str):
        return content

    model_dump_json = getattr(content, "model_dump_json", None)
    if callable(model_dump_json):
        try:
            return str(model_dump_json())
        except Exception as error:
            log_warning(f"AG-UI could not dump a subagent result of type {type(content).__name__}: {error}")

    try:
        return to_json_str(content)
    except Exception as error:
        log_warning(f"AG-UI could not serialize a subagent result of type {type(content).__name__}: {error}")

    try:
        return str(content)
    except Exception as error:
        log_warning(f"AG-UI could not render a subagent result of type {type(content).__name__}: {error}")
        return f"<unrenderable {type(content).__name__} result>"


def on_subagent_completed(chunk: BaseRunOutputEvent, state: StreamState, lane: Optional[str]) -> List[BaseEvent]:
    return _lane_finished(state, lane, result=_subagent_result(getattr(chunk, "content", None)))


def on_subagent_error(chunk: BaseRunOutputEvent, state: StreamState, lane: Optional[str]) -> List[BaseEvent]:
    # The failure text comes off the failing run, so it is read through the same
    # guard every other label is: one that cannot be rendered leaves the lane
    # reporting a failure without a message of its own, never a live run ended
    # by the attempt to describe a dead one.
    message = _readable(getattr(chunk, "content", None), "a subagent failure message") or "Subagent run failed"
    return _lane_errored(
        state,
        lane,
        message,
        getattr(chunk, "error_type", None),
        details={
            "error_id": getattr(chunk, "error_id", None),
            "additional_data": getattr(chunk, "additional_data", None),
        },
    )


def on_subagent_cancelled(chunk: BaseRunOutputEvent, state: StreamState, lane: Optional[str]) -> List[BaseEvent]:
    """A cancelled member is terminated as errored: it produced no result to report."""
    reason = _readable(getattr(chunk, "reason", None), "a subagent cancellation reason") or "Subagent run cancelled"
    return _lane_errored(state, lane, reason, _SUBAGENT_CANCELLED_CODE)


# A subagent's own terminal, which ends that subagent rather than the stream.
# A member's pause is deliberately absent: a paused member has not finished, so
# its lane stays open and the run-end drain terminates it.
_SUBAGENT_TERMINAL_HANDLERS: Dict[str, Callable[[BaseRunOutputEvent, StreamState, Optional[str]], List[BaseEvent]]] = {
    RunEvent.run_completed.value: on_subagent_completed,
    RunEvent.run_error.value: on_subagent_error,
    RunEvent.run_cancelled.value: on_subagent_cancelled,
}

# A member's own pause carries nothing the client needs: the pending tool call
# reaches it from the delegating run's requirements, so dumping the internal
# payload would both leak it and duplicate that call.
_SUBAGENT_WITHHELD_EVENTS = frozenset({RunEvent.run_paused.value})

# Every chunk that stops a subagent, normalized. Derived from the terminal table
# rather than listed beside it, so a terminal type this interface learns to
# handle cannot be one the stream fails to recognize as ending a subagent: the
# two would then disagree, and a stream whose last chunk was that terminal would
# report the run finished after saying the subagent did not. A pause is here
# too, and only here: it stops the subagent without terminating its lane, so it
# has no entry in the table.
_SUBAGENT_RUN_ENDING_EVENTS = frozenset(_SUBAGENT_TERMINAL_HANDLERS) | _SUBAGENT_WITHHELD_EVENTS


def _events_missing_the_lane_field() -> List[str]:
    """The event classes this interface attributes that cannot carry a lane."""
    return sorted(
        event_class.__name__
        for event_class in _ATTRIBUTABLE_EVENT_CLASSES.values()
        if _SUBAGENT_RUN_ID_FIELD not in event_class.model_fields
    )


def _lineage_event_fields() -> Dict[Type[BaseEvent], Tuple[str, ...]]:
    """Every SUBAGENT_* field this interface writes, per class it writes it on.

    Built here rather than at import, because on a protocol release without the
    lineage events there are no classes to key it by.
    """
    return {
        SubagentStartedEvent: (
            _SUBAGENT_RUN_ID_FIELD,
            "name",
            "description",
            "parent_subagent_run_id",
            "parent_tool_call_id",
            "parent_message_id",
        ),
        SubagentFinishedEvent: (_SUBAGENT_RUN_ID_FIELD, "result"),
        SubagentErrorEvent: (_SUBAGENT_RUN_ID_FIELD, "message", "code"),
    }


def _lineage_fields_the_protocol_omits() -> List[str]:
    """The SUBAGENT_* fields this interface writes that the installed protocol omits.

    Named class by field, so the refusal says exactly what is missing. The
    protocol models accept attributes they do not declare, so an omitted field
    would otherwise leave the run: the value goes out under the name written
    here instead of the one the wire format defines, and a client reads a lane
    with no description, no parent and no result rather than a refusal.
    """
    if not SUBAGENT_EVENTS_AVAILABLE:
        return []
    return sorted(
        f"{event_class.__name__}.{field}"
        for event_class, fields in _lineage_event_fields().items()
        for field in fields
        if field not in event_class.model_fields
    )


def validate_subagent_visibility(visibility: Optional[str]) -> str:
    """Normalize a subagent_visibility value, refusing one this install cannot serve.

    Everything ``attributed`` needs is feature-detected here: the lineage event
    types, every field this interface writes on one of them, and the per-event
    field the lane is stamped in. They belong in this check rather than at the
    events themselves, which are built with a client already reading the stream.
    """
    resolved = visibility or SUBAGENT_VISIBILITY_INLINE
    if resolved not in SUBAGENT_VISIBILITY_VALUES:
        raise ValueError(f"subagent_visibility must be one of {SUBAGENT_VISIBILITY_VALUES}, got {visibility!r}")
    if resolved == SUBAGENT_VISIBILITY_ATTRIBUTED:
        if not SUBAGENT_EVENTS_AVAILABLE:
            raise ValueError(
                "subagent_visibility='attributed' needs the AG-UI subagent lineage events. "
                "Please upgrade with `pip install -U ag-ui-protocol`."
            )
        undeclared = _lineage_fields_the_protocol_omits()
        if undeclared:
            raise ValueError(
                "subagent_visibility='attributed' needs every field it writes on the AG-UI subagent "
                f"lineage events, which the installed ag_ui.core omits: {', '.join(undeclared)}. "
                "Please upgrade with `pip install -U ag-ui-protocol`."
            )
        cannot_carry_a_lane = _events_missing_the_lane_field()
        if cannot_carry_a_lane:
            raise ValueError(
                f"subagent_visibility='attributed' needs {_SUBAGENT_RUN_ID_FIELD} on every event it "
                f"attributes, which the installed ag_ui.core omits on {', '.join(cannot_carry_a_lane)}. "
                "Please upgrade with `pip install -U ag-ui-protocol`."
            )
    return resolved


def _log_withheld_failure(chunk: BaseRunOutputEvent, lane: Optional[str], normalized: str) -> None:
    """Record a member failure or cancellation that ``hidden`` keeps off the wire.

    Every way a member can fail belongs here, its own run and any one of its
    tool calls alike: with nothing on the wire naming the member, this line is
    the only trace an operator gets of which member it was.

    What ``hidden`` withholds is that identity, not always the text. A member's
    own terminal can be the only account the stream carries of how the run
    stopped, and is then read as the run terminal, so its failure text or its
    cancellation reason reaches the client as the reason the run ended. Those
    two lines say so rather than claiming the client was told nothing. A tool
    call's failure ends no run, so nothing of it reaches the client and its line
    says exactly that.
    """
    if normalized == RunEvent.run_error.value:
        details = {
            "error_type": getattr(chunk, "error_type", None),
            "error_id": getattr(chunk, "error_id", None),
            "additional_data": getattr(chunk, "additional_data", None),
        }
        message = _readable(getattr(chunk, "content", None), "a withheld subagent failure message")
        log_error(
            f"AG-UI withheld the identity of a subagent that failed in lane {lane}, so no SUBAGENT_ERROR "
            f"named it; {_REASON_STILL_REACHES_THE_CLIENT}: "
            f"{message or 'Subagent run failed'}{_correlation(details)}"
        )
    elif normalized == RunEvent.tool_call_error.value:
        tool = getattr(chunk, "tool", None)
        details = {
            "tool_call_id": getattr(tool, "tool_call_id", None),
            "tool_name": getattr(tool, "tool_name", None),
        }
        error = _readable(getattr(chunk, "error", None), "a withheld subagent tool call failure")
        log_error(
            f"AG-UI withheld a subagent tool call failure in lane {lane}: "
            f"{error or 'Tool call failed'}{_correlation(details)}"
        )
    elif normalized == RunEvent.run_cancelled.value:
        reason = _readable(getattr(chunk, "reason", None), "a withheld subagent cancellation reason")
        log_warning(
            f"AG-UI withheld the identity of a subagent cancelled in lane {lane}, so no SUBAGENT_ERROR "
            f"named it; {_REASON_STILL_REACHES_THE_CLIENT}: {reason or 'Subagent run cancelled'}"
        )


def _ends_a_run(chunk: BaseRunOutputEvent) -> bool:
    """Whether a chunk is one of the events that end a run: completed, paused or error."""
    event = getattr(chunk, "event", None)
    if event is None:
        return False
    event_value = event.value if hasattr(event, "value") else str(event)
    return event_value in _COMPLETION_EVENTS


def _ends_a_subagent(chunk: BaseRunOutputEvent) -> bool:
    """Whether a chunk stops the subagent it came from."""
    return _normalized_event_of(chunk) in _SUBAGENT_RUN_ENDING_EVENTS


def _normalized_event_of(chunk: BaseRunOutputEvent) -> str:
    """A chunk's event name with the Team prefix stripped, or empty when it has none."""
    event = getattr(chunk, "event", None)
    if event is None:
        return ""
    return _normalize_event(event.value if hasattr(event, "value") else str(event))


def is_completion_event(chunk: BaseRunOutputEvent, state: StreamState) -> bool:
    """Check if this event is terminal for the stream (completed, paused, or error).

    A subagent's own completion is terminal for that subagent only. It still
    reads as a stream terminal under inline visibility, where the wire carries
    no subagent lifecycle and the top-level terminal that follows supersedes it.
    The state is what says which of the two a chunk is, so there is no answering
    without it.
    """
    return _ends_a_run(chunk) and state.lane_for(*_chunk_run_ids(chunk)) is ROOT_LANE


def is_subagent_completion_event(chunk: BaseRunOutputEvent, state: StreamState) -> bool:
    """Whether a chunk ends one subagent rather than the run.

    A stream whose last chunk is one of these ended on a subagent's terminal and
    reported no terminal of its own, so that chunk is the only account of how the
    run ended: read as anything else, a run that died inside a subagent is
    reported to the client as a success. Under inline visibility every such chunk
    is already the run's own terminal, so this is what makes the other
    visibilities end that stream the same way.

    What counts is read from the subagent terminal table rather than from the
    run-terminal set, which a cancellation is deliberately absent from: the
    top-level entity's cancellation is not a run terminal this interface builds
    from, but a subagent's is a subagent terminal, and every one of those has to
    be recognized here.
    """
    return _ends_a_subagent(chunk) and state.lane_for(*_chunk_run_ids(chunk)) is not ROOT_LANE


def process_event(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    """Process a single Agno event and return AG-UI events to emit."""
    lane = state.resolve_lane(*_chunk_run_ids(chunk))

    event = getattr(chunk, "event", None)
    event_value = event.value if event is not None and hasattr(event, "value") else str(event)
    normalized = _normalize_event(event_value) if event is not None else ""

    events: List[BaseEvent] = []
    if lane is not ROOT_LANE:
        if state.hides_subagents:
            # Invisible delegation: nothing the subagent streamed is sent as its
            # own work, and no lineage event or stamp goes out. The parent's own
            # delegation tool call and its result still do, arguments included.
            # Two things the subagent produced also reach the client. One is a
            # change a tool of its own made to the session state, which is one
            # shared document, delivered here. The other is a pending tool call
            # it paused on, which the run cannot continue without and which
            # reaches the client from the delegating run's requirements.
            if normalized == RunEvent.tool_call_completed.value:
                return _emit_state_delta(state)
            # Hidden withholds what identifies a member, not the fact that one
            # failed: nothing else would tell the operator it happened.
            _log_withheld_failure(chunk, lane, normalized)
            return []
        events.extend(_announce_subagent(chunk, state, lane))
        if normalized in _SUBAGENT_WITHHELD_EVENTS:
            return events
        subagent_terminal = _SUBAGENT_TERMINAL_HANDLERS.get(normalized)
        if subagent_terminal:
            events.extend(subagent_terminal(chunk, state, lane))
            return events

    handler = HANDLERS.get(normalized) if event is not None else None
    mapped = handler(chunk, state) if handler else on_unknown_event(chunk, state)
    events.extend(_stamp_lane(mapped, lane))
    if lane is not ROOT_LANE and lane in state.closed_subagents:
        # These events carry a member after that member's terminal, which the
        # rest of this interface refuses to do: the run end orders the pause
        # prompt before the member terminals, and the prompt itself declines to
        # name a lane that has already terminated, both for that reason. This is
        # the exemption, and it is the source stream's doing rather than a
        # choice made here. A member whose own run already ended is still
        # emitting, and the alternatives are worse: reparenting its output to
        # the leader would report a member's words as somebody else's, and a
        # second announcement would give one invocation two lifecycles.
        #
        # The span it opens does close with it. Left open, it swallows
        # everything the rest of the run emits, starting with the parent's
        # result for the delegation this member was running inside. Tool calls
        # keep their own lifecycle, so a result still arrives for one opened
        # here.
        events.extend(_close_lane_messages(state, lane))
    return events


# The terminal chunks that end the run in failure rather than completion. A
# cancellation is one of them: the run stopped without producing what it was
# asked for, so telling the client it finished would report a success that never
# happened. Only a subagent's cancellation can be the chunk the run terminal is
# built from, since the top-level entity's is not read as a run terminal at all.
_FAILED_RUN_TERMINALS = frozenset({RunEvent.run_error.value, RunEvent.run_cancelled.value})


def process_completion(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    """Process a terminal event and return the corresponding AG-UI events."""
    state.resolve_lane(*_chunk_run_ids(chunk))
    normalized = _normalized_event_of(chunk)
    if normalized in _FAILED_RUN_TERMINALS:
        return on_run_error(chunk, state, normalized)
    return on_run_completed(chunk, state)
