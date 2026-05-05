from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Dict

from agno.agent import RunEvent
from agno.os.interfaces.slack.helpers import member_name, task_id
from agno.os.interfaces.slack.state import StreamState
from agno.run.agent import BaseAgentRunEvent
from agno.run.workflow import WorkflowRunEvent

if TYPE_CHECKING:
    from slack_sdk.web.async_chat_stream import AsyncChatStream

    from agno.run.base import BaseRunOutputEvent


# Event handlers return True on terminal events to break the stream loop
_EventHandler = Callable[
    ["BaseRunOutputEvent", StreamState, "AsyncChatStream"],
    Awaitable[bool],
]


@dataclass
class _ToolRef:
    tid: str | None  # Slack task card ID (None when tool_call_id is missing)
    label: str  # Display title, e.g. "Researcher: web_search"
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
    card_id: str,
    title: str,
    status: str,
    *,
    output: str | None = None,
) -> None:
    chunk: dict = {"type": "task_update", "id": card_id, "title": title, "status": status}
    if output:
        # Slack rejects plain strings in task_card output slots — requires rich_text
        # even though slack_sdk types output as Optional[str]. Truncate to 200 chars.
        chunk["output"] = {
            "type": "rich_text",
            "elements": [{"type": "rich_text_section", "elements": [{"type": "text", "text": output[:200]}]}],
        }
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
        # Reasoning: internal chain-of-thought, not actionable for Slack users
        RunEvent.reasoning_started.value,
        RunEvent.reasoning_completed.value,
        # Tool calls: workflow steps already emit their own progress cards
        RunEvent.tool_call_started.value,
        RunEvent.tool_call_completed.value,
        RunEvent.tool_call_error.value,
        # Memory: background housekeeping, no user-facing impact
        RunEvent.memory_update_started.value,
        RunEvent.memory_update_completed.value,
        # Content: workflow consolidates final output in WorkflowCompleted
        RunEvent.run_content.value,
        RunEvent.run_intermediate_content.value,
        # Lifecycle: workflow-level events handle start/end, not inner runs
        RunEvent.run_completed.value,
        RunEvent.run_error.value,
        RunEvent.run_cancelled.value,
    }
)


