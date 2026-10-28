import copy
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, Type

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
from agno.os.interfaces.agui.interrupts import (
    PAUSE_NOT_CONTINUABLE_CODE,
    NeededAnswer,
    answers_a_pause_needs,
    build_interrupt,
    interrupt_outcome,
    pause_not_continuable,
    subagent_suspension_available,
    suspended_outcome,
)
from agno.os.interfaces.agui.state import (
    ROOT_LANE,
    SUBAGENT_VISIBILITY_ATTRIBUTED,
    SUBAGENT_VISIBILITY_INLINE,
    SUBAGENT_VISIBILITY_VALUES,
    StreamState,
)
from agno.os.interfaces.agui.utils import readable as _readable
from agno.os.interfaces.agui.utils import to_json_str
from agno.reasoning.step import ReasoningStep
from agno.run.agent import RunContentEvent, RunEvent
from agno.run.agent import RunPausedEvent as AgentRunPausedEvent
from agno.run.base import BaseRunOutputEvent
from agno.run.requirement import RunRequirement
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.run.team import TeamRunEvent
from agno.utils.log import log_error, log_exception, log_warning
from agno.utils.message import get_text_from_message
from agno.utils.string import url_safe_string

if TYPE_CHECKING:  # the interrupt types are an optional part of the protocol
    from ag_ui.core import Interrupt

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

    A lane the run paused inside closes as suspended, carrying the interrupts it
    owns, so a client renders it as waiting rather than as work that finished.
    Every other lane closes with no outcome at all, which the protocol reads as
    success. The suspended outcome only ever pairs with a run-level interrupt
    outcome, because the pause terminal records the lanes at the same time as it
    builds that one: a lone suspended half would tell a client the subagent is
    waiting while the run says it finished.
    """
    if lane is None:
        return []
    already_closed = lane in state.closed_subagents
    owned_interrupts = state.suspended_lane_interrupts.get(lane)
    suspended = suspended_outcome(owned_interrupts) if owned_interrupts is not None else None
    state.close_subagent(lane)
    if already_closed:
        return []
    # The outcome is named only when there is one to name. An omitted outcome is
    # the protocol's reading of a subagent whose work completed, and passing the
    # field to say so would put it on the wire as an explicit null on a release
    # that does not declare it.
    if suspended is not None:
        terminal = SubagentFinishedEvent(
            type=EventType.SUBAGENT_FINISHED,
            subagent_run_id=lane,
            result=result,
            outcome=suspended,
        )
    else:
        terminal = SubagentFinishedEvent(
            type=EventType.SUBAGENT_FINISHED,
            subagent_run_id=lane,
            result=result,
        )
    return [*_close_lane_messages(state, lane), terminal]


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


# The keys a dumped chunk can name a subagent by, matched at any depth. A
# fragment rather than a list of field names, because the identity travels on
# several of the framework's models at once: a pause requirement carries the
# member's id, its name and its run id, and a delegation's tool execution
# carries the run it started. A list of names is what a model that later gains
# another such field walks straight past. ``child_run_id`` is the one key
# holding a subagent's run id without saying so in its name, so it is named.
_SUBAGENT_NAMING_KEY_FRAGMENT = "member"
_SUBAGENT_NAMING_KEYS = frozenset({"child_run_id"})


def _names_a_subagent(dumped: Any) -> bool:
    """Whether anything inside a dumped chunk names a subagent.

    The question a verbatim dump has to answer before it goes out under a
    visibility that withholds which member did something. Asking whose lane the
    chunk came from answers a different one and is what let this through: a
    leader's pause event is the leader's own, and carries the id, the name and
    the run id of every member the run is waiting on inside it.

    A key holding nothing names nobody, so a value that is absent or empty does
    not withhold a dump: every requirement a pause reports carries the member
    fields whether or not a member is involved, and a run with no members at all
    would otherwise lose its dump to the fields that say so.

    Reading the dump walks whatever a model or a tool put in the run's content,
    which can nest arbitrarily and refer to itself. An unanswerable question is
    answered yes: this decides whether identity reaches a client, so a walk that
    cannot finish withholds rather than publishes.
    """
    try:
        return _walk_for_a_subagent_name(dumped)
    except Exception as error:
        log_warning(
            f"AG-UI could not read whether a failed run terminal's chunk names a member: {type(error).__name__}"
        )
        return True


def _walk_for_a_subagent_name(dumped: Any) -> bool:
    """The unguarded walk behind the question above. Text is a leaf, not a sequence."""
    if isinstance(dumped, Mapping):
        for key, value in dumped.items():
            names_it = isinstance(key, str) and (
                _SUBAGENT_NAMING_KEY_FRAGMENT in key.lower() or key in _SUBAGENT_NAMING_KEYS
            )
            if names_it and value not in (None, "", [], {}, ()):
                return True
            if _walk_for_a_subagent_name(value):
                return True
        return False
    if isinstance(dumped, (list, tuple, set, frozenset)):
        return any(_walk_for_a_subagent_name(item) for item in dumped)
    return False


def _recorded_verbatim(dumped: Dict[str, Any]) -> str:
    """A withheld dump as the one line an operator reads it off instead.

    Rendering it runs the same content the wire would have carried, so it falls
    back rather than raising: this is the only place the withheld payload exists,
    and a record that ends the run reports nothing at all.
    """
    try:
        return json.dumps(dumped, default=str)
    except Exception as error:
        return f"<unrenderable {type(dumped).__name__}: {type(error).__name__}>"


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

    Whose chunk it is decides none of that on its own. A leader's own terminal
    is the run's and still carries member identity inside it: a pause reports
    one requirement per thing it waits on, each naming the member that asked, its
    id and its run. So under ``hidden`` the dump goes out only when nothing in it
    names a member, and is recorded for the operator when it does. The
    visibilities that name members keep it, since withholding there withholds
    nothing a client is not already told.
    """
    if state.lane_for(*_chunk_run_ids(chunk)) is not ROOT_LANE:
        return None
    try:
        dumped = chunk.to_dict()
    except Exception as error:
        # Recorded, because this runs before the run terminal's own cleanup: a
        # dump that fails silently here leaves nothing at all saying why the
        # client got a terminal naming the event instead of the chunk. The
        # record names the type and renders nothing, since an exception's text
        # can raise as readily as the dump did, and the fallback reads the event
        # name through the same guard: unguarded, both of them end the run from
        # inside the terminal that reports why it stopped.
        log_warning(f"AG-UI could not dump the chunk a failed run terminal reports verbatim: {type(error).__name__}")
        return {"event": _readable(getattr(chunk, "event", None), "a failed run event name") or "RunError"}

    if state.hides_subagents and _names_a_subagent(dumped):
        # The only place the withheld payload survives, so it is recorded whole:
        # the terminal tells the client why the run stopped and nothing else,
        # and an operator diagnosing that has this line and no other copy.
        log_warning(
            "AG-UI withheld the chunk a failed run terminal reports verbatim, because it names a member and "
            f"this visibility names none; it is recorded here instead: {_recorded_verbatim(dumped)}"
        )
        return None
    return dumped


