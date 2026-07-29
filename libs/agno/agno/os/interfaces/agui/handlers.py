import copy
import json
import uuid
from typing import Any, Callable, Dict, List, Optional

from ag_ui.core import (
    ActivitySnapshotEvent,
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

from agno.models.response import ToolExecution
from agno.os.interfaces.agui.state import StreamState
from agno.os.interfaces.agui.utils import to_json_str
from agno.reasoning.step import ReasoningStep
from agno.run.agent import BaseAgentRunEvent, RunContentEvent, RunEvent
from agno.run.agent import RunPausedEvent as AgentRunPausedEvent
from agno.run.base import BaseRunOutputEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.run.team import TeamRunEvent
from agno.utils.message import get_text_from_message

EventHandler = Callable[[BaseRunOutputEvent, StreamState], List[BaseEvent]]

# activity_type identifying an Agno team member's live state to AG-UI frontends.
TEAM_MEMBER_ACTIVITY_TYPE = "agno.team_member"


def _extract_response_chunk_content(response: RunContentEvent) -> str:
    # RunContentEvent can carry text in .messages (list) or .content (direct)
    # AG-UI needs a plain string for TEXT_MESSAGE_CONTENT delta
    if hasattr(response, "messages") and response.messages:  # type: ignore
        for msg in reversed(response.messages):  # type: ignore
            if hasattr(msg, "role") and msg.role == "assistant" and hasattr(msg, "content") and msg.content:
                return get_text_from_message(msg.content)
    return get_text_from_message(response.content) if response.content is not None else ""


def _extract_team_response_chunk_content(response: TeamRunContentEvent) -> str:
    # Team-leader chunks carry only the leader's own token in .content. Member
    # output is NOT folded in here — member chunks stream separately as agent
    # RunContentEvents and are surfaced via Activity snapshots (see on_run_content).
    return get_text_from_message(response.content) if response.content is not None else ""


def _is_member_chunk(chunk: BaseRunOutputEvent) -> bool:
    """True when this chunk comes from a team member (not the team leader).

    Member events are agent-level events whose parent_run_id was set to the team
    run_id when delegated (see team/_default_tools.py). The team leader emits
    BaseTeamRunEvent instead, so agent-level events with a parent are members.
    """
    return isinstance(chunk, BaseAgentRunEvent) and getattr(chunk, "parent_run_id", None) is not None


def _member_key(chunk: BaseRunOutputEvent) -> str:
    """Stable per-member key for the run: member run_id, falling back to agent_id."""
    run_id = getattr(chunk, "run_id", None)
    agent_id = getattr(chunk, "agent_id", None)
    return run_id or agent_id or "member"


def _member_activity_snapshot(chunk: BaseRunOutputEvent, state: StreamState) -> ActivitySnapshotEvent:
    """Build the ACTIVITY_SNAPSHOT for a member chunk, updating its live state."""
    key = _member_key(chunk)
    message_id, content = state.get_or_create_member(key)
    # Identity fields are filled in once known; chunks always carry them but we
    # only overwrite when present so a later sparse chunk can't blank them out.
    agent_id = getattr(chunk, "agent_id", None)
    agent_name = getattr(chunk, "agent_name", None)
    parent_run_id = getattr(chunk, "parent_run_id", None)
    run_id = getattr(chunk, "run_id", None)
    if agent_id:
        content["agentId"] = agent_id
    if agent_name:
        content["agentName"] = agent_name
    if run_id:
        content["runId"] = run_id
    if parent_run_id:
        content["parentRunId"] = parent_run_id
    content["updatedAt"] = getattr(chunk, "created_at", None)
    return ActivitySnapshotEvent(
        type=EventType.ACTIVITY_SNAPSHOT,
        message_id=message_id,
        activity_type=TEAM_MEMBER_ACTIVITY_TYPE,
        content=dict(content),
        replace=True,
    )


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


def on_run_content(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    # Team member chunks are surfaced as Activity snapshots, not folded into the
    # leader's text message. This preserves which member produced the content.
    if _is_member_chunk(chunk):
        _, content = state.get_or_create_member(_member_key(chunk))
        content["text"] += _extract_response_chunk_content(chunk)  # type: ignore
        content["status"] = "running"
        return [_member_activity_snapshot(chunk, state)]

    events: List[BaseEvent] = []

    event = getattr(chunk, "event", None)
    if event == TeamRunEvent.run_content:
        content_str = _extract_team_response_chunk_content(chunk)  # type: ignore
    else:
        content_str = _extract_response_chunk_content(chunk)  # type: ignore

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

    if content_str:
        events.append(
            TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=state.text_message_id,
                delta=content_str,
            )
        )

    return events


def on_tool_call_started(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []
    tool = getattr(chunk, "tool", None)
    if tool is None:
        return events

    # Member tool call: reflect it on the member's Activity and skip the
    # leader-oriented text-message bookkeeping below.
    if _is_member_chunk(chunk):
        _, content = state.get_or_create_member(_member_key(chunk))
        content["status"] = "tool_calling"
        content["currentTool"] = tool.tool_name
        return [_member_activity_snapshot(chunk, state)]

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
    return events


def on_tool_call_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []
    tool = getattr(chunk, "tool", None)
    if tool is None:
        return events

    if _is_member_chunk(chunk):
        _, content = state.get_or_create_member(_member_key(chunk))
        content["status"] = "running"
        content["currentTool"] = None
        return [_member_activity_snapshot(chunk, state)]

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


def on_member_content_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    """Member finished producing content: mark its Activity completed."""
    if not _is_member_chunk(chunk):
        return []
    _, content = state.get_or_create_member(_member_key(chunk))
    content["status"] = "completed"
    content["currentTool"] = None
    return [_member_activity_snapshot(chunk, state)]


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


def on_run_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
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
        if tool_call_id not in state.ended_tool_call_ids:
            events.append(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call_id))
            state.end_tool_call(tool_call_id)

    # Close open text message
    if state.text_message_open:
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id))
        state.close_text_message()

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
    RunEvent.run_content_completed.value: on_member_content_completed,
    RunEvent.custom_event.value: on_custom_event,
}

# Terminal events that trigger completion handling
_COMPLETION_EVENTS = frozenset(
    {
        RunEvent.run_completed.value,
        RunEvent.run_paused.value,
        TeamRunEvent.run_completed.value,
        TeamRunEvent.run_paused.value,
    }
)


def is_completion_event(chunk: BaseRunOutputEvent) -> bool:
    """Check if this event signals stream completion."""
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
    """Process completion event (run_completed/run_paused) and return cleanup events."""
    return on_run_completed(chunk, state)
