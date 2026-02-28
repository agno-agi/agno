"""
Slack Streaming Event Handlers
==============================

Processes streaming events from agents, teams, and workflows,
translating them into Slack task cards and buffered content.

Key concepts:
- Events are normalized (Team prefix stripped) for unified handling
- Workflow mode suppresses inner agent events to reduce noise
- Task cards track progress; content is buffered for streaming
- Factory pattern generates simple paired handlers (Started/Completed)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Dict

from agno.agent import RunEvent
from agno.os.interfaces.slack.helpers import member_name, task_id
from agno.os.interfaces.slack.state import StreamState
from agno.run.workflow import WorkflowRunEvent

if TYPE_CHECKING:
    from slack_sdk.web.async_chat_stream import AsyncChatStream

    from agno.run.base import BaseRunOutputEvent


# =============================================================================
# Type Aliases
# =============================================================================

# Event handlers return True on terminal events to break the stream loop
_EventHandler = Callable[
    ["BaseRunOutputEvent", StreamState, "AsyncChatStream"],
    Awaitable[bool],
]


# =============================================================================
# Helper Functions
# =============================================================================


def _normalize_event(event: str) -> str:
    """Strip 'Team' prefix so agent and team events use the same handlers."""
    return event.removeprefix("Team")


@dataclass
class _ToolRef:
    """Reference to a tool call for task card tracking."""

    tid: str | None  # Slack task card ID (None when tool_call_id is missing)
    label: str  # Display title, e.g. "Researcher: web_search"
    errored: bool


def _extract_tool_ref(chunk: BaseRunOutputEvent, state: StreamState, *, fallback_id: str | None = None) -> _ToolRef:
    """Build unique (tid, label) for each tool call's Slack task card."""
    tool = getattr(chunk, "tool", None)
    tool_name = (tool.tool_name if tool else None) or "tool"
    call_id = (tool.tool_call_id if tool else None) or fallback_id
    member = member_name(chunk, state.entity_name)
    label = f"{member}: {tool_name}" if member else tool_name
    tid = task_id(member, call_id) if call_id else None  # type: ignore[arg-type]
    errored = bool(tool.tool_call_error) if tool else False
    return _ToolRef(tid=tid, label=label, errored=errored)


async def _emit_task(
    stream: AsyncChatStream,
    card_id: str,
    title: str,
    status: str,
    *,
    output: str | None = None,
) -> None:
    """Send a task card update to the Slack stream."""
    chunk: dict = {"type": "task_update", "id": card_id, "title": title, "status": status}
    if output:
        chunk["output"] = output[:200]  # Slack truncates longer task output
    await stream.append(markdown_text="", chunks=[chunk])


async def _wf_task(
    chunk: BaseRunOutputEvent,
    state: StreamState,
    stream: AsyncChatStream,
    prefix: str,
    label: str = "",
    *,
    started: bool,
    name_attr: str = "step_name",
) -> None:
    """Emit a workflow task card for paired events (Started/Completed)."""
    name = getattr(chunk, name_attr, None) or prefix
    sid = getattr(chunk, "step_id", None) or name
    key = f"wf_{prefix}_{sid}"
    title = f"{label}: {name}" if label else name
    if started:
        state.track_task(key, title)
        await _emit_task(stream, key, title, "in_progress")
    else:
        state.complete_task(key)
        await _emit_task(stream, key, title, "complete")


# =============================================================================
# Suppression Set
# =============================================================================

# Workflows orchestrate multiple agents via steps/loops/conditions. Without
# suppression, each inner agent's tool calls and reasoning events would flood
# the Slack stream with low-level noise. We only show step-level progress.
# Values are NORMALIZED (no "Team" prefix) so one set covers agent + team events.
_SUPPRESSED_IN_WORKFLOW: frozenset[str] = frozenset(
    {
        RunEvent.reasoning_started.value,
        RunEvent.reasoning_completed.value,
        RunEvent.tool_call_started.value,
        RunEvent.tool_call_completed.value,
        RunEvent.tool_call_error.value,
        RunEvent.memory_update_started.value,
        RunEvent.memory_update_completed.value,
        RunEvent.run_content.value,
        RunEvent.run_intermediate_content.value,
        RunEvent.run_completed.value,
        RunEvent.run_error.value,
        RunEvent.run_cancelled.value,
    }
)


