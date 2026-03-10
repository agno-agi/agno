# Streaming event dispatch table.
# Events are normalized (Team prefix stripped) for unified handling.
# Handlers update StreamState; the stream loop in router.py drives iteration.

import time
from typing import TYPE_CHECKING, Awaitable, Callable, Dict, Optional

from agno.agent import RunEvent
from agno.os.interfaces.telegram.state import TG_DRAFT_EDIT_INTERVAL, TG_STREAM_EDIT_INTERVAL, StreamState
from agno.run.workflow import WorkflowRunEvent
from agno.utils.log import log_error, log_warning

if TYPE_CHECKING:
    from agno.run.base import BaseRunOutputEvent

_DELEGATION_TOOLS = {"delegate_task_to_member", "delegate_task_to_members"}

# Inner-agent events suppressed during workflow streaming to avoid flooding
# the status blockquote. Only workflow-level progress is shown.
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

# Handlers return True on terminal events (errors, cancellations) to break the loop.
_EventHandler = Callable[["BaseRunOutputEvent", StreamState], Awaitable[bool]]


def _normalize_event(event: str) -> str:
    return event.removeprefix("Team")


def _get_tool_info(chunk: "BaseRunOutputEvent") -> tuple[str, Optional[dict]]:
    tool = getattr(chunk, "tool", None)
    name = (tool.tool_name if tool else None) or ""
    args = tool.tool_args if tool else None
    return name, args


def _delegation_label(tool_name: str, tool_args: Optional[dict], *, started: bool) -> Optional[str]:
    if tool_name not in _DELEGATION_TOOLS:
        return None
    if tool_name == "delegate_task_to_members":
        return "Delegating to all members..." if started else "Delegated to all members"
    member = (tool_args or {}).get("member_id", "member")
    return f"Delegating to {member}..." if started else f"Delegated to {member}"


