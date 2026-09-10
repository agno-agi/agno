import json
import uuid
from typing import Any, Callable, Dict, List, Optional

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

from agno.models.response import ToolExecution
from agno.os.interfaces.agui.state import StateDeltaUnavailable, StreamState, client_state
from agno.os.interfaces.agui.utils import to_json_str
from agno.reasoning.step import ReasoningStep
from agno.run.agent import RunContentEvent, RunEvent
from agno.run.agent import RunPausedEvent as AgentRunPausedEvent
from agno.run.base import BaseRunOutputEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.run.team import TeamRunEvent
from agno.utils.log import log_warning
from agno.utils.message import get_text_from_message

EventHandler = Callable[[BaseRunOutputEvent, StreamState], List[BaseEvent]]


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
    try:
        ops = state.compute_state_delta(state.run_state)
    except StateDeltaUnavailable as e:
        if e.reason == StateDeltaUnavailable.STATE_NOT_SENDABLE:
            # A snapshot would carry the very state the encoder has just
            # refused, and the encoder runs after this handler, on the way to
            # the socket: the event would take the rest of the response with
            # it, terminal event included. So nothing goes out, and the
            # baseline stays where the client is, which is what lets a later
            # change the encoder can render be described against what it holds.
            if state.should_warn_delta_fallback(e.reason):
                log_warning(f"{e} The client keeps the state it was last sent. {state.run_label()}")
            return []
        # State did change, so staying quiet would hide the mutation from the
        # client for the rest of the run. A full snapshot carries everything
        # the patch would have.
        if state.should_warn_delta_fallback(e.reason):
            log_warning(f"{e} Sending a full STATE_SNAPSHOT instead. {state.run_label()}")
        snapshot = client_state(state.run_state)
        state.set_state_snapshot(state.run_state)
        return [StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=snapshot)]
    if ops is None:
        return []
    state.set_state_snapshot(state.run_state)
    return [StateDeltaEvent(type=EventType.STATE_DELTA, delta=ops)]


def _close_open_spans(state: StreamState) -> List[BaseEvent]:
    """End any reasoning, tool call, or text message still open, so a terminal event never leaves a dangling span."""
    events: List[BaseEvent] = []

    # Close orphaned reasoning session
    if state.reasoning_message_id is not None:
        events.append(
            ReasoningMessageEndEvent(type=EventType.REASONING_MESSAGE_END, message_id=state.reasoning_message_id)
        )
        events.append(ReasoningEndEvent(type=EventType.REASONING_END, message_id=state.reasoning_message_id))
        state.end_reasoning()

    # Close remaining active tool calls
    for tool_call_id in list(state.active_tool_call_ids):
        events.append(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call_id))
        state.end_tool_call(tool_call_id)

    # Close open text message
    if state.text_message_open:
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id))
        state.close_text_message()

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


def _open_tool_call(
    state: StreamState, tool_call_id: str, tool_call_name: str, args_streaming: bool = False
) -> List[BaseEvent]:
    """TOOL_CALL_START for one call, parented to the message open at this moment.

    Shared by the events that can be the first sight of a call: an argument
    fragment and Agno's own announcement. Every caller has to have found the
    call closed first, because a second start for a call the client holds open
    is where its verifier stops reading the run.
    """
    events: List[BaseEvent] = []

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
            tool_call_id=tool_call_id,
            tool_call_name=tool_call_name,
            parent_message_id=parent_message_id,
        )
    )

    state.start_tool_call(tool_call_id, args_streaming=args_streaming)
    return events


