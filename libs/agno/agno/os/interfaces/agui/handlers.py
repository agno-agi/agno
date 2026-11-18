import copy
import json
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

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
from agno.os.interfaces.agui.state import StreamState
from agno.os.interfaces.agui.utils import to_json_str
from agno.reasoning.step import ReasoningStep
from agno.run.agent import RunContentEvent, RunEvent
from agno.run.agent import RunPausedEvent as AgentRunPausedEvent
from agno.run.base import BaseRunOutputEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.run.team import TeamRunEvent
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


def _close_text_message(state: StreamState) -> List[BaseEvent]:
    if not state.text_message_open:
        return []
    events: List[BaseEvent] = [TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id)]
    state.close_text_message()
    return events


def _open_reasoning(state: StreamState) -> Tuple[List[BaseEvent], str]:
    """Close any open text message and make sure a reasoning span is open. Returns its message id."""
    events = _close_text_message(state)
    reasoning_id, is_new = state.ensure_reasoning_started()
    if is_new:
        events.append(ReasoningStartEvent(type=EventType.REASONING_START, message_id=reasoning_id))
        events.append(
            ReasoningMessageStartEvent(
                type=EventType.REASONING_MESSAGE_START, message_id=reasoning_id, role="reasoning"
            )
        )
    return events, reasoning_id


def _close_reasoning(state: StreamState) -> List[BaseEvent]:
    if state.reasoning_message_id is None:
        return []
    reasoning_id = state.reasoning_message_id
    state.end_reasoning()
    return [
        ReasoningMessageEndEvent(type=EventType.REASONING_MESSAGE_END, message_id=reasoning_id),
        ReasoningEndEvent(type=EventType.REASONING_END, message_id=reasoning_id),
    ]


def _emit_state_delta(state: StreamState) -> List[BaseEvent]:
    if state.run_state is None:
        return []
    ops = state.compute_state_delta(state.run_state)
    if ops is None:
        return []
    state.set_state_snapshot(state.run_state)
    return [StateDeltaEvent(type=EventType.STATE_DELTA, delta=ops)]


def _close_open_spans(state: StreamState) -> List[BaseEvent]:
    """End any reasoning, tool call, or text message still open, so a terminal event never leaves a dangling span."""
    events: List[BaseEvent] = _close_reasoning(state)

    # Close remaining active tool calls
    for tool_call_id in list(state.active_tool_call_ids):
        if tool_call_id not in state.ended_tool_call_ids:
            events.append(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call_id))
            state.end_tool_call(tool_call_id)

    events.extend(_close_text_message(state))
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

    # Assistant text and reasoning alternate on one timeline of non-overlapping spans: whichever
    # channel produces a delta closes the other channel's open span first, and every delta is emitted
    # the moment it arrives. Three consequences follow and are accepted. A chunk carrying both text
    # and its own differing reasoning yields a reasoning span and then a fresh assistant message, so
    # consecutive such chunks give one message each. A reasoning-only chunk arriving mid-answer ends
    # that message and the rest of the answer streams under a new id. And a tool call arriving before
    # any assistant message exists has to mint one, which ends the reasoning span, while the same call
    # after assistant text does not, so one chain of thought reaches the client as a single reasoning
    # block or as several depending on where the tool calls fall.

    # Models that stream their own reasoning deliver it on the content stream rather than as
    # reasoning events, so it has to be routed to the reasoning span here or it never reaches AG-UI.
    # Some providers mirror the assistant text into reasoning_content, so a value byte-identical to
    # this chunk's own content is the answer repeated, not reasoning, and must not open a span.
    reasoning_content = getattr(chunk, "reasoning_content", None)
    if reasoning_content and reasoning_content != content:
        reasoning_events, reasoning_id = _open_reasoning(state)
        events.extend(reasoning_events)
        events.append(
            ReasoningMessageContentEvent(
                type=EventType.REASONING_MESSAGE_CONTENT,
                message_id=reasoning_id,
                delta=reasoning_content,
            )
        )
        if not content:
            return events

    # A chunk carrying only citations, provider data or media has no text, so it neither ends the
    # reasoning span nor opens a message inside it.
    if content:
        events.extend(_close_reasoning(state))
    elif state.reasoning_message_id is not None:
        return events

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

    # Close open text message before tool call, then parent the tool call to it
    if state.text_message_open:
        events.extend(_close_text_message(state))
        state.set_pending_tool_calls_parent_id(state.text_message_id)

    parent_message_id = state.get_parent_message_id_for_tool_call()

    # Create empty parent message if none exists (AG-UI protocol requirement)
    if not parent_message_id:
        # A message span must not open inside the reasoning span, so the synthetic parent
        # ends reasoning first. A tool call on its own leaves the span open.
        events.extend(_close_reasoning(state))
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
    events: List[BaseEvent] = _close_text_message(state)
    # A span may already be open; end it before minting a new id, or it never gets its end events.
    events.extend(_close_reasoning(state))

    reasoning_id = state.start_reasoning()
    events.append(ReasoningStartEvent(type=EventType.REASONING_START, message_id=reasoning_id))
    events.append(
        ReasoningMessageStartEvent(type=EventType.REASONING_MESSAGE_START, message_id=reasoning_id, role="reasoning")
    )
    return events


def on_reasoning_content_delta(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events, reasoning_id = _open_reasoning(state)

    content = getattr(chunk, "reasoning_content", None)
    if content:
        events.append(
            ReasoningMessageContentEvent(
                type=EventType.REASONING_MESSAGE_CONTENT, message_id=reasoning_id, delta=content
            )
        )
    return events


def on_reasoning_step(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events, reasoning_id = _open_reasoning(state)

    step_num = state.next_reasoning_step()
    step_content = getattr(chunk, "content", None)
    delta = _format_reasoning_step(step_content, step_num)
    if delta:
        events.append(
            ReasoningMessageContentEvent(type=EventType.REASONING_MESSAGE_CONTENT, message_id=reasoning_id, delta=delta)
        )
    return events


def on_reasoning_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    return _close_reasoning(state)


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


def on_run_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events = _close_open_spans(state)

    # 1. Collect paused tools for frontend rendering
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

    if paused_tools:
        assistant_message_id = str(uuid.uuid4())
        events.append(
            TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=assistant_message_id,
                role="assistant",
            )
        )

        content = getattr(chunk, "content", None)
        if content:
            events.append(
                TextMessageContentEvent(
                    type=EventType.TEXT_MESSAGE_CONTENT,
                    message_id=assistant_message_id,
                    delta=str(content),
                )
            )

        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=assistant_message_id))

        for tool in paused_tools:
            if tool.tool_call_id is None or tool.tool_name is None:
                continue

            events.append(
                ToolCallStartEvent(
                    type=EventType.TOOL_CALL_START,
                    tool_call_id=tool.tool_call_id,
                    tool_call_name=tool.tool_name,
                    parent_message_id=assistant_message_id,
                )
            )

            events.append(
                ToolCallArgsEvent(
                    type=EventType.TOOL_CALL_ARGS,
                    tool_call_id=tool.tool_call_id,
                    delta=json.dumps(tool.tool_args),
                )
            )

            events.append(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool.tool_call_id))

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