# =============================================================================
# Handler Factory
# =============================================================================


def _make_wf_handler(
    prefix: str,
    label: str,
    *,
    started: bool,
    name_attr: str = "step_name",
) -> _EventHandler:
    """
    Factory to create workflow event handlers for simple paired events.

    This eliminates boilerplate for events that just call _wf_task with
    different parameters (e.g., ParallelStarted, ConditionCompleted, etc.).
    """

    async def handler(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
        await _wf_task(chunk, state, stream, prefix, label, started=started, name_attr=name_attr)
        return False

    return handler


# =============================================================================
# Agent/Team Event Handlers (require custom logic)
# =============================================================================


async def _on_reasoning_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    key = f"reasoning_{state.reasoning_round}"
    state.track_task(key, "Reasoning")
    await _emit_task(stream, key, "Reasoning", "in_progress")
    return False


async def _on_reasoning_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    key = f"reasoning_{state.reasoning_round}"
    state.complete_task(key)
    state.reasoning_round += 1
    await _emit_task(stream, key, "Reasoning", "complete")
    return False


async def _on_tool_call_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    # Fallback when SDK chunks omit tool_call_id so cards still render
    ref = _extract_tool_ref(chunk, state, fallback_id=str(len(state.task_cards)))
    if ref.tid:
        state.track_task(ref.tid, ref.label)
        await _emit_task(stream, ref.tid, ref.label, "in_progress")
    return False


async def _on_tool_call_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    ref = _extract_tool_ref(chunk, state)
    if ref.tid:
        # Backfill card when Completed arrives without a prior Started event
        if ref.tid not in state.task_cards:
            state.track_task(ref.tid, ref.label)
        if ref.errored:
            state.error_task(ref.tid)
        else:
            state.complete_task(ref.tid)
        await _emit_task(stream, ref.tid, ref.label, "error" if ref.errored else "complete")
    return False


async def _on_tool_call_error(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    ref = _extract_tool_ref(chunk, state, fallback_id=f"tool_error_{state.error_count}")
    error_msg = getattr(chunk, "error", None) or "Tool call failed"
    state.error_count += 1
    if ref.tid:
        if ref.tid not in state.task_cards:
            state.track_task(ref.tid, ref.label)
        state.error_task(ref.tid)
        await _emit_task(stream, ref.tid, ref.label, "error", output=str(error_msg))
    return False


async def _on_run_content(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    content = getattr(chunk, "content", None)
    if content is not None:
        state.append_content(content)
    return False


async def _on_run_intermediate_content(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    # Teams emit intermediate content from each member as they finish. Showing
    # these would interleave partial outputs in the stream. The team leader
    # emits a single consolidated RunContent at the end — that's what we show.
    if state.entity_type != "team":
        content = getattr(chunk, "content", None)
        if content is not None:
            state.append_content(content)
    return False


async def _on_memory_update_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    state.track_task("memory_update", "Updating memory")
    await _emit_task(stream, "memory_update", "Updating memory", "in_progress")
    return False


async def _on_memory_update_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    state.complete_task("memory_update")
    await _emit_task(stream, "memory_update", "Updating memory", "complete")
    return False


async def _on_run_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    return False  # Finalization handled by caller after stream ends


async def _on_run_error(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    state.error_count += 1
    error_msg = getattr(chunk, "content", None) or "An error occurred"
    state.append_error(error_msg)
    state.terminal_status = "error"
    return True


# =============================================================================
# Workflow Event Handlers (require custom logic)
# =============================================================================


async def _on_step_output(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    # StepOutput is workflow-only (agents/teams never emit it).
    # Capture but don't stream — WorkflowCompleted uses this as fallback.
    content = getattr(chunk, "content", None)
    if content is not None:
        state.workflow_final_content = str(content)
    return False


async def _on_workflow_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    wf_name = getattr(chunk, "workflow_name", None) or state.entity_name or "Workflow"
    run_id = getattr(chunk, "run_id", None) or "run"
    key = f"wf_run_{run_id}"
    state.track_task(key, f"Workflow: {wf_name}")
    await _emit_task(stream, key, f"Workflow: {wf_name}", "in_progress")
    return False


async def _on_workflow_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    run_id = getattr(chunk, "run_id", None) or "run"
    wf_name = getattr(chunk, "workflow_name", None) or state.entity_name or "Workflow"
    key = f"wf_run_{run_id}"
    state.complete_task(key)
    await _emit_task(stream, key, f"Workflow: {wf_name}", "complete")
    final = getattr(chunk, "content", None)
    if final is None:
        final = state.workflow_final_content
    if final:
        state.append_content(final)
    return False


async def _on_workflow_error(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    state.error_count += 1
    error_msg = getattr(chunk, "error", None) or getattr(chunk, "content", None) or "Workflow failed"
    state.append_error(error_msg)
    state.terminal_status = "error"
    return True


async def _on_step_error(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    step_name = getattr(chunk, "step_name", None) or "step"
    sid = getattr(chunk, "step_id", None) or step_name
    key = f"wf_step_{sid}"
    error_msg = getattr(chunk, "error", None) or "Step failed"
    if key not in state.task_cards:
        state.track_task(key, step_name)
    state.error_task(key)
    await _emit_task(stream, key, step_name, "error", output=str(error_msg))
    return False


# =============================================================================
# Loop Event Handlers (custom logic for iteration tracking)
# =============================================================================


async def _on_loop_execution_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    step_name = getattr(chunk, "step_name", None) or "loop"
    loop_key = getattr(chunk, "step_id", None) or step_name
    max_iter = getattr(chunk, "max_iterations", None)
    title = f"Loop: {step_name}" + (f" (max {max_iter})" if max_iter else "")
    key = f"wf_loop_{loop_key}"
    state.track_task(key, title)
    await _emit_task(stream, key, title, "in_progress")
    return False


async def _on_loop_iteration_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    loop_key = getattr(chunk, "step_id", None) or getattr(chunk, "step_name", None) or "loop"
    iteration = getattr(chunk, "iteration", 0)
    max_iter = getattr(chunk, "max_iterations", None)
    title = f"Iteration {iteration}" + (f"/{max_iter}" if max_iter else "")
    key = f"wf_loop_{loop_key}_iter_{iteration}"
    state.track_task(key, title)
    await _emit_task(stream, key, title, "in_progress")
    return False


async def _on_loop_iteration_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    loop_key = getattr(chunk, "step_id", None) or getattr(chunk, "step_name", None) or "loop"
    iteration = getattr(chunk, "iteration", 0)
    key = f"wf_loop_{loop_key}_iter_{iteration}"
    state.complete_task(key)
    await _emit_task(stream, key, f"Iteration {iteration}", "complete")
    return False


async def _on_loop_execution_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    step_name = getattr(chunk, "step_name", None) or "loop"
    loop_key = getattr(chunk, "step_id", None) or step_name
    key = f"wf_loop_{loop_key}"
    state.complete_task(key)
    await _emit_task(stream, key, f"Loop: {step_name}", "complete")
    return False


# =============================================================================
# Dispatch Table
# =============================================================================

# Single dispatch table — keys are normalized (no "Team" prefix).
# Workflow event names never start with "Team" so normalization is a no-op for them.
HANDLERS: Dict[str, _EventHandler] = {
    # -------------------------------------------------------------------------
    # Agent/Team Events (normalized - use RunEvent values)
    # -------------------------------------------------------------------------
    RunEvent.reasoning_started.value: _on_reasoning_started,
    RunEvent.reasoning_completed.value: _on_reasoning_completed,
    RunEvent.tool_call_started.value: _on_tool_call_started,
    RunEvent.tool_call_completed.value: _on_tool_call_completed,
    RunEvent.tool_call_error.value: _on_tool_call_error,
    RunEvent.run_content.value: _on_run_content,
    RunEvent.run_intermediate_content.value: _on_run_intermediate_content,
    RunEvent.memory_update_started.value: _on_memory_update_started,
    RunEvent.memory_update_completed.value: _on_memory_update_completed,
    RunEvent.run_completed.value: _on_run_completed,
    RunEvent.run_error.value: _on_run_error,
    RunEvent.run_cancelled.value: _on_run_error,  # Treat cancellation as terminal error
    # -------------------------------------------------------------------------
    # Workflow Lifecycle Events
    # -------------------------------------------------------------------------
    WorkflowRunEvent.step_output.value: _on_step_output,
    WorkflowRunEvent.workflow_started.value: _on_workflow_started,
    WorkflowRunEvent.workflow_completed.value: _on_workflow_completed,
    WorkflowRunEvent.workflow_error.value: _on_workflow_error,
    WorkflowRunEvent.workflow_cancelled.value: _on_workflow_error,
    # -------------------------------------------------------------------------
    # Workflow Step Events
    # -------------------------------------------------------------------------
    WorkflowRunEvent.step_started.value: _make_wf_handler("step", "", started=True),
    WorkflowRunEvent.step_completed.value: _make_wf_handler("step", "", started=False),
    WorkflowRunEvent.step_error.value: _on_step_error,
    # -------------------------------------------------------------------------
    # Workflow Loop Events
    # -------------------------------------------------------------------------
    WorkflowRunEvent.loop_execution_started.value: _on_loop_execution_started,
    WorkflowRunEvent.loop_iteration_started.value: _on_loop_iteration_started,
    WorkflowRunEvent.loop_iteration_completed.value: _on_loop_iteration_completed,
    WorkflowRunEvent.loop_execution_completed.value: _on_loop_execution_completed,
    # -------------------------------------------------------------------------
    # Workflow Structural Events (factory-generated)
    # -------------------------------------------------------------------------
    WorkflowRunEvent.parallel_execution_started.value: _make_wf_handler("parallel", "Parallel", started=True),
    WorkflowRunEvent.parallel_execution_completed.value: _make_wf_handler("parallel", "Parallel", started=False),
    WorkflowRunEvent.condition_execution_started.value: _make_wf_handler("cond", "Condition", started=True),
    WorkflowRunEvent.condition_execution_completed.value: _make_wf_handler("cond", "Condition", started=False),
    WorkflowRunEvent.router_execution_started.value: _make_wf_handler("router", "Router", started=True),
    WorkflowRunEvent.router_execution_completed.value: _make_wf_handler("router", "Router", started=False),
    WorkflowRunEvent.workflow_agent_started.value: _make_wf_handler(
        "agent", "Running", started=True, name_attr="agent_name"
    ),
    WorkflowRunEvent.workflow_agent_completed.value: _make_wf_handler(
        "agent", "Running", started=False, name_attr="agent_name"
    ),
    WorkflowRunEvent.steps_execution_started.value: _make_wf_handler("steps", "Steps", started=True),
    WorkflowRunEvent.steps_execution_completed.value: _make_wf_handler("steps", "Steps", started=False),
}


async def process_event(ev_raw: str, chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    """
    Process a streaming event and update Slack accordingly.

    Args:
        ev_raw: Raw event name (e.g., "ToolCallStarted", "TeamRunContent")
        chunk: Stream chunk containing event data
        state: StreamState tracking session state
        stream: Slack chat_stream for sending updates

    Returns:
        True if this is a terminal event and the stream loop should break.
    """
    ev = _normalize_event(ev_raw)

    # Suppress nested agent internals in workflow mode
    if state.entity_type == "workflow" and ev in _SUPPRESSED_IN_WORKFLOW:
        return False

    handler = HANDLERS.get(ev)
    if handler:
        return await handler(chunk, state, stream)

    return False