def _terminal_failure(
    chunk: BaseRunOutputEvent,
    normalized: str,
    pause_not_continuable_because: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """What a failed run terminal says, and the code it says it under.

    A pause no client can answer is a run that has ended for good, and the
    reason for it is the caller's rather than the chunk's: the chunk is a pause,
    which carries no failure to read. It says so under a code of its own, so a
    client can tell a run that cannot be continued from one that died working.

    A cancellation is not a failure of the run's own making, so it reports the
    reason it was cancelled for under the same code a cancelled member's
    terminal carries. Only a subagent's cancellation ever reaches here: the
    top-level entity's is not read as a run terminal at all.
    """
    if pause_not_continuable_because is not None:
        return (
            f"The paused run cannot be continued: {pause_not_continuable_because}. A resume has to answer "
            "every requirement the pause left open, so nothing was advertised for a client to answer.",
            PAUSE_NOT_CONTINUABLE_CODE,
        )
    if normalized == RunEvent.run_cancelled.value:
        reason = _readable(getattr(chunk, "reason", None), "a cancelled run reason")
        return reason or "Run cancelled", _SUBAGENT_CANCELLED_CODE
    # Read through the same guard the reason above is, and for a stronger
    # reason: this message is built before the terminal's cleanup runs and is
    # also what every open member lane terminates under, so a failure whose text
    # cannot be rendered would close no span, terminate no lane and write no
    # terminal, leaving the client an open message and the run's real failure
    # replaced by the one raised while naming it.
    message = _readable(getattr(chunk, "content", None), "a failed run message")
    return message or "Run failed", getattr(chunk, "error_type", None)


def on_run_error(
    chunk: BaseRunOutputEvent,
    state: StreamState,
    normalized: str,
    pause_not_continuable_because: Optional[str] = None,
) -> List[BaseEvent]:
    """Close open spans, then emit the terminal AG-UI error event. Nothing may follow RUN_ERROR.

    ``normalized`` is the chunk's event name, which says which kind of failed
    terminal this is. It is required rather than defaulted: a default would read
    every cancellation as a plain failure and report the wrong code for it.

    ``pause_not_continuable_because`` is how a pause reaches this path at all. A
    paused chunk is not a failed terminal, so nothing routes it here on the
    chunk's own account; the pause handler does, once it has read that no client
    could answer what the run is waiting on.
    """
    raw_event = _terminal_raw_event(chunk, state)
    message, error_type = _terminal_failure(chunk, normalized, pause_not_continuable_because)

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
class _PausedRequirement:
    """One answer a paused run still needs, and the lane that owns it.

    ``needed`` is the entry ``answers_a_pause_needs`` returned for it, which
    carries the id the resume channel looks an answer up by and whether any
    answer could resolve it at all. The terminal is built from these rather than
    from the calls the prompt shows, because those are a different list: one call
    can be listed by several of the terminal's pause lists, and a listed call can
    have no open requirement behind it at all.
    """

    needed: NeededAnswer
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

    ``blocks`` is what the prompt shows, grouped into the one message per lane
    it sends them in, and ``pending`` is what the run is actually waiting on.
    They differ by the calls the client already has a start for, which the prompt
    leaves out and the run still cannot continue without: an interrupt outcome
    that named only the prompted ones would tell a client it had answered
    everything while a requirement was still open.

    The grouping is settled here rather than where the events are built, because
    ``open_requirements`` is ordered against it. One grouping read by both is
    what keeps the calls the client sees and the interrupts it reads beside them
    from disagreeing about their order.

    ``open_requirements`` is what the run has to have answered, which is neither
    of those two lists: it is read from the run's own requirements under every
    visibility, one entry per requirement the pause left open, and it is what
    the terminal is built from. Each entry carries whether any answer could
    resolve it, because one that none could ends the run instead of prompting.
    It is empty for a pause that reports no requirement, and the terminal then
    falls back to ``pending``.
    """

    lanes: Dict[str, _PausedMemberLane]
    blocks: List[Tuple[Optional[str], List[_PausedToolCall]]]
    pending: List[_PausedToolCall]
    open_requirements: List[_PausedRequirement]
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

    The run's open requirements come back too, read under every visibility,
    because they are what has to be answered rather than what is shown, and
    the terminal's interrupts are built from them. Reading them changes nothing
    the prompt sends: the calls above are read from the same lists, under the
    same rules, as they always were.
    """
    pending: Dict[str, _PausedMemberLane] = {}
    recorded: List[_PausedToolCall] = []
    open_requirements: List[_PausedRequirement] = []
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
            tool_call_id=tool.tool_call_id,
            tool_name=tool.tool_name,
            tool_args=tool.tool_args,
            lane=lane,
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
        # Every open requirement, which is what the run has to have answered and
        # therefore what the terminal's interrupts are built from. A subagent's
        # tools live here rather than on the lists above, and the requirement
        # names the run waiting on them, so this is also where a member's
        # attribution comes from; an agent that ran an inner agent reports one
        # exactly as a team reports a member's.
        for needed in answers_a_pause_needs(_active_requirements(chunk)):
            requirement = needed.requirement
            member_tool = requirement.tool_execution if requirement.member_agent_id else None
            # The prompt's own lane rules, so an interrupt names a member only
            # under a visibility that names members at all. Under the other two
            # this resolves to the root and announces nothing.
            lane = _paused_member_lane(state, requirement, pending) if member_tool else reporting_lane
            open_requirements.append(_PausedRequirement(needed, lane))
            # What the prompt shows is unchanged by any of the above: a member's
            # attributed copy wins over the unattributed one, and the default is
            # the pre-change stream, which read this on a team's pause only.
            if member_tool is not None and (lineage or isinstance(chunk, TeamRunPausedEvent)):
                record(member_tool, lane, merges=lineage)

    prompted = recorded
    if lineage:
        # Read once every copy of a call has been merged, so a call the wire
        # already carries under its member's lane is dropped whichever of the two
        # places reported it first.
        prompted = [
            tool_call
            for tool_call in recorded
            if tool_call.lane is ROOT_LANE or not state.tool_call_started(tool_call.tool_call_id)
        ]

    stamped = {tool_call.lane for tool_call in prompted}
    content = _pause_content(chunk, terminal_lane, reporting_lane)
    blocks = _prompt_blocks(prompted, reporting_lane, content is not None)
    return _PausedPrompt(
        lanes={run_id: lane for run_id, lane in pending.items() if run_id in stamped},
        blocks=blocks,
        pending=recorded,
        open_requirements=_in_prompt_order(open_requirements, blocks),
        carried=carried,
        dropped=dropped,
        content=content,
        content_lane=reporting_lane,
    )


def _in_prompt_order(
    open_requirements: List[_PausedRequirement],
    blocks: List[Tuple[Optional[str], List[_PausedToolCall]]],
) -> List[_PausedRequirement]:
    """The open requirements, ordered as the prompt sends the calls they wait on.

    A client renders the pending calls in the order the prompt sent them and
    reads the terminal's interrupts beside them, so the two name them in the
    same order. The prompt sends one message per lane, so a lane's calls arrive
    together whatever order the pause reported them in, and that order is read
    off the blocks the prompt is built from rather than worked out a second way.

    Keyed by the tool call, which is what a requirement and a prompted call have
    in common. Several requirements can name one call, and those keep the order
    the pause reported them in at the place that call is prompted. A requirement
    the prompt sends no call for keeps its own place, after every requirement
    that has one.
    """
    positions: Dict[str, int] = {}
    for _, tool_calls in blocks:
        for tool_call in tool_calls:
            positions.setdefault(tool_call.tool_call_id, len(positions))

    def prompted_at(open_requirement: _PausedRequirement) -> int:
        tool_execution = open_requirement.needed.requirement.tool_execution
        tool_call_id = tool_execution.tool_call_id if tool_execution else None
        if tool_call_id is None:
            return len(positions)
        return positions.get(tool_call_id, len(positions))

    return sorted(open_requirements, key=prompted_at)


def _pause_content(
    chunk: BaseRunOutputEvent,
    terminal_lane: Optional[str],
    reporting_lane: Optional[str],
) -> Optional[str]:
    """The paused run's own words, or None when there are none to send.

    A member's pause carries the member's words, so they go out on the member's
    lane. A visibility that will not name that lane withholds them instead of
    passing a member's prose off as the run's own reply.

    The words are read through the same guard every other label is. Rendering a
    run's content runs whatever the model or a tool put there, which can raise,
    and this is the run terminal: prose is never worth ending a run for, so a
    value that cannot be read is recorded and the prompt sends no words.
    """
    if terminal_lane is not ROOT_LANE and reporting_lane is ROOT_LANE:
        return None
    return _readable(getattr(chunk, "content", None), "a paused run's own words")


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
    blocks = prompt.blocks
    if not blocks:
        if not prompt.dropped:
            return events
        blocks = [(prompt.content_lane, [])]

    for lane, tool_calls in blocks:
        events.extend(_prompt_block(state, lane, tool_calls, prompt.content if lane == prompt.content_lane else None))
    return events


def _prompt_blocks(
    tool_calls: List[_PausedToolCall],
    content_lane: Optional[str],
    has_content: bool,
) -> List[Tuple[Optional[str], List[_PausedToolCall]]]:
    """The pause prompt split into one message per lane, in the order it was reported.

    The lane the paused run's own words belong to leads, since that message is
    the prompt's opening line whether or not any pending call is stamped with
    the same lane.
    """
    grouped: Dict[Optional[str], List[_PausedToolCall]] = {}
    if has_content:
        grouped[content_lane] = []
    for tool_call in tool_calls:
        grouped.setdefault(tool_call.lane, []).append(tool_call)
    return list(grouped.items())


# What a pending call is prompted with when its own arguments cannot be sent.
# An empty object, because the client parses this field as JSON and a call it
# cannot parse is one it cannot render an approval for at all.
_NO_PROMPTED_ARGUMENTS = "{}"


def _prompted_arguments(tool_call: _PausedToolCall) -> str:
    """One pending call's arguments as the prompt sends them, or an empty object.

    Serializing them runs whatever a tool was called with through the JSON
    encoder, which refuses a cycle, a set, and anything with no encoding at all.
    This is the run terminal, and it is built after the closing sweep: a raise
    here discards every span end the sweep produced along with the terminal
    itself, leaving the client a message and a tool call nothing ever closes. So
    the arguments are dropped with a record instead, and the call still reaches
    the client under the id a resume answers it by.
    """
    try:
        return json.dumps(tool_call.tool_args)
    except Exception as error:
        log_warning(
            f"AG-UI could not serialize the arguments of paused tool call {tool_call.tool_call_id}, so it "
            f"is prompted with none: {type(error).__name__}"
        )
        return _NO_PROMPTED_ARGUMENTS


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
                    delta=_prompted_arguments(tool_call),
                ),
                ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call.tool_call_id),
            ]
        )
        # The client has been given an end for this call, so the run-end sweep
        # must not write a second one.
        state.end_tool_call(tool_call.tool_call_id)

    return _stamp_lane(events, lane)


