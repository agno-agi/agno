import copy
import json
import uuid
from typing import Any, List, Optional

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
    RunErrorEvent,
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

from agno.os.interfaces.agui.state import StreamState
from agno.reasoning.step import ReasoningStep
from agno.run.agent import RunContentEvent, RunEvent, RunPausedEvent
from agno.run.base import BaseRunOutputEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import TeamRunEvent
from agno.run.workflow import WorkflowRunEvent
from agno.utils.message import get_text_from_message
from agno.workflow.types import StepType


# Workflow terminal events routed to process_completion
_WORKFLOW_TERMINAL_VALUES = frozenset(
    {
        WorkflowRunEvent.workflow_completed.value,
        WorkflowRunEvent.workflow_error.value,
    }
)

# Workflow structural events surfaced as CustomEvents
_WORKFLOW_STRUCTURAL_VALUES = frozenset(e.value for e in WorkflowRunEvent) - _WORKFLOW_TERMINAL_VALUES

# All terminal events that trigger completion handling
_COMPLETION_EVENTS = frozenset(
    {
        RunEvent.run_completed.value,
        RunEvent.run_paused.value,
        TeamRunEvent.run_completed.value,
        TeamRunEvent.run_paused.value,
        WorkflowRunEvent.workflow_completed.value,
        WorkflowRunEvent.workflow_error.value,
    }
)


def _event_value(chunk: BaseRunOutputEvent) -> str:
    event = getattr(chunk, "event", None)
    if event is None:
        return ""
    return event.value if hasattr(event, "value") else str(event)


def _normalize_event(event: str) -> str:
    return event.removeprefix("Team")


# Content extraction


def _extract_content(chunk: BaseRunOutputEvent) -> str:
    event = getattr(chunk, "event", None)
    if event == RunEvent.run_content:
        return _extract_agent_content(chunk)  # type: ignore
    if event == TeamRunEvent.run_content:
        return _extract_team_content(chunk)  # type: ignore
    return ""


def _extract_agent_content(response: RunContentEvent) -> str:
    if hasattr(response, "messages") and response.messages:  # type: ignore
        for msg in reversed(response.messages):  # type: ignore
            if hasattr(msg, "role") and msg.role == "assistant" and hasattr(msg, "content") and msg.content:
                return get_text_from_message(msg.content)
    return get_text_from_message(response.content) if response.content is not None else ""


def _extract_team_content(response: TeamRunContentEvent) -> str:
    parts = []
    if hasattr(response, "member_responses") and response.member_responses:  # type: ignore
        for member_resp in response.member_responses:  # type: ignore
            if isinstance(member_resp, RunContentEvent):
                content = _extract_agent_content(member_resp)
            elif isinstance(member_resp, TeamRunContentEvent):
                content = _extract_team_content(member_resp)
            else:
                content = ""
            if content:
                parts.append(f"Team member: {content}")
    main = get_text_from_message(response.content) if response.content is not None else ""
    return main + ("\n".join(parts) if parts else "")


def _format_reasoning_step(step: Optional[ReasoningStep], step_number: int = 0) -> str:
    if step is None:
        return ""
    parts: List[str] = []
    title = step.title or "Thinking"
    parts.append(f"## Step {step_number}: {title}" if step_number > 0 else f"## {title}")
    if step.reasoning:
        parts.append(step.reasoning)
    if step.action:
        parts.append(f"Action: {step.action}")
    if step.result:
        parts.append(f"Result: {step.result}")
    if step.confidence is not None:
        parts.append(f"Confidence: {step.confidence}")
    return "\n".join(parts) + "\n\n"


def _render_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, (list, dict)):
        return json.dumps(content, default=str)
    return str(content)


# Event emission helpers


def _text_message_triplet(text: str) -> List[BaseEvent]:
    message_id = str(uuid.uuid4())
    return [
        TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=message_id, role="assistant"),
        TextMessageContentEvent(type=EventType.TEXT_MESSAGE_CONTENT, message_id=message_id, delta=text),
        TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id),
    ]


def _close_text_if_open(state: StreamState) -> List[BaseEvent]:
    if not state.text_message_open:
        return []
    events = [TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id)]
    state.close_text_message()
    return events


def _ensure_reasoning_open(state: StreamState) -> tuple[str, List[BaseEvent]]:
    reasoning_id, is_new = state.ensure_reasoning_started()
    if not is_new:
        return reasoning_id, []
    return reasoning_id, [
        ReasoningStartEvent(type=EventType.REASONING_START, message_id=reasoning_id),
        ReasoningMessageStartEvent(type=EventType.REASONING_MESSAGE_START, message_id=reasoning_id, role="reasoning"),
    ]


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