def on_tool_call_args_delta(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    """Pass one fragment of a tool call's arguments straight through to the client.

    A provider streams a call's arguments in pieces, and these usually arrive
    before Agno has the finished call to announce, so a fragment carrying
    argument text for a call nothing has opened yet is what opens it. That is
    also why the fragment carries the tool name: there is nothing else to read
    it off yet.
    """
    events: List[BaseEvent] = []
    tool_call_id = getattr(chunk, "tool_call_id", None)
    if not tool_call_id:
        return events

    delta = getattr(chunk, "tool_args_delta", None)
    if not delta:
        # A provider can name a call on a fragment carrying no argument text at
        # all. Opening the call on that would leave the client a start and an
        # end with nothing between them, so the call waits for something to be
        # said about it.
        return events

    if state.tool_call_open(tool_call_id):
        if state.streamed_tool_call_args(tool_call_id) is None:
            # Agno's announcement opened this call and carried its whole
            # argument string, so passing this fragment on would append to
            # arguments the client already holds complete.
            return events
    else:
        tool_name = getattr(chunk, "tool_name", None)
        if not tool_name:
            # A call is opened once and under one name, and the name is what a
            # client renders it as. A fragment that names no tool cannot open
            # one, so the call waits for Agno's announcement of the finished
            # call, which names it and carries its whole argument string.
            return events
        events.extend(_open_tool_call(state, tool_call_id, tool_name, args_streaming=True))

    events.append(ToolCallArgsEvent(type=EventType.TOOL_CALL_ARGS, tool_call_id=tool_call_id, delta=delta))
    state.note_streamed_tool_call_args(tool_call_id, delta)
    return events


def on_tool_call_started(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []
    tool = getattr(chunk, "tool", None)
    if tool is None:
        return events

    # The call is already open, which means a fragment opened it, so this
    # announcement neither opens it again nor carries the arguments:
    # TOOL_CALL_ARGS appends, so anything sent here would be added to the text
    # the fragments carried, whether or not they carried all of it.
    if state.tool_call_open(tool.tool_call_id):
        return events

    events.extend(_open_tool_call(state, tool.tool_call_id, tool.tool_name))

    events.append(
        ToolCallArgsEvent(
            type=EventType.TOOL_CALL_ARGS,
            tool_call_id=tool.tool_call_id,
            delta=json.dumps(tool.tool_args),
        )
    )

    return events


def _close_tool_call(state: StreamState, tool_call_id: str, result: Optional[str]) -> List[BaseEvent]:
    """End an open call on the wire and report what it left behind.

    Every call that ends with something to report ends here, so a call is
    released from the open record and its result carried the same way however
    it ended. ``result`` is what the call is to be shown as having produced,
    an error text included, and ``None`` where it produced nothing to show.
    """
    events: List[BaseEvent] = [ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call_id)]
    state.end_tool_call(tool_call_id)

    if result is not None:
        events.append(
            ToolCallResultEvent(
                type=EventType.TOOL_CALL_RESULT,
                tool_call_id=tool_call_id,
                content=to_json_str(result),
                role="tool",
                # Use tool_call_id as message_id so frontend can link result to the tool call
                message_id=tool_call_id,
            )
        )

    events.extend(_emit_state_delta(state))
    return events


def on_tool_call_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []
    tool = getattr(chunk, "tool", None)
    if tool is None:
        return events

    # Nothing to close, and nothing to report the result of: either the call
    # was never opened on the wire, or a completion for it has already been
    # handled. An end for a call the client does not hold open is where its
    # verifier stops reading the run.
    if not state.tool_call_open(tool.tool_call_id):
        return events

    return _close_tool_call(state, tool.tool_call_id, tool.result)


def on_tool_call_error(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    """Close a call that failed, with what went wrong as its result.

    A call the run refuses once its arguments have gone out is never started
    and never completed, so this is the only event that says anything about
    it: unhandled, it reaches the client as an opaque passthrough and leaves
    the call pending until the run ends. What the failure says is Agno's to
    word, a refusal included, so it is carried rather than restated.

    An error for a call that is not open closes nothing. An ordinary tool
    failure is announced as a completion first, which has already closed the
    call and carried the same text as its result, and an end for a call the
    client does not hold open is where its verifier stops reading the run.
    """
    events: List[BaseEvent] = []
    tool = getattr(chunk, "tool", None)
    if tool is None:
        return events

    tool_call_id = tool.tool_call_id
    if not tool_call_id or not state.tool_call_open(tool_call_id):
        return events

    error = getattr(chunk, "error", None)
    return _close_tool_call(state, tool_call_id, error if error is not None else tool.result)


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


def on_run_error(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    """Close open spans, then emit the terminal AG-UI error event. Nothing may follow RUN_ERROR."""
    try:
        raw_event: Any = chunk.to_dict()
    except Exception:
        raw_event = {"event": str(getattr(chunk, "event", "RunError"))}

    message = getattr(chunk, "content", None) or "Run failed"
    error_type = getattr(chunk, "error_type", None)

    events = _close_open_spans(state)
    events.append(
        AGUIRunErrorEvent(
            type=EventType.RUN_ERROR,
            message=str(message),
            code=error_type,
            rawEvent=raw_event,
        )
    )
    return events


def _paused_tool_calls(chunk: BaseRunOutputEvent) -> List[ToolExecution]:
    """The calls a paused run is waiting on the client for."""
    paused_tools: List[ToolExecution] = []
    if isinstance(chunk, AgentRunPausedEvent):
        paused_tools = (
            chunk.tools_awaiting_external_execution
            + chunk.tools_requiring_confirmation
            + chunk.tools_requiring_user_input
        )
    elif isinstance(chunk, TeamRunPausedEvent):
        # Leader tools from .tools, member tools from active_requirements
        paused_tools = (
            chunk.tools_awaiting_external_execution
            + chunk.tools_requiring_confirmation
            + chunk.tools_requiring_user_input
        )
        for req in chunk.active_requirements:
            if req.member_agent_id and req.tool_execution:
                paused_tools.append(req.tool_execution)
    return paused_tools


def on_run_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    paused_tools = _paused_tool_calls(chunk)
    events = _close_open_spans(state)

    # A paused call the stream already opened, whichever opener did it, has
    # been carried and closed by now: its fragments carried its arguments and
    # the close above ended it. Rendering it again would give the client a
    # second call under the same id, and a second stand-in message to parent it
    # to. A pause can also name the same call twice, once as a team leader's
    # and once as its member's.
    tools_to_render: List[ToolExecution] = []
    for tool in paused_tools:
        if tool.tool_call_id is None or tool.tool_name is None:
            continue
        if state.tool_call_ended(tool.tool_call_id) or any(
            tool.tool_call_id == picked.tool_call_id for picked in tools_to_render
        ):
            continue
        tools_to_render.append(tool)
    paused_content = getattr(chunk, "content", None) if paused_tools else None

    if tools_to_render or paused_content:
        assistant_message_id = str(uuid.uuid4())
        events.append(
            TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=assistant_message_id,
                role="assistant",
            )
        )

        if paused_content:
            events.append(
                TextMessageContentEvent(
                    type=EventType.TEXT_MESSAGE_CONTENT,
                    message_id=assistant_message_id,
                    delta=str(paused_content),
                )
            )

        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=assistant_message_id))

        for tool in tools_to_render:
            tool_call_id = str(tool.tool_call_id)
            events.append(
                ToolCallStartEvent(
                    type=EventType.TOOL_CALL_START,
                    tool_call_id=tool_call_id,
                    tool_call_name=tool.tool_name,
                    parent_message_id=assistant_message_id,
                )
            )
            state.start_tool_call(tool_call_id)

            events.append(
                ToolCallArgsEvent(
                    type=EventType.TOOL_CALL_ARGS,
                    tool_call_id=tool_call_id,
                    delta=json.dumps(tool.tool_args),
                )
            )

            events.append(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call_id))
            state.end_tool_call(tool_call_id)

    # Emit final state snapshot
    if state.run_state is not None:
        authoritative_state = getattr(chunk, "session_state", None)
        final_state = authoritative_state if authoritative_state is not None else state.run_state
        events.append(StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=client_state(final_state)))

    events.append(RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=state.thread_id, run_id=state.run_id))
    return events


