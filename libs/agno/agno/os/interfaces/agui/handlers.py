import copy
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
    RunErrorEvent,
    RunFinishedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    StepFinishedEvent,
    StepStartedEvent,
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
from agno.run.agent import RunContentEvent, RunEvent
from agno.run.agent import RunPausedEvent as AgentRunPausedEvent
from agno.run.base import BaseRunOutputEvent, RunStatus
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.run.team import TeamRunEvent
from agno.run.workflow import WorkflowRunEvent
from agno.utils.message import get_text_from_message
from agno.workflow.types import StepType

# --- Type aliases ---

EventHandler = Callable[[BaseRunOutputEvent, StreamState], List[BaseEvent]]

# --- Workflow event constants ---

_WF = WorkflowRunEvent

# Truncate step output to keep STATE deltas small
_MAX_STEP_OUTPUT = 500

# Terminal events route to process_completion; workflow_cancelled is NOT terminal
# because it surfaces as a STATE status and the run finalizes on the trailing completed event
_WORKFLOW_TERMINAL_VALUES = frozenset({_WF.workflow_completed.value, _WF.workflow_error.value})

# All non-terminal workflow events route to progress handler
STRUCTURAL_EVENT_VALUES = frozenset(e.value for e in _WF) - _WORKFLOW_TERMINAL_VALUES

# Step pause/continue events map to the status they set
_STEP_STATUS_ON_EVENT: Dict[str, str] = {
    _WF.step_paused.value: "paused",
    _WF.step_executor_paused.value: "paused",
    _WF.step_output_review.value: "paused",
    _WF.step_continued.value: "running",
    _WF.step_executor_continued.value: "running",
}


# --- Shared helpers ---


def _event_value(chunk: BaseRunOutputEvent) -> str:
    event = getattr(chunk, "event", None)
    if event is None:
        return ""
    return event.value if hasattr(event, "value") else str(event)


def _normalize_event(event: str) -> str:
    # Strip "Team" prefix so agent and team events use same handlers
    return event.removeprefix("Team")


def _render_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, (list, dict)):
        return json.dumps(content, default=str)
    return str(content)


def _emit_state_delta(state: StreamState) -> List[BaseEvent]:
    if state.run_state is None:
        return []
    ops = state.compute_state_delta(state.run_state)
    if not ops:
        return []
    state.set_state_snapshot(state.run_state)
    return [StateDeltaEvent(type=EventType.STATE_DELTA, delta=ops)]


def _new_text_message(text: str) -> List[BaseEvent]:
    message_id = str(uuid.uuid4())
    return [
        TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=message_id, role="assistant"),
        TextMessageContentEvent(type=EventType.TEXT_MESSAGE_CONTENT, message_id=message_id, delta=text),
        TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id),
    ]


# --- Text content handlers ---


def _extract_response_chunk_content(response: RunContentEvent) -> str:
    # RunContentEvent carries text in .messages (list) or .content (direct)
    if hasattr(response, "messages") and response.messages:  # type: ignore
        for msg in reversed(response.messages):  # type: ignore
            if hasattr(msg, "role") and msg.role == "assistant" and hasattr(msg, "content") and msg.content:
                return get_text_from_message(msg.content)
    return get_text_from_message(response.content) if response.content is not None else ""


def _extract_team_response_chunk_content(response: TeamRunContentEvent) -> str:
    # Team responses nest member outputs; fold them into one text delta
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
        state.streamed_any_text = True
        events.append(
            TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=state.text_message_id,
                delta=content,
            )
        )

    return events


# --- Tool call handlers ---


def on_tool_call_started(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []
    tool = getattr(chunk, "tool", None)
    if tool is None:
        return events

    if state.text_message_open:
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id))
        state.set_pending_tool_calls_parent_id(state.text_message_id)
        state.close_text_message()

    parent_message_id = state.get_parent_message_id_for_tool_call()

    # AG-UI protocol requires tool calls to have a parent message
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
                message_id=tool.tool_call_id,
            )
        )

    events.extend(_emit_state_delta(state))
    return events


# --- Reasoning handlers ---