# Workflow provenance logic


def _leaf_streamed(node: Any) -> Optional[bool]:
    # Parallel/Loop fan-out has no single final leaf
    if getattr(node, "step_type", None) in (StepType.PARALLEL, StepType.LOOP):
        return None
    # Container nodes descend to final child
    sub = getattr(node, "steps", None)
    if sub:
        return _leaf_streamed(sub[-1])
    # Leaf executor type determines if it streamed
    executor = getattr(node, "executor_type", None)
    if executor in ("agent", "team"):
        return True
    if executor == "function":
        return False
    return None


def _final_leaf_streamed(chunk: BaseRunOutputEvent) -> Optional[bool]:
    results = getattr(chunk, "step_results", None)
    if not results:
        return None
    return _leaf_streamed(results[-1])


# Event handlers


def on_run_content(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []
    content = _extract_content(chunk)

    if not state.text_message_open:
        message_id = state.open_text_message()
        state.clear_pending_tool_calls_parent_id()
        events.append(TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=message_id, role="assistant"))

    if content:
        state.streamed_any_text = True
        events.append(
            TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT, message_id=state.text_message_id, delta=content
            )
        )

    return events


def on_tool_call_started(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    tool = getattr(chunk, "tool", None)
    if tool is None:
        return []

    events: List[BaseEvent] = []

    # 1. Close open text message
    if state.text_message_open:
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id))
        state.set_pending_tool_calls_parent_id(state.text_message_id)
        state.close_text_message()

    # 2. Get or create parent message
    parent_id = state.get_parent_message_id_for_tool_call()
    if not parent_id:
        parent_id = str(uuid.uuid4())
        events.append(TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=parent_id, role="assistant"))
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=parent_id))
        state.set_pending_tool_calls_parent_id(parent_id)

    # 3. Emit tool call
    events.append(
        ToolCallStartEvent(
            type=EventType.TOOL_CALL_START,
            tool_call_id=tool.tool_call_id,
            tool_call_name=tool.tool_name,
            parent_message_id=parent_id,
        )
    )
    events.append(
        ToolCallArgsEvent(
            type=EventType.TOOL_CALL_ARGS, tool_call_id=tool.tool_call_id, delta=json.dumps(tool.tool_args)
        )
    )

    state.start_tool_call(tool.tool_call_id)
    return events


def on_tool_call_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    tool = getattr(chunk, "tool", None)
    if tool is None or tool.tool_call_id in state.ended_tool_call_ids:
        return []

    events: List[BaseEvent] = [ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool.tool_call_id)]
    state.end_tool_call(tool.tool_call_id)

    if tool.result is not None:
        events.append(
            ToolCallResultEvent(
                type=EventType.TOOL_CALL_RESULT,
                tool_call_id=tool.tool_call_id,
                content=str(tool.result),
                role="tool",
                message_id=str(uuid.uuid4()),
            )
        )

    events.extend(_emit_state_delta(state))
    return events