def _pause_interrupts(state: StreamState, prompt: _PausedPrompt) -> List["Interrupt"]:
    """The interrupts a paused run's terminal carries, and the lanes they suspend.

    One interrupt per answer ``answers_a_pause_needs`` said the run needs, keyed
    by the id that computation gave it, which is the id the resume channel looks
    an answer up by. Nothing sits between the two lists: every entry becomes an
    interrupt, because an entry with no id and two entries sharing one are both
    answers no client could send, which makes the pause not continuable and the
    caller emits the failed terminal instead of reaching here. The calls the
    prompt shows are a different list again, and neither of the two ways they
    differ is a thing to be answered: one call flagged for several pause kinds is
    listed once per kind, and a listed call can have no open requirement behind
    it at all.

    A pause that reports no requirement has nothing to key by but the calls the
    prompt read, so it falls back to those, keyed by the tool call, which is
    unique within the run. There the dedup below earns its place: the prompt can
    list one call more than once, and one correlation key standing for two
    interrupts is one answer that could land on either.

    A requirement stamped with a member's lane makes that interrupt the member's
    request, and the lane it names is recorded so the drain closes it as
    suspended instead of finished. The lanes above it are recorded too, with no
    interrupts of their own: a delegation whose member is waiting has not
    finished either, and the protocol says so with a suspended outcome carrying
    nothing. Under a visibility that names no member every lane resolves to the
    root, so nothing is stamped and nothing is suspended.

    Called after the pause prompt's own lanes are announced, so a lane the state
    now holds open is one the client has been told about, and a lane it does not
    is one the client will never hear of: the announcement is withheld for a
    member whose every pending call was dropped, and its requirement is still
    open. Such an interrupt goes out unattributed rather than naming a member
    the client never saw start.
    """
    interrupts: List["Interrupt"] = []
    owned: Dict[str, List[str]] = {}

    def carry(
        needed: Optional[NeededAnswer],
        tool_call_id: Optional[str],
        tool_name: Optional[str],
        lane: Optional[str],
    ) -> None:
        named = lane if lane in state.open_subagents else ROOT_LANE
        # The member the interrupt names and the lane recorded as owning it are
        # one value, read once: a lane suspended for an interrupt that went out
        # naming another member is an outcome no client can reconcile.
        attributed_to = named if named is not ROOT_LANE else None
        interrupt = build_interrupt(
            needed,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            subagent_run_id=attributed_to,
        )
        if interrupt is None or any(already.id == interrupt.id for already in interrupts):
            return
        interrupts.append(interrupt)
        if attributed_to is not None:
            owned.setdefault(attributed_to, []).append(interrupt.id)

    if prompt.open_requirements:
        for open_requirement in prompt.open_requirements:
            tool_execution = open_requirement.needed.requirement.tool_execution
            carry(
                open_requirement.needed,
                tool_execution.tool_call_id if tool_execution else None,
                tool_execution.tool_name if tool_execution else None,
                open_requirement.lane,
            )
    else:
        for tool_call in prompt.pending:
            carry(None, tool_call.tool_call_id, tool_call.tool_name, tool_call.lane)

    if owned and subagent_suspension_available():
        suspended: Dict[str, List[str]] = {lane: list(ids) for lane, ids in owned.items()}
        for lane in owned:
            for ancestor in state.ancestor_lanes(lane):
                suspended.setdefault(ancestor, [])
        state.suspended_lane_interrupts = suspended
    return interrupts