def on_reasoning_started(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []

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


# --- Custom and unknown event handlers ---


def on_custom_event(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    # User-provided name takes precedence; fallback to subclass name (e.g. "CustomerProfileEvent")
    custom_event_name = getattr(chunk, "name", None) or type(chunk).__name__

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


# --- Workflow progress tracking ---
#
# Workflow state shape in run_state:
#   workflow_progress: {run_id, status, steps: [{id, name, status, output}]}
#   steps: [{description, status}]  # Dojo-compatible format, synced automatically


def _get_workflow_progress(state: StreamState) -> Dict[str, Any]:
    # Reset when run_id changes to prevent stale state from prior turn leaking through
    if state.run_state is None:
        state.run_state = {}
    existing = state.run_state.get("workflow_progress")
    if existing is None or existing.get("run_id") != state.run_id:
        state.run_state["workflow_progress"] = {
            "run_id": state.run_id,
            "status": RunStatus.running.value,
            "steps": [],
        }
    return state.run_state["workflow_progress"]


def _sync_steps_to_dojo_format(state: StreamState) -> None:
    # Dojo agentic_generative_ui expects state.steps[{description, status}]
    if state.run_state is None or "workflow_progress" not in state.run_state:
        return
    wp_steps = state.run_state["workflow_progress"].get("steps", [])
    state.run_state["steps"] = [
        {
            "description": s.get("name", ""),
            # Dojo uses "pending" for in-progress steps
            "status": "pending" if s.get("status") == "running" else s.get("status", "pending"),
        }
        for s in wp_steps
    ]


def _ensure_state_baseline(state: StreamState) -> List[BaseEvent]:
    # First STATE_SNAPSHOT establishes the diff baseline for subsequent deltas
    if state.run_state is not None:
        return []
    state.run_state = {}
    state.set_state_snapshot(state.run_state)
    return [StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copy.deepcopy(state.run_state))]


def _truncate_step_output(content: Any) -> Optional[str]:
    if content is None:
        return None
    text = _render_content(content)
    return text[:_MAX_STEP_OUTPUT] if text else None


def _find_open_step(steps: List[Dict[str, Any]], step_id: Optional[str]) -> Optional[Dict[str, Any]]:
    # Match by step_id, not index, because Parallel siblings share index but have distinct ids
    for step in reversed(steps):
        if step["status"] in ("running", "paused") and step["id"] == step_id:
            return step
    return None


def _mark_workflow_completed(state: StreamState) -> None:
    progress = state.workflow_progress
    if progress is None:
        return
    if progress.get("status") == RunStatus.running.value:
        progress["status"] = RunStatus.completed.value
    # Steps still running at completion were skipped (e.g., on_error=skip)
    if progress.get("status") == RunStatus.completed.value:
        for step in progress["steps"]:
            if step["status"] == "running":
                step["status"] = "skipped"
    _sync_steps_to_dojo_format(state)


def _workflow_error_snapshot(state: StreamState) -> List[BaseEvent]:
    progress = state.workflow_progress
    if progress is None or state.run_state is None:
        return []
    progress["status"] = RunStatus.error.value
    for step in progress["steps"]:
        if step["status"] in ("running", "paused"):
            step["status"] = "error"
    _sync_steps_to_dojo_format(state)
    state.set_state_snapshot(state.run_state)
    return [StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copy.deepcopy(state.run_state))]


def on_workflow_progress(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events = _ensure_state_baseline(state)
    value = _event_value(chunk)
    progress = _get_workflow_progress(state)
    state.workflow_progress = progress
    steps = progress["steps"]
    name = getattr(chunk, "step_name", None)
    step_id = getattr(chunk, "step_id", None)

    if value == _WF.step_started.value:
        steps.append({"id": step_id, "name": name, "status": "running", "output": None})
        if name:
            events.append(StepStartedEvent(type=EventType.STEP_STARTED, step_name=name))

    elif value == _WF.step_completed.value:
        step = _find_open_step(steps, step_id)
        if step is not None:
            step.update(status="completed", output=_truncate_step_output(getattr(chunk, "content", None)))
        if name:
            events.append(StepFinishedEvent(type=EventType.STEP_FINISHED, step_name=name))

    elif value == _WF.step_error.value:
        step = _find_open_step(steps, step_id)
        if step is not None:
            step.update(status="error", output=_truncate_step_output(getattr(chunk, "error", None)))
        if name:
            events.append(StepFinishedEvent(type=EventType.STEP_FINISHED, step_name=name))

    elif value in _STEP_STATUS_ON_EVENT:
        step = _find_open_step(steps, step_id)
        if step is not None:
            step["status"] = _STEP_STATUS_ON_EVENT[value]

    elif value in (_WF.workflow_paused.value, _WF.router_paused.value):
        progress["status"] = RunStatus.paused.value

    elif value == _WF.workflow_cancelled.value:
        progress["status"] = RunStatus.cancelled.value
        state.cancelled = True

    # Other events (workflow_started, container events, step_output) need no special handling:
    # workflow_started initializes progress via _get_workflow_progress above; container events
    # are no-ops because their inner step_started/completed populate the flat list; step_output
    # only restates content that step_completed sets authoritatively

    _sync_steps_to_dojo_format(state)
    return events + _emit_state_delta(state)


# --- Workflow completion ---


def _is_workflow_terminal(chunk: BaseRunOutputEvent) -> bool:
    return _event_value(chunk) in _WORKFLOW_TERMINAL_VALUES


def _is_workflow_completed(chunk: BaseRunOutputEvent) -> bool:
    return _event_value(chunk) == _WF.workflow_completed.value


def _leaf_streamed(node: Any) -> Optional[bool]:
    # Descend step tree to final leaf; True if agent/team (streamed), False if function, None if uncertain
    if getattr(node, "step_type", None) in (StepType.PARALLEL, StepType.LOOP):
        return None
    sub = getattr(node, "steps", None)
    if sub:
        return _leaf_streamed(sub[-1])
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


def _workflow_completion_events(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    if _event_value(chunk) == _WF.workflow_error.value:
        error = getattr(chunk, "error", None) or "Workflow error occurred"
        return [RunErrorEvent(type=EventType.RUN_ERROR, message=str(error))]

    # Cancellation: the trailing WorkflowCompletedEvent.content is the cancel REASON, not an answer
    if state.cancelled:
        return []

    content = getattr(chunk, "content", None)
    if content is None:
        return []
    rendered = _render_content(content)
    if not rendered.strip():
        return []

    # Drop-safe bias: only suppress if final leaf is agent/team AND content already streamed
    # A rare duplicate beats a dropped answer
    if _final_leaf_streamed(chunk) and state.streamed_any_text:
        return []
    return _new_text_message(rendered)


# --- Run finalization ---


def _close_open_streams(state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []

    if state.reasoning_message_id is not None:
        events.append(
            ReasoningMessageEndEvent(type=EventType.REASONING_MESSAGE_END, message_id=state.reasoning_message_id)
        )
        events.append(ReasoningEndEvent(type=EventType.REASONING_END, message_id=state.reasoning_message_id))
        state.end_reasoning()

    for tool_call_id in list(state.active_tool_call_ids):
        if tool_call_id not in state.ended_tool_call_ids:
            events.append(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call_id))
            state.end_tool_call(tool_call_id)

    if state.text_message_open:
        events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=state.text_message_id))
        state.close_text_message()

    return events


