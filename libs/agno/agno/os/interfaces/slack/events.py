from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Dict

from agno.os.interfaces.slack.helpers import member_name, task_id
from agno.os.interfaces.slack.state import StreamState

if TYPE_CHECKING:
    from slack_sdk.web.async_chat_stream import AsyncChatStream

    from agno.run.base import BaseRunOutputEvent


def _normalize_event(event: str) -> str:
    # Strip "Team" prefix so agent events ("ToolCallStarted") and team events
    # ("TeamToolCallStarted") are handled by the same branches.
    return event[4:] if event.startswith("Team") else event


@dataclass(frozen=True)
class _ToolRef:
    tid: str | None
    label: str
    errored: bool


def _extract_tool_ref(chunk: BaseRunOutputEvent, state: StreamState, *, fallback_id: str | None = None) -> _ToolRef:
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
    task_id: str,
    title: str,
    status: str,
    *,
    output: str | None = None,
) -> None:
    chunk: dict = {"type": "task_update", "id": task_id, "title": title, "status": status}
    if output:
        chunk["output"] = output[:200]  # Slack truncates longer task output
    await stream.append(chunks=[chunk])


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


# Workflows orchestrate multiple agents via steps/loops/conditions. Without
# suppression, each inner agent's tool calls and reasoning events would flood
# the Slack stream with low-level noise. We only show step-level progress.
# Values are NORMALIZED (no "Team" prefix) so one set covers agent + team events.
_SUPPRESSED_IN_WORKFLOW: frozenset[str] = frozenset(
    {
        "ReasoningStarted",
        "ReasoningCompleted",
        "ToolCallStarted",
        "ToolCallCompleted",
        "ToolCallError",
        "MemoryUpdateStarted",
        "MemoryUpdateCompleted",
        "RunContent",
        "RunIntermediateContent",
        "RunCompleted",
        "RunError",
        "RunCancelled",
    }
)


# ---------------------------------------------------------------------------
# Event handlers — each returns True on terminal events to break the loop.
# ---------------------------------------------------------------------------

_EventHandler = Callable[
    ["BaseRunOutputEvent", StreamState, "AsyncChatStream"],
    Awaitable[bool],
]


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
    ref = _extract_tool_ref(chunk, state, fallback_id=str(len(state.task_cards)))
    if ref.tid:
        state.track_task(ref.tid, ref.label)
        await _emit_task(stream, ref.tid, ref.label, "in_progress")
    return False


async def _on_tool_call_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    ref = _extract_tool_ref(chunk, state)
    if ref.tid:
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
        if ref.tid in state.task_cards:
            state.error_task(ref.tid)
        else:
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


async def _on_step_output(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    content = getattr(chunk, "content", None)
    if content is not None:
        if state.entity_type == "workflow":
            # Workflow steps may produce intermediate output before the final
            # WorkflowCompleted event. We capture (not stream) it here so the
            # completed handler can use it as a fallback if chunk.content is None.
            state.workflow_final_content = str(content)
        else:
            state.append_content(content)
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


async def _on_step_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    await _wf_task(chunk, state, stream, "step", started=True)
    return False


async def _on_step_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    await _wf_task(chunk, state, stream, "step", started=False)
    return False


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


async def _on_parallel_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    await _wf_task(chunk, state, stream, "parallel", "Parallel", started=True)
    return False


async def _on_parallel_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    await _wf_task(chunk, state, stream, "parallel", "Parallel", started=False)
    return False


async def _on_condition_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    await _wf_task(chunk, state, stream, "cond", "Condition", started=True)
    return False


async def _on_condition_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    await _wf_task(chunk, state, stream, "cond", "Condition", started=False)
    return False


async def _on_router_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    await _wf_task(chunk, state, stream, "router", "Router", started=True)
    return False


async def _on_router_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    await _wf_task(chunk, state, stream, "router", "Router", started=False)
    return False


async def _on_wf_agent_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    await _wf_task(chunk, state, stream, "agent", "Running", started=True, name_attr="agent_name")
    return False


async def _on_wf_agent_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    await _wf_task(chunk, state, stream, "agent", "Running", started=False, name_attr="agent_name")
    return False


async def _on_steps_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    await _wf_task(chunk, state, stream, "steps", "Steps", started=True)
    return False


async def _on_steps_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    await _wf_task(chunk, state, stream, "steps", "Steps", started=False)
    return False


# Dispatch table for normalized agent/team events.
DISPATCH: Dict[str, _EventHandler] = {
    "ReasoningStarted": _on_reasoning_started,
    "ReasoningCompleted": _on_reasoning_completed,
    "ToolCallStarted": _on_tool_call_started,
    "ToolCallCompleted": _on_tool_call_completed,
    "ToolCallError": _on_tool_call_error,
    "RunContent": _on_run_content,
    "RunIntermediateContent": _on_run_intermediate_content,
    "MemoryUpdateStarted": _on_memory_update_started,
    "MemoryUpdateCompleted": _on_memory_update_completed,
    "RunCompleted": _on_run_completed,
    "RunError": _on_run_error,
    "RunCancelled": _on_run_error,
}

# Dispatch table for raw workflow events (looked up before normalization).
WORKFLOW_DISPATCH: Dict[str, _EventHandler] = {
    "StepOutput": _on_step_output,
    "WorkflowStarted": _on_workflow_started,
    "WorkflowCompleted": _on_workflow_completed,
    "WorkflowError": _on_workflow_error,
    "WorkflowCancelled": _on_workflow_error,
    "StepStarted": _on_step_started,
    "StepCompleted": _on_step_completed,
    "StepError": _on_step_error,
    "LoopExecutionStarted": _on_loop_execution_started,
    "LoopIterationStarted": _on_loop_iteration_started,
    "LoopIterationCompleted": _on_loop_iteration_completed,
    "LoopExecutionCompleted": _on_loop_execution_completed,
    "ParallelExecutionStarted": _on_parallel_started,
    "ParallelExecutionCompleted": _on_parallel_completed,
    "ConditionExecutionStarted": _on_condition_started,
    "ConditionExecutionCompleted": _on_condition_completed,
    "RouterExecutionStarted": _on_router_started,
    "RouterExecutionCompleted": _on_router_completed,
    "WorkflowAgentStarted": _on_wf_agent_started,
    "WorkflowAgentCompleted": _on_wf_agent_completed,
    "StepsExecutionStarted": _on_steps_started,
    "StepsExecutionCompleted": _on_steps_completed,
}


async def process_event(ev_raw: str, chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    # Returns True on terminal events (error/cancel) to break the stream loop.

    # 1) Try raw workflow-specific events first (they use un-normalized names).
    handler = WORKFLOW_DISPATCH.get(ev_raw)
    if handler:
        return await handler(chunk, state, stream)

    # 2) Normalize (strip "Team" prefix) then check agent/team dispatch table.
    ev = _normalize_event(ev_raw)

    # Workflow mode: suppress nested agent internals
    if state.entity_type == "workflow" and ev in _SUPPRESSED_IN_WORKFLOW:
        return False

    handler = DISPATCH.get(ev)
    if handler:
        return await handler(chunk, state, stream)

    return False