def _pause_nothing_can_answer(state: StreamState, prompt: _PausedPrompt) -> Optional[str]:
    """Why this pause can never be continued, when it cannot be.

    A resume has to answer every requirement the pause left open or the guard
    stops it, so one requirement no answer resolves is a run that has ended for
    good. Advertising the rest is what stranded it: the client answers everything
    it was told about and the guard refuses the resume over a requirement it was
    never told about, with nothing on the wire saying why.

    Read only where the interrupt outcome is emitted. With it off this interface
    advertises nothing and makes no claim about what a resume must carry, so its
    stream stays exactly what it was.
    """
    if not state.emit_interrupt_outcome:
        return None
    return pause_not_continuable([open_requirement.needed for open_requirement in prompt.open_requirements])


def on_run_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    prompt = _paused_tools_with_lanes(chunk, state)

    # Read before anything is announced or emitted, because a pause nothing can
    # answer ends the run as a failure here instead of prompting for it: the
    # pending calls are rendered as an approval a client can act on, and this run
    # cannot act on one. Reading the prompt above committed to nothing.
    stranded = _pause_nothing_can_answer(state, prompt)
    if stranded is not None:
        log_warning(
            f"AG-UI run {state.run_id} in session {state.thread_id} paused on something no client can "
            f"answer, so the run is reported as failed rather than waiting: {stranded}"
        )
        return on_run_error(chunk, state, _normalized_event_of(chunk), pause_not_continuable_because=stranded)

    # Announced here, before the closing order is chosen, because it is only now
    # certain which lanes the prompt really carries, and because a lane
    # announced needs the run end to terminate it.
    announcements = _announce_paused_lanes(state, prompt.lanes)
    try:
        return _run_end_events(chunk, state, prompt, announcements)
    except Exception:
        # None of the terminal reached the wire, the announcements above with
        # it, so the lanes they opened go back out of the record. Left in, the
        # cleanup the caller runs next would terminate a member the client was
        # never told started.
        _forget_unsent_lanes(state, prompt.lanes)
        raise