def _make_wf_handler(
    prefix: str,
    label: str,
    *,
    started: bool,
    name_attr: str = "step_name",
) -> _EventHandler:
    # Factory for paired events that just call _wf_task with different params
    async def handler(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
        await _wf_task(chunk, state, stream, prefix, label, started=started, name_attr=name_attr)
        return False

    return handler


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
    # Suppress member agent content in team mode to avoid duplication — leader
    # emits TeamRunContent which aggregates all member outputs into one response
    if state.entity_type == "team" and isinstance(chunk, BaseAgentRunEvent):
        return False
    content = getattr(chunk, "content", None)
    if content is not None:
        state.append_content(content)
    return False


async def _on_run_intermediate_content(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    # Team intermediate content arrives per-member as they finish — showing it
    # would interleave partial outputs. Only agents show intermediate content.
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


async def _on_run_paused(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    # Stash the event; the router attaches one `card` block per pending
    # requirement via stream.stop(blocks=...). The card carries the full
    # approval context (tool name, args, Approve/Deny buttons) and coexists
    # with the streaming plan above it.
    print(f"[DEBUG] _on_run_paused called: run_id={getattr(chunk, 'run_id', None)}")
    state.paused_event = chunk
    # Keep pending task_cards in-progress rather than flipping to complete —
    # the run isn't finished, it's awaiting human input.
    state.terminal_status = "in_progress"

    # Emit a "pending" task card for each paused requirement so the plan
    # block above the awaiting indicator shows WHAT the agent is waiting on.
    # Regular tool_call_started events create these for normal tools, but
    # system tools like ask_user (user_feedback) bypass that event stream
    # and pause directly — without this explicit emit, their bubble has no
    # plan block and Slack's AI-Stream UI collapses the pairing, hiding
    # the user's trigger from the thread pane.
    from agno.os.interfaces.slack.types import _tool_name

    requirements = list(getattr(chunk, "active_requirements", None) or [])
    for req in requirements:
        req_id = getattr(req, "id", None) or ""
        key = f"pause_req_{req_id}"
        if key in state.task_cards:
            continue
        tool_label = _tool_name(req)
        # Emit as "complete" — semantically "the agent has decided which
        # tool to invoke, now awaiting human input". A non-complete status
        # at stream.stop causes Slack's AI-Stream UI to render the bubble
        # as "Something went wrong" with a red error icon, regardless of
        # whether we transition to pending. The awaiting indicator and
        # Card block posted below the bubble carry the actual pause state.
        state.track_task(key, tool_label, "complete")
        await _emit_task(stream, key, tool_label, "complete")

    # Fallback placeholder — only if we couldn't emit any task cards (e.g.
    # requirements empty for some reason) and no prior tool content streamed.
    # Without at least one non-empty block, Slack's AI-Stream UI collapses
    # the question+response pairing and hides the trigger.
    if not state.has_content() and state.stream_chars_sent == 0 and not state.task_cards:
        await stream.append(markdown_text="_Reviewing request…_")

    # The "⏸ Awaiting approval of <tool>…" indicator is posted by the
    # router as a SEPARATE chat.postMessage in the same thread (see the
    # pause path in attach_to_app). Posting it separately means we can
    # chat.delete just that message once the user decides — preserving
    # the tool-call audit trail in THIS streamed bubble (Thinking, prior
    # tool calls) which would otherwise be collateral damage of any
    # cleanup that targeted the streamed message.
    return True


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


# Keys are normalized (no "Team" prefix) so agent + team events share handlers
HANDLERS: Dict[str, _EventHandler] = {
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
    # Cancelled runs are terminal errors — user sees error status, not silent stop
    RunEvent.run_cancelled.value: _on_run_error,
    # HITL pause — stream ends, router posts Block Kit approval card separately
    RunEvent.run_paused.value: _on_run_paused,
    # Workflow Lifecycle Events
    WorkflowRunEvent.step_output.value: _on_step_output,
    WorkflowRunEvent.workflow_started.value: _on_workflow_started,
    WorkflowRunEvent.workflow_completed.value: _on_workflow_completed,
    WorkflowRunEvent.workflow_error.value: _on_workflow_error,
    WorkflowRunEvent.workflow_cancelled.value: _on_workflow_error,
    # Workflow Step Events
    WorkflowRunEvent.step_started.value: _make_wf_handler("step", "", started=True),
    WorkflowRunEvent.step_completed.value: _make_wf_handler("step", "", started=False),
    WorkflowRunEvent.step_error.value: _on_step_error,
    # Workflow Loop Events
    WorkflowRunEvent.loop_execution_started.value: _on_loop_execution_started,
    WorkflowRunEvent.loop_iteration_started.value: _on_loop_iteration_started,
    WorkflowRunEvent.loop_iteration_completed.value: _on_loop_iteration_completed,
    WorkflowRunEvent.loop_execution_completed.value: _on_loop_execution_completed,
    # Workflow Structural Events (factory-generated)
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
    import logging

    logging.basicConfig(filename="/tmp/slack_events_debug.log", level=logging.DEBUG, force=True)
    logger = logging.getLogger("slack_events")
    # Strip "Team" prefix so agent + team events share handlers
    ev = ev_raw.removeprefix("Team")
    logger.warning(f"[DEBUG] process_event: {ev_raw} -> {ev}")

    # Suppress nested agent internals in workflow mode
    if state.entity_type == "workflow" and ev in _SUPPRESSED_IN_WORKFLOW:
        return False

    handler = HANDLERS.get(ev)
    if handler:
        result = await handler(chunk, state, stream)
        if ev == "RunPaused":
            print(
                f"[DEBUG] RunPaused handler returned: {result}, paused_event set: {state.paused_event is not None}",
                flush=True,
            )
        return result

    return False