async def _on_reasoning_started(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    state.add_status("Reasoning...")
    await state.flush()
    return False


async def _on_reasoning_completed(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    state.update_status("Reasoning...", "Reasoned")
    await state.flush()
    return False


async def _on_tool_call_started(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    tool_name, tool_args = _get_tool_info(chunk)
    if not tool_name:
        try:
            await state.bot.send_chat_action(state.chat_id, "typing", message_thread_id=state.message_thread_id)
        except Exception:
            pass
        return False

    label = _delegation_label(tool_name, tool_args, started=True)
    if label is None:
        agent_label = ""
        if state.is_team:
            agent_name = getattr(chunk, "agent_name", None)
            if agent_name:
                agent_label = f"[{agent_name}] "
        label = f"{agent_label}Using {tool_name}..."
    state.add_status(label)
    await state.flush()
    return False


async def _on_tool_call_completed(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    tool_name, tool_args = _get_tool_info(chunk)
    if not tool_name:
        return False

    completed = _delegation_label(tool_name, tool_args, started=False)
    if completed:
        started = _delegation_label(tool_name, tool_args, started=True)
        if started:
            state.update_status(started, completed)
    else:
        for i, line in enumerate(state.status_lines):
            if f"Using {tool_name}..." in line:
                state.status_lines[i] = line.replace(f"Using {tool_name}...", f"Used {tool_name}")
                break
    await state.flush()
    return False


async def _on_tool_call_error(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    tool_name, _ = _get_tool_info(chunk)
    tool_name = tool_name or "tool"
    found = False
    for i, line in enumerate(state.status_lines):
        if f"Using {tool_name}..." in line:
            state.status_lines[i] = line.replace(f"Using {tool_name}...", f"{tool_name} failed")
            found = True
            break
    if not found:
        state.add_status(f"{tool_name} failed")
    await state.flush()
    return False


async def _on_run_content(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    content = getattr(chunk, "content", None)
    if content is not None:
        state.accumulated_content += str(content)
        now = time.monotonic()
        interval = TG_DRAFT_EDIT_INTERVAL if state.use_draft else TG_STREAM_EDIT_INTERVAL
        if now - state.last_edit_time >= interval:
            try:
                await state.send_or_edit(state.build_display_html())
            except Exception as e:
                log_warning(f"Stream edit failed (will retry on next chunk): {e}")
    return False


async def _on_run_intermediate_content(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    # Teams emit intermediate content from each member as they finish. The team
    # leader emits a single consolidated RunContent at the end — that's what we
    # show. For non-team entities, accumulate normally.
    if not state.is_team:
        content = getattr(chunk, "content", None)
        if content is not None:
            state.accumulated_content += str(content)
    return False


async def _on_run_completed(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    content = getattr(chunk, "content", None)
    if content:
        state.accumulated_content = str(content)
    return False


async def _on_run_error(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    error_content = getattr(chunk, "content", None) or "Unknown error"
    log_error(f"Run error during stream: {error_content}")
    state.accumulated_content = state.error_message
    state.terminal = True
    return True


async def _on_memory_update_started(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    state.add_status("Updating memory...")
    await state.flush()
    return False


async def _on_memory_update_completed(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    state.update_status("Updating memory...", "Memory updated")
    await state.flush()
    return False


async def _on_workflow_started(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    wf_name = getattr(chunk, "workflow_name", None) or "Workflow"
    state.add_status(f"Running workflow: {wf_name}...")
    await state.flush()
    return False


async def _on_workflow_completed(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    state.update_status("Running workflow:", "Workflow completed")
    content = getattr(chunk, "content", None)
    if content:
        state.accumulated_content = str(content)
    elif state.workflow_final_content:
        state.accumulated_content = state.workflow_final_content
    return False


async def _on_workflow_error(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    state.update_status("Running workflow:", "Workflow failed")
    state.accumulated_content = state.error_message or "Error: workflow failed"
    state.terminal = True
    return True


async def _on_step_started(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    step_name = getattr(chunk, "step_name", None) or "unknown"
    state.add_status(f"Running step: {step_name}...")
    await state.flush()
    return False


async def _on_step_completed(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    step_name = getattr(chunk, "step_name", None) or "unknown"
    state.update_status(f"Running step: {step_name}...", f"Completed step: {step_name}")
    content = getattr(chunk, "content", None)
    if content:
        state.accumulated_content = str(content)
    await state.flush()
    return False


async def _on_step_error(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    step_name = getattr(chunk, "step_name", None) or "unknown"
    state.update_status(f"Running step: {step_name}...", f"Step failed: {step_name}")
    await state.flush()
    return False


async def _on_step_output(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    content = getattr(chunk, "content", None)
    if content is not None:
        state.workflow_final_content = str(content)
    return False


async def _on_workflow_agent_started(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    agent_name = getattr(chunk, "agent_name", None) or "agent"
    state.add_status(f"Running agent: {agent_name}...")
    await state.flush()
    return False


async def _on_workflow_agent_completed(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    agent_name = getattr(chunk, "agent_name", None) or "agent"
    state.update_status(f"Running agent: {agent_name}...", f"Completed agent: {agent_name}")
    await state.flush()
    return False


async def _on_loop_execution_started(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    step_name = getattr(chunk, "step_name", None) or "loop"
    max_iter = getattr(chunk, "max_iterations", None)
    label = f"Loop: {step_name}" + (f" (max {max_iter})" if max_iter else "")
    state.add_status(f"{label}...")
    await state.flush()
    return False


async def _on_loop_iteration_started(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    step_name = getattr(chunk, "step_name", None) or "loop"
    iteration = getattr(chunk, "iteration", 0)
    max_iter = getattr(chunk, "max_iterations", None)
    label = f"{step_name}: iteration {iteration}" + (f"/{max_iter}" if max_iter else "")
    state.add_status(f"{label}...")
    await state.flush()
    return False


async def _on_loop_iteration_completed(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    step_name = getattr(chunk, "step_name", None) or "loop"
    iteration = getattr(chunk, "iteration", 0)
    state.update_status(f"{step_name}: iteration {iteration}...", f"{step_name}: iteration {iteration} done")
    await state.flush()
    return False


async def _on_loop_execution_completed(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    step_name = getattr(chunk, "step_name", None) or "loop"
    state.update_status(f"Loop: {step_name}", f"Loop: {step_name} completed")
    await state.flush()
    return False


# Factory for simple paired workflow events (started/completed)
def _make_wf_handler(label: str, *, started: bool) -> _EventHandler:
    async def handler(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
        if started:
            state.add_status(f"{label}...")
        else:
            state.update_status(f"{label}...", f"{label} completed")
        await state.flush()
        return False

    return handler


# Normalized keys (no "Team" prefix) — one table handles both agent and team events
HANDLERS: Dict[str, _EventHandler] = {
    RunEvent.reasoning_started.value: _on_reasoning_started,
    RunEvent.reasoning_completed.value: _on_reasoning_completed,
    RunEvent.tool_call_started.value: _on_tool_call_started,
    RunEvent.tool_call_completed.value: _on_tool_call_completed,
    RunEvent.tool_call_error.value: _on_tool_call_error,
    RunEvent.run_content.value: _on_run_content,
    RunEvent.run_intermediate_content.value: _on_run_intermediate_content,
    RunEvent.run_completed.value: _on_run_completed,
    RunEvent.run_error.value: _on_run_error,
    RunEvent.run_cancelled.value: _on_run_error,  # Treat cancellation as terminal error
    RunEvent.memory_update_started.value: _on_memory_update_started,
    RunEvent.memory_update_completed.value: _on_memory_update_completed,
    WorkflowRunEvent.workflow_started.value: _on_workflow_started,
    WorkflowRunEvent.workflow_completed.value: _on_workflow_completed,
    WorkflowRunEvent.workflow_error.value: _on_workflow_error,
    WorkflowRunEvent.workflow_cancelled.value: _on_workflow_error,
    WorkflowRunEvent.step_started.value: _on_step_started,
    WorkflowRunEvent.step_completed.value: _on_step_completed,
    WorkflowRunEvent.step_error.value: _on_step_error,
    WorkflowRunEvent.step_output.value: _on_step_output,
    WorkflowRunEvent.workflow_agent_started.value: _on_workflow_agent_started,
    WorkflowRunEvent.workflow_agent_completed.value: _on_workflow_agent_completed,
    WorkflowRunEvent.loop_execution_started.value: _on_loop_execution_started,
    WorkflowRunEvent.loop_iteration_started.value: _on_loop_iteration_started,
    WorkflowRunEvent.loop_iteration_completed.value: _on_loop_iteration_completed,
    WorkflowRunEvent.loop_execution_completed.value: _on_loop_execution_completed,
    WorkflowRunEvent.parallel_execution_started.value: _make_wf_handler("Parallel execution", started=True),
    WorkflowRunEvent.parallel_execution_completed.value: _make_wf_handler("Parallel execution", started=False),
    WorkflowRunEvent.condition_execution_started.value: _make_wf_handler("Evaluating condition", started=True),
    WorkflowRunEvent.condition_execution_completed.value: _make_wf_handler("Evaluating condition", started=False),
    WorkflowRunEvent.router_execution_started.value: _make_wf_handler("Routing", started=True),
    WorkflowRunEvent.router_execution_completed.value: _make_wf_handler("Routing", started=False),
    WorkflowRunEvent.steps_execution_started.value: _make_wf_handler("Running steps", started=True),
    WorkflowRunEvent.steps_execution_completed.value: _make_wf_handler("Running steps", started=False),
}


async def process_event(ev_raw: str, chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    ev = _normalize_event(ev_raw)

    # Suppress nested agent internals in workflow mode
    if state.is_workflow and ev in _SUPPRESSED_IN_WORKFLOW:
        return False

    handler = HANDLERS.get(ev)
    if handler:
        return await handler(chunk, state)

    return False