def on_reasoning_started(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events = _close_text_if_open(state)
    reasoning_id = state.start_reasoning()
    events.append(ReasoningStartEvent(type=EventType.REASONING_START, message_id=reasoning_id))
    events.append(
        ReasoningMessageStartEvent(type=EventType.REASONING_MESSAGE_START, message_id=reasoning_id, role="reasoning")
    )
    return events


def on_reasoning_content_delta(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events = _close_text_if_open(state)
    reasoning_id, start_events = _ensure_reasoning_open(state)
    events.extend(start_events)

    content = getattr(chunk, "reasoning_content", None)
    if content:
        events.append(
            ReasoningMessageContentEvent(
                type=EventType.REASONING_MESSAGE_CONTENT, message_id=reasoning_id, delta=content
            )
        )
    return events


def on_reasoning_step(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events = _close_text_if_open(state)
    reasoning_id, start_events = _ensure_reasoning_open(state)
    events.extend(start_events)

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
    name = chunk.__class__.__name__
    try:
        value: Any = chunk.to_dict()
    except Exception:
        value = getattr(chunk, "content", None)
    return [CustomEvent(name=name, value=value)]


def on_workflow_cancelled(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    state.cancelled = True
    return on_custom_event(chunk, state)


def on_unknown_event(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    try:
        raw_dict = chunk.to_dict()
    except Exception:
        raw_dict = {"event": str(getattr(chunk, "event", "unknown"))}
    return [RawEvent(type=EventType.RAW, event=raw_dict, source="agno")]


# Stream lifecycle


def _close_all_streams(state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []
    events.extend(_close_reasoning(state))

    for tool_call_id in list(state.active_tool_call_ids):
        if tool_call_id not in state.ended_tool_call_ids:
            events.append(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call_id))
            state.end_tool_call(tool_call_id)

    events.extend(_close_text_if_open(state))
    return events


def _emit_paused_tools(chunk: RunPausedEvent, state: StreamState) -> List[BaseEvent]:
    external_tools = chunk.tools_awaiting_external_execution
    if not external_tools:
        return []

    events: List[BaseEvent] = []
    message_id = str(uuid.uuid4())

    # Emit parent message
    events.append(TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=message_id, role="assistant"))
    content = getattr(chunk, "content", None)
    if content:
        state.streamed_any_text = True
        events.append(
            TextMessageContentEvent(type=EventType.TEXT_MESSAGE_CONTENT, message_id=message_id, delta=str(content))
        )
    events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id))

    # Emit each tool call
    for tool in external_tools:
        if tool.tool_call_id is None or tool.tool_name is None:
            continue
        events.append(
            ToolCallStartEvent(
                type=EventType.TOOL_CALL_START,
                tool_call_id=tool.tool_call_id,
                tool_call_name=tool.tool_name,
                parent_message_id=message_id,
            )
        )
        events.append(
            ToolCallArgsEvent(
                type=EventType.TOOL_CALL_ARGS, tool_call_id=tool.tool_call_id, delta=json.dumps(tool.tool_args)
            )
        )
        events.append(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool.tool_call_id))

    return events


def _emit_final_state(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    if state.run_state is None:
        return []
    authoritative = getattr(chunk, "session_state", None)
    final = authoritative if authoritative is not None else state.run_state
    return [StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copy.deepcopy(final))]


def _finalize_run(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []
    if isinstance(chunk, RunPausedEvent):
        events.extend(_emit_paused_tools(chunk, state))
    events.extend(_emit_final_state(chunk, state))
    events.append(RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=state.thread_id, run_id=state.run_id))
    return events


def _workflow_completion_events(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    # Workflow error
    if _event_value(chunk) == WorkflowRunEvent.workflow_error.value:
        error = getattr(chunk, "error", None) or "Workflow error occurred"
        return [RunErrorEvent(type=EventType.RUN_ERROR, message=str(error))]

    # Cancelled workflow: don't render the cancel reason as an answer
    if state.cancelled:
        return []

    # Get content
    content = getattr(chunk, "content", None)
    if content is None:
        return []
    rendered = _render_content(content)
    if not rendered.strip():
        return []

    # Suppress if final leaf already streamed
    if _final_leaf_streamed(chunk) and state.streamed_any_text:
        return []

    return _text_message_triplet(rendered)


def on_run_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    return _close_all_streams(state) + _finalize_run(chunk, state)


# Handler registry

HANDLERS = {
    RunEvent.run_content.value: on_run_content,
    RunEvent.tool_call_started.value: on_tool_call_started,
    RunEvent.tool_call_completed.value: on_tool_call_completed,
    RunEvent.reasoning_started.value: on_reasoning_started,
    RunEvent.reasoning_content_delta.value: on_reasoning_content_delta,
    RunEvent.reasoning_step.value: on_reasoning_step,
    RunEvent.reasoning_completed.value: on_reasoning_completed,
    RunEvent.custom_event.value: on_custom_event,
}

HANDLERS.update({value: on_custom_event for value in _WORKFLOW_STRUCTURAL_VALUES})
HANDLERS[WorkflowRunEvent.workflow_cancelled.value] = on_workflow_cancelled


# Public API


def is_completion_event(chunk: BaseRunOutputEvent) -> bool:
    return _event_value(chunk) in _COMPLETION_EVENTS


def process_event(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    event_val = _event_value(chunk)
    if not event_val:
        return on_unknown_event(chunk, state)

    handler = HANDLERS.get(_normalize_event(event_val))
    if handler:
        return handler(chunk, state)

    return on_unknown_event(chunk, state)


def process_completion(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    event_val = _event_value(chunk)

    # Regular agent/team completion
    if event_val not in _WORKFLOW_TERMINAL_VALUES:
        return on_run_completed(chunk, state)

    # Workflow completion
    events = _close_all_streams(state)
    events.extend(_workflow_completion_events(chunk, state))
    if event_val == WorkflowRunEvent.workflow_completed.value:
        events.extend(_finalize_run(chunk, state))
    return events