def _normalize_event(event: str) -> str:
    """Strip 'Team' prefix so agent and team events use the same handlers."""
    return event.removeprefix("Team")


# Maps normalized event names to handler functions
HANDLERS: Dict[str, EventHandler] = {
    RunEvent.run_content.value: on_run_content,
    RunEvent.tool_call_started.value: on_tool_call_started,
    RunEvent.tool_call_args_delta.value: on_tool_call_args_delta,
    RunEvent.tool_call_completed.value: on_tool_call_completed,
    RunEvent.tool_call_error.value: on_tool_call_error,
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


def is_completion_event(chunk: BaseRunOutputEvent) -> bool:
    """Check if this event is terminal for the stream (completed, paused, or error)."""
    event = getattr(chunk, "event", None)
    if event is None:
        return False
    event_value = event.value if hasattr(event, "value") else str(event)
    return event_value in _COMPLETION_EVENTS


def process_event(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    """Process a single Agno event and return AG-UI events to emit."""
    event = getattr(chunk, "event", None)
    if event is None:
        return on_unknown_event(chunk, state)

    event_value = event.value if hasattr(event, "value") else str(event)
    normalized = _normalize_event(event_value)

    handler = HANDLERS.get(normalized)
    if handler:
        return handler(chunk, state)

    return on_unknown_event(chunk, state)


def process_completion(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    """Process a terminal event and return the corresponding AG-UI events."""
    event = getattr(chunk, "event", None)
    event_value = event.value if event is not None and hasattr(event, "value") else str(event)
    if _normalize_event(event_value) == RunEvent.run_error.value:
        return on_run_error(chunk, state)
    return on_run_completed(chunk, state)