def _paused_tools_for(chunk: BaseRunOutputEvent) -> List[ToolExecution]:
    paused_tools: List[ToolExecution] = []
    if isinstance(chunk, AgentRunPausedEvent):
        paused_tools = (
            chunk.tools_awaiting_external_execution
            + chunk.tools_requiring_confirmation
            + chunk.tools_requiring_user_input
        )
    elif isinstance(chunk, TeamRunPausedEvent):
        paused_tools = (
            chunk.tools_awaiting_external_execution
            + chunk.tools_requiring_confirmation
            + chunk.tools_requiring_user_input
        )
        for req in chunk.active_requirements:
            if req.member_agent_id and req.tool_execution:
                paused_tools.append(req.tool_execution)
    return paused_tools


def _final_snapshot(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    # Re-inject workflow_progress and steps because workflow.py strips them before DB save
    if state.run_state is None:
        return []
    authoritative_state = getattr(chunk, "session_state", None)
    final_state = authoritative_state if authoritative_state is not None else state.run_state
    if state.workflow_progress is not None:
        final_state = {**final_state, "workflow_progress": state.workflow_progress}
    if "steps" in state.run_state:
        final_state = {**final_state, "steps": state.run_state["steps"]}
    return [StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copy.deepcopy(final_state))]


def _finalize_run(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    events: List[BaseEvent] = []

    paused_tools = _paused_tools_for(chunk)
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
            state.streamed_any_text = True
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

    events += _final_snapshot(chunk, state)
    events.append(RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=state.thread_id, run_id=state.run_id))
    return events


def on_run_completed(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
    return _close_open_streams(state) + _finalize_run(chunk, state)


# --- Event dispatch ---

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

# Workflow structural events route to progress handler; custom_event excluded so
# author's own event keeps CustomEvent passthrough (same wire value "CustomEvent")
HANDLERS.update({value: on_workflow_progress for value in STRUCTURAL_EVENT_VALUES - {_WF.custom_event.value}})

# Terminal events trigger completion handling
_COMPLETION_EVENTS = (
    frozenset(
        {
            RunEvent.run_completed.value,
            RunEvent.run_paused.value,
            TeamRunEvent.run_completed.value,
            TeamRunEvent.run_paused.value,
        }
    )
    | _WORKFLOW_TERMINAL_VALUES
)


def is_completion_event(chunk: BaseRunOutputEvent) -> bool:
    event = getattr(chunk, "event", None)
    if event is None:
        return False
    event_value = event.value if hasattr(event, "value") else str(event)
    return event_value in _COMPLETION_EVENTS


def process_event(chunk: BaseRunOutputEvent, state: StreamState) -> List[BaseEvent]:
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
    # Agent/team runs
    if not _is_workflow_terminal(chunk):
        return on_run_completed(chunk, state)

    # Workflow runs: close streams first, always
    events = _close_open_streams(state)

    # Error: terminalize progress BEFORE emitting RUN_ERROR
    if not _is_workflow_completed(chunk):
        events += _workflow_error_snapshot(state)

    # Emit workflow-specific events (RUN_ERROR or final content)
    events += _workflow_completion_events(chunk, state)

    # Completed: mark progress done, then finalize (no RUN_FINISHED on error)
    if _is_workflow_completed(chunk):
        _mark_workflow_completed(state)
        events += _finalize_run(chunk, state)

    return events
