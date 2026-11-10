import time
from typing import TYPE_CHECKING, Awaitable, Callable, Dict

from agno.agent import RunEvent
from agno.os.interfaces.telegram.state import TG_STREAM_EDIT_INTERVAL, StreamState
from agno.run.workflow import WorkflowRunEvent
from agno.utils.log import log_error, log_warning

if TYPE_CHECKING:
    from agno.run.base import BaseRunOutputEvent

# Suppress inner-agent events in workflow mode — only workflow-level
# lifecycle events (step/loop/parallel/etc.) are shown
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

_EventHandler = Callable[["BaseRunOutputEvent", StreamState], Awaitable[bool]]


def _strip_team_prefix(event: str) -> str:
    return event.removeprefix("Team")


def _get_tool_name(chunk: "BaseRunOutputEvent") -> str:
    tool = getattr(chunk, "tool", None)
    return (tool.tool_name if tool else None) or ""


def _team_prefix(chunk: "BaseRunOutputEvent", state: StreamState) -> str:
    if state.entity_type != "team":
        return ""
    name = getattr(chunk, "agent_name", None)
    return f"{name}: " if name else ""


def _status_handler(
    label: str = "",
    *,
    started: bool,
    name_attr: str = "",
    indent: bool = False,
) -> _EventHandler:
    async def handler(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
        name = getattr(chunk, name_attr, None) if name_attr else None
        if name and label:
            resolved = f"{label}: {name}"
        elif name:
            resolved = str(name)
        else:
            resolved = label
        if indent:
            resolved = f"\u2003{resolved}"
        if started:
            state.add_status(f"{resolved}...")
        else:
            state.replace_status(f"{resolved}...", resolved)
        await state.update_display()
        return False

    return handler


async def _on_tool_call_started(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    tool_name = _get_tool_name(chunk)
    if not tool_name:
        try:
            await state.bot.send_chat_action(state.chat_id, "typing", message_thread_id=state.message_thread_id)
        except Exception:
            pass
        return False

    label = f"{_team_prefix(chunk, state)}{tool_name}"
    state.add_status(f"{label}...")
    await state.update_display()
    return False


async def _on_tool_call_completed(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    tool_name = _get_tool_name(chunk)
    if not tool_name:
        return False
    label = f"{_team_prefix(chunk, state)}{tool_name}"
    state.replace_status(f"{label}...", label)
    await state.update_display()
    return False


async def _on_tool_call_error(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    tool_name = _get_tool_name(chunk) or "tool"
    label = f"{_team_prefix(chunk, state)}{tool_name}"
    if not state.replace_status(f"{label}...", f"{label} failed"):
        state.add_status(f"{label} failed")
    await state.update_display()
    return False


async def _on_run_content(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    content = getattr(chunk, "content", None)
    if content is not None:
        state.accumulated_content += str(content)
        now = time.monotonic()
        interval = TG_STREAM_EDIT_INTERVAL
        if now - state.last_edit_time >= interval:
            try:
                await state.send_or_edit(state.build_display_html())
            except Exception as e:
                log_warning(f"Stream edit failed (will retry on next chunk): {str(e)}")
    return False


async def _on_run_intermediate_content(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    # Teams aggregate content at run_completed; only accumulate for single agents
    if state.entity_type != "team":
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
    return True


async def _on_workflow_started(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    wf_name = getattr(chunk, "workflow_name", None) or "Workflow"
    state.add_status(f"Workflow: {wf_name}...")
    await state.update_display()
    return False


async def _on_workflow_completed(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    content = getattr(chunk, "content", None)
    if content:
        state.accumulated_content = str(content)
    elif state.workflow_final_content:
        state.accumulated_content = state.workflow_final_content
    return False


async def _on_workflow_error(_chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    # Mark the workflow line as failed while preserving the workflow name
    for i, line in enumerate(state.status_lines):
        if line.startswith("Workflow:"):
            state.status_lines[i] = line.removesuffix("...") + " (failed)"
            break
    state.accumulated_content = state.error_message or "Error: workflow failed"
    return True


async def _on_step_error(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    name = getattr(chunk, "step_name", None) or "step"
    if not state.replace_status(f"{name}...", f"{name} failed"):
        state.add_status(f"{name} failed")
    await state.update_display()
    return False


async def _on_step_output(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    # Captured here as fallback; workflow_completed may not include final content
    content = getattr(chunk, "content", None)
    if content is not None:
        state.workflow_final_content = str(content)
    return False


async def _on_loop_execution_started(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    name = getattr(chunk, "step_name", None) or "loop"
    max_iter = getattr(chunk, "max_iterations", None)
    label = f"Loop: {name}" + (f" (max {max_iter})" if max_iter else "")
    state.add_status(f"{label}...")
    await state.update_display()
    return False


async def _on_loop_iteration_started(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    iteration = getattr(chunk, "iteration", 0)
    max_iter = getattr(chunk, "max_iterations", None)
    label = f"Iteration {iteration}" + (f"/{max_iter}" if max_iter else "")
    state.add_status(f"{label}...")
    await state.update_display()
    return False


async def _on_loop_iteration_completed(chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    iteration = getattr(chunk, "iteration", 0)
    state.replace_status(f"Iteration {iteration}...", f"Iteration {iteration}")
    await state.update_display()
    return False


HANDLERS: Dict[str, _EventHandler] = {
    RunEvent.reasoning_started.value: _status_handler("Reasoning", started=True),
    RunEvent.reasoning_completed.value: _status_handler("Reasoning", started=False),
    RunEvent.tool_call_started.value: _on_tool_call_started,
    RunEvent.tool_call_completed.value: _on_tool_call_completed,
    RunEvent.tool_call_error.value: _on_tool_call_error,
    RunEvent.run_content.value: _on_run_content,
    RunEvent.run_intermediate_content.value: _on_run_intermediate_content,
    RunEvent.run_completed.value: _on_run_completed,
    RunEvent.run_error.value: _on_run_error,
    RunEvent.run_cancelled.value: _on_run_error,
    RunEvent.memory_update_started.value: _status_handler("Updating memory", started=True),
    RunEvent.memory_update_completed.value: _status_handler("Updating memory", started=False),
    WorkflowRunEvent.workflow_started.value: _on_workflow_started,
    WorkflowRunEvent.workflow_completed.value: _on_workflow_completed,
    WorkflowRunEvent.workflow_error.value: _on_workflow_error,
    WorkflowRunEvent.workflow_cancelled.value: _on_workflow_error,
    WorkflowRunEvent.step_started.value: _status_handler(started=True, name_attr="step_name", indent=True),
    WorkflowRunEvent.step_completed.value: _status_handler(started=False, name_attr="step_name", indent=True),
    WorkflowRunEvent.step_error.value: _on_step_error,
    WorkflowRunEvent.step_output.value: _on_step_output,
    WorkflowRunEvent.workflow_agent_started.value: _status_handler("Running", started=True, name_attr="agent_name"),
    WorkflowRunEvent.workflow_agent_completed.value: _status_handler("Running", started=False, name_attr="agent_name"),
    WorkflowRunEvent.loop_execution_started.value: _on_loop_execution_started,
    WorkflowRunEvent.loop_iteration_started.value: _on_loop_iteration_started,
    WorkflowRunEvent.loop_iteration_completed.value: _on_loop_iteration_completed,
    WorkflowRunEvent.loop_execution_completed.value: _status_handler("Loop", started=False, name_attr="step_name"),
    WorkflowRunEvent.parallel_execution_started.value: _status_handler("Parallel", started=True, name_attr="step_name"),
    WorkflowRunEvent.parallel_execution_completed.value: _status_handler(
        "Parallel", started=False, name_attr="step_name"
    ),
    WorkflowRunEvent.condition_execution_started.value: _status_handler(
        "Condition", started=True, name_attr="step_name"
    ),
    WorkflowRunEvent.condition_execution_completed.value: _status_handler(
        "Condition", started=False, name_attr="step_name"
    ),
    WorkflowRunEvent.router_execution_started.value: _status_handler("Router", started=True, name_attr="step_name"),
    WorkflowRunEvent.router_execution_completed.value: _status_handler("Router", started=False, name_attr="step_name"),
    WorkflowRunEvent.steps_execution_started.value: _status_handler("Steps", started=True, name_attr="step_name"),
    WorkflowRunEvent.steps_execution_completed.value: _status_handler("Steps", started=False, name_attr="step_name"),
}


async def dispatch_stream_event(ev_raw: str, chunk: "BaseRunOutputEvent", state: StreamState) -> bool:
    ev = _strip_team_prefix(ev_raw)

    if state.entity_type == "workflow" and ev in _SUPPRESSED_IN_WORKFLOW:
        return False

    handler = HANDLERS.get(ev)
    if handler:
        return await handler(chunk, state)

    return False