def _forget_unsent_lanes(state: StreamState, lanes: Dict[str, _PausedMemberLane]) -> None:
    """Unwind the lanes a pause opened, for a terminal that never reached the wire.

    A pause has to open its lanes before the rest of its terminal is built,
    because everything after reads them: which member an interrupt names, which
    lanes the drain closes as suspended, and the order the spans close in. The
    announcement that tells the client about them only leaves with the rest of
    that terminal, so a terminal that raises sends none of it, and what this
    interface holds has to go back to what the client was actually sent.

    Every lane here is one this pause opened: a lane the stream had already
    announced is not collected as pending, so none of these was known to the
    client before the announcement that never went out.
    """
    for run_id in lanes:
        state.open_subagents.pop(run_id, None)
        state.announced_subagents.pop(run_id, None)
        state.closed_subagents.discard(run_id)
        state.suspended_lane_interrupts.pop(run_id, None)


def _run_end_events(
    chunk: BaseRunOutputEvent,
    state: StreamState,
    prompt: _PausedPrompt,
    announcements: List[BaseEvent],
) -> List[BaseEvent]:
    """Everything a run's own end emits, from the closing sweep to the terminal.

    Split from the caller so the lanes its pause announced are unwound as one
    decision when any of this raises, rather than at each of the places it can.
    """
    # Built before the closing order runs, because the drain inside it reads
    # which lanes this suspended, and the announcements the caller made have
    # already settled which lanes the prompt names.
    outcome = interrupt_outcome(_pause_interrupts(state, prompt)) if state.emit_interrupt_outcome else None

    if (
        isinstance(chunk, (AgentRunPausedEvent, TeamRunPausedEvent))
        and prompt.dropped == prompt.carried
        and outcome is None
    ):
        # The run is waiting on something nobody can resolve, and the two ways
        # that happens reach the client differently, so they are recorded
        # differently. A call left out because the client already has a start
        # for it is neither of them: that one is on the wire to be acted on.
        # A terminal that carries the pause as an interrupt is neither: the
        # client is told what the run waits on and can answer it by id.
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
        # Copied so a write after the run cannot rewrite what the client was
        # sent, and guarded because a session state holds whatever a tool put in
        # it and a value with no copy of its own raises here. This is the last
        # thing the terminal builds, after the closing sweep: a raise would
        # discard every span end and the terminal with them, leaving the client
        # a message nothing closes. A state that cannot be copied is one the
        # protocol's encoder refuses too, and an event it refuses stops the
        # response body short of the terminal, so the snapshot is dropped with a
        # record rather than sent uncopied.
        try:
            copied_state = copy.deepcopy(final_state)
        except Exception:
            log_exception(
                f"AG-UI run {state.run_id} in session {state.thread_id} could not copy the session state "
                "it ends holding, so the run ends with no state snapshot"
            )
        else:
            events.append(StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copied_state))

    if state.emit_interrupt_outcome and outcome is None and prompt.carried:
        # The run is waiting, and the terminal cannot say so: the protocol
        # rejects an interrupt outcome with nothing in it, so this reaches the
        # client as the plain finished run it was before the outcome existed.
        # Every pending call read here was one the client cannot be shown, which
        # the sweep above has already recorded per call.
        log_warning(
            f"AG-UI run {state.run_id} in session {state.thread_id} paused with no interrupt the terminal "
            "can carry, so the pause reaches the client as a plain finished run"
        )

    # The outcome is named only when there is one. An omitted outcome is the
    # protocol's own back-compat shape, and naming the field to say there is none
    # would put it on the wire as an explicit null on a release that does not
    # declare it, which is not the same thing to a client.
    if outcome is not None:
        events.append(
            RunFinishedEvent(
                type=EventType.RUN_FINISHED,
                thread_id=state.thread_id,
                run_id=state.run_id,
                outcome=outcome,
            )
        )
    else:
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
