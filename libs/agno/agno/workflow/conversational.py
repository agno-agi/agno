"""Conversational sticky steps and goto helpers for Workflows.

See: https://github.com/agno-agi/agno/issues/9128

Design:
- conversational=True steps stay paused until the agent calls complete_step()
- goto(step_name, clear_keys=...) jumps back to a completed conversational
  agent/team step and re-runs it immediately with the current user message
- session_state is only cleared via explicit clear_keys (no hidden namespaces)
- Parallel must not contain conversational steps
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from agno.run.base import RunStatus
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.run.workflow import WorkflowRunOutput
    from agno.workflow.step import Step
    from agno.workflow.types import StepOutput


COMPLETE_STEP_TOOL_NAME = "complete_step"
GOTO_TOOL_NAME = "goto"


@dataclass
class ConversationalSignal:
    """Control signal produced by complete_step / goto tools during an agent turn."""

    kind: str  # "complete" | "goto"
    data: Optional[Dict[str, Any]] = None
    goto_step: Optional[str] = None
    clear_keys: List[str] = field(default_factory=list)


@dataclass
class ConversationalControl:
    """Mutable control plane shared between injected tools and Step.execute."""

    available_goto_steps: List[Tuple[str, str]] = field(default_factory=list)
    signal: Optional[ConversationalSignal] = None

    def reset_signal(self) -> None:
        self.signal = None


def build_conversational_tools(control: ConversationalControl) -> List[Callable[..., Any]]:
    """Build complete_step / goto callables closed over ``control``."""

    def complete_step(**data: Any) -> str:
        """Mark the current conversational step as complete.

        Call this when you have collected everything needed for this step.
        Optional keyword arguments become the structured StepOutput content
        for the next step. With no arguments, the step completes and the next
        step receives this turn's natural-language reply as content.
        """
        # goto wins if both were somehow set; prefer the latest call
        control.signal = ConversationalSignal(kind="complete", data=dict(data) if data else None)
        if data:
            return f"Step marked complete with data: {data}"
        return "Step marked complete."

    def goto(step_name: str, clear_keys: Optional[List[str]] = None) -> str:
        """Go back to an earlier completed conversational step and continue from there.

        Only previously completed conversational=True agent/team steps listed in
        the tool context are valid. Use clear_keys to remove stale session_state
        entries that depended on the steps being invalidated.
        """
        valid = {name for name, _ in control.available_goto_steps}
        if step_name not in valid:
            available = ", ".join(sorted(valid)) if valid else "(none)"
            return (
                f"Invalid goto target '{step_name}'. You may only go back to "
                f"completed conversational steps: {available}"
            )

        control.signal = ConversationalSignal(
            kind="goto",
            goto_step=step_name,
            clear_keys=list(clear_keys) if clear_keys else [],
        )
        if clear_keys:
            return f"Will go back to step '{step_name}' and clear keys: {clear_keys}"
        return f"Will go back to step '{step_name}'."

    # Enrich goto docstring with current targets (models often see the docstring)
    if control.available_goto_steps:
        lines = ["\n\nCurrently available goto targets:"]
        for name, description in control.available_goto_steps:
            desc = description or name
            lines.append(f"- {name}: {desc}")
        goto.__doc__ = (goto.__doc__ or "") + "\n".join(lines)

    return [complete_step, goto]


def apply_signal_to_step_output(
    step_output: "StepOutput",
    signal: Optional[ConversationalSignal],
    *,
    conversational: bool,
) -> "StepOutput":
    """Annotate StepOutput based on conversational control signal."""
    if not conversational:
        return step_output

    if signal is None:
        step_output.conversational_complete = False
        return step_output

    if signal.kind == "goto":
        step_output.goto_step = signal.goto_step
        step_output.goto_clear_keys = list(signal.clear_keys)
        step_output.conversational_complete = True
        return step_output

    # complete
    step_output.conversational_complete = True
    if signal.data:
        step_output.content = signal.data
    # else keep natural-language content from the agent turn
    return step_output


def collect_completed_goto_targets(
    steps: Sequence[Any],
    step_results: Sequence[Any],
    current_step_name: Optional[str],
) -> List[Tuple[str, str]]:
    """Return (name, description) for completed conversational steps before the current one.

    Only ``conversational=True`` agent/team Steps are eligible goto targets
    (``conversational=True`` already requires an agent or team executor).
    """
    name_to_index = _flat_step_name_index(steps)
    current_index = name_to_index.get(current_step_name) if current_step_name else None

    completed_names: List[str] = []
    for result in step_results:
        if isinstance(result, list):
            for nested in result:
                name = getattr(nested, "step_name", None)
                if name:
                    completed_names.append(name)
        else:
            name = getattr(result, "step_name", None)
            if name:
                completed_names.append(name)

    # Deduplicate while preserving order
    seen = set()
    ordered_completed: List[str] = []
    for name in completed_names:
        if name not in seen:
            seen.add(name)
            ordered_completed.append(name)

    step_meta = _flat_step_metadata(steps)
    targets: List[Tuple[str, str]] = []
    for name in ordered_completed:
        idx = name_to_index.get(name)
        if idx is None:
            continue
        if current_index is not None and idx >= current_index:
            continue
        meta = step_meta.get(name) or {}
        if not meta.get("conversational"):
            continue
        description = meta.get("description") or name
        targets.append((name, description))
    return targets


def is_conversational_goto_target(steps: Sequence[Any], step_name: str) -> bool:
    """True if ``step_name`` is a conversational=True Step (agent/team)."""
    meta = _flat_step_metadata(steps).get(step_name) or {}
    return bool(meta.get("conversational"))


def require_conversational_goto_target(steps: Sequence[Any], step_name: str) -> None:
    """Raise ValueError unless ``step_name`` is a conversational=True agent/team step."""
    if not is_conversational_goto_target(steps, step_name):
        raise ValueError(f"goto target '{step_name}' must be a conversational=True agent/team step")


def find_step_index_by_name(steps: Sequence[Any], step_name: str) -> Optional[int]:
    """Find top-level step index by name (nested names map to their top-level container)."""
    for i, step in enumerate(steps):
        if getattr(step, "name", None) == step_name:
            return i
        # Nested: if the named step lives inside this container, return container index
        if _contains_step_name(step, step_name):
            return i
    return None


def prune_step_results(
    step_results: List[Any],
    previous_step_outputs: Dict[str, Any],
    target_step_name: str,
    steps: Sequence[Any],
) -> Tuple[List[Any], Dict[str, Any]]:
    """Remove target step and all subsequent completed results.

    Also rebuilds previous_step_outputs from remaining results.
    """
    target_index = find_step_index_by_name(steps, target_step_name)
    name_to_index = _flat_step_name_index(steps)

    if target_index is None:
        log_warning(f"goto target '{target_step_name}' not found in workflow steps")
        return step_results, previous_step_outputs

    pruned: List[Any] = []
    for result in step_results:
        if isinstance(result, list):
            # Keep nested list only if its container index is before target
            # Heuristic: use first nested step_name
            first_name = None
            for nested in result:
                first_name = getattr(nested, "step_name", None)
                if first_name:
                    break
            idx = name_to_index.get(first_name) if first_name else None
            if idx is not None and idx < target_index:
                pruned.append(result)
        else:
            name = getattr(result, "step_name", None)
            idx = name_to_index.get(name) if name else None
            # Also treat nested names that map to a container index
            if idx is None and name:
                container = find_step_index_by_name(steps, name)
                idx = container
            if idx is not None and idx < target_index:
                pruned.append(result)

    rebuilt: Dict[str, Any] = {}
    for result in pruned:
        if isinstance(result, list):
            for nested in result:
                name = getattr(nested, "step_name", None)
                if name:
                    rebuilt[name] = nested
        else:
            name = getattr(result, "step_name", None)
            if name:
                rebuilt[name] = result

    log_debug(
        f"goto prune: target={target_step_name} index={target_index} kept={len(pruned)}/{len(step_results)} results"
    )
    return pruned, rebuilt


def clear_session_state_keys(session_state: Optional[Dict[str, Any]], keys: Sequence[str]) -> None:
    """Remove explicitly requested keys from session_state."""
    if not session_state or not keys:
        return
    for key in keys:
        if key in session_state:
            session_state.pop(key, None)
            log_debug(f"goto clear_keys: removed session_state['{key}']")


def validate_no_conversational_in_parallel(steps: Optional[Sequence[Any]]) -> None:
    """Raise ValueError if any Parallel contains a conversational step."""
    if not steps:
        return
    from agno.workflow.parallel import Parallel

    def _walk(node: Any, inside_parallel: bool = False) -> None:
        if isinstance(node, Parallel):
            for child in node.steps or []:
                _walk(child, inside_parallel=True)
            return

        conversational = bool(getattr(node, "conversational", False))
        if conversational and inside_parallel:
            name = getattr(node, "name", None) or "unnamed"
            raise ValueError(
                f"conversational=True is not supported inside Parallel "
                f"(step '{name}'). Use sequential steps, Loop, or Router instead."
            )

        # Recurse into containers
        for attr in ("steps", "choices", "else_steps"):
            children = getattr(node, attr, None)
            if children and isinstance(children, (list, tuple)):
                for child in children:
                    _walk(child, inside_parallel=inside_parallel)

    for step in steps:
        _walk(step, inside_parallel=False)


def ensure_conversational_tools_on_executor(
    executor: Any,
    control: ConversationalControl,
) -> List[Callable[..., Any]]:
    """Ensure complete_step/goto tools are present on an agent/team executor.

    Returns the tool callables (always freshly built so goto docstring stays current).
    """
    tools = build_conversational_tools(control)
    existing = list(getattr(executor, "tools", None) or [])

    # Remove prior conversational tools by name, then append fresh ones
    filtered = []
    for tool in existing:
        name = getattr(tool, "__name__", None) or getattr(tool, "name", None)
        if name in (COMPLETE_STEP_TOOL_NAME, GOTO_TOOL_NAME):
            continue
        filtered.append(tool)

    executor.tools = filtered + tools
    return tools


def is_conversational_pause_kind(pause_kind: Any) -> bool:
    from agno.workflow.types import PauseKind

    if pause_kind is None:
        return False
    if isinstance(pause_kind, PauseKind):
        return pause_kind == PauseKind.CONVERSATIONAL
    return str(pause_kind) == PauseKind.CONVERSATIONAL.value


def apply_conversational_pause(
    workflow_run_response: "WorkflowRunOutput",
    step: Any,
    step_index: int,
    step_name: Optional[str],
    step_output: "StepOutput",
    collected_step_outputs: List[Union["StepOutput", List["StepOutput"]]],
) -> None:
    """Apply conversational sticky-step pause state to the workflow run response.

    The step's natural-language reply is kept on workflow content for the UI, but
    the step is not appended to completed step_results until complete_step.
    """
    from agno.workflow.types import PauseKind, StepRequirement, StepType

    workflow_run_response.status = RunStatus.paused
    workflow_run_response.paused_step_index = step_index
    workflow_run_response.paused_step_name = step_name
    workflow_run_response.pause_kind = PauseKind.CONVERSATIONAL
    workflow_run_response.step_results = list(collected_step_outputs)
    # Surface the assistant reply to the user without completing the step
    if step_output.content is not None:
        workflow_run_response.content = step_output.content

    requirement = StepRequirement(
        step_id=getattr(step, "step_id", None) or step_name or f"step_{step_index}",
        step_name=step_name,
        step_index=step_index,
        step_type=StepType.STEP,
        requires_conversational_input=True,
    )
    existing = workflow_run_response.step_requirements or []
    workflow_run_response.step_requirements = existing + [requirement]


def create_conversational_paused_event(
    workflow_run_response: "WorkflowRunOutput",
    step: Any,
    step_name: str,
    step_index: int,
    step_output: "StepOutput",
) -> Any:
    """Create a StepPausedEvent for a conversational sticky-step pause."""
    from agno.run.workflow import StepPausedEvent

    return StepPausedEvent(
        run_id=workflow_run_response.run_id or "",
        workflow_name=workflow_run_response.workflow_name,
        workflow_id=workflow_run_response.workflow_id,
        session_id=workflow_run_response.session_id,
        step_name=step_name,
        step_index=step_index,
        step_id=getattr(step, "step_id", None),
        requires_conversational_input=True,
        content=step_output.content,
        user_input_message="Continue the conversation with the active step.",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _flat_step_name_index(steps: Sequence[Any]) -> Dict[str, int]:
    """Map step name -> top-level index (nested names point at container index)."""
    mapping: Dict[str, int] = {}
    for i, step in enumerate(steps):
        name = getattr(step, "name", None)
        if name:
            mapping[name] = i
        for nested_name in _iter_nested_step_names(step):
            mapping.setdefault(nested_name, i)
    return mapping


def _flat_step_metadata(steps: Sequence[Any]) -> Dict[str, Dict[str, Any]]:
    meta: Dict[str, Dict[str, Any]] = {}

    def _add(node: Any) -> None:
        name = getattr(node, "name", None)
        if name:
            meta[name] = {
                "description": getattr(node, "description", None),
                "conversational": bool(getattr(node, "conversational", False)),
            }
        for attr in ("steps", "choices", "else_steps"):
            children = getattr(node, attr, None)
            if children and isinstance(children, (list, tuple)):
                for child in children:
                    _add(child)

    for step in steps:
        _add(step)
    return meta


def _iter_nested_step_names(node: Any) -> List[str]:
    names: List[str] = []
    for attr in ("steps", "choices", "else_steps"):
        children = getattr(node, attr, None)
        if children and isinstance(children, (list, tuple)):
            for child in children:
                child_name = getattr(child, "name", None)
                if child_name:
                    names.append(child_name)
                names.extend(_iter_nested_step_names(child))
    return names


def _contains_step_name(node: Any, step_name: str) -> bool:
    return step_name in _iter_nested_step_names(node)


def get_last_paused_run(session: Any) -> Any:
    """Return the latest paused run from a WorkflowSession, if any."""
    runs = getattr(session, "runs", None) or []
    for run in reversed(runs):
        status = getattr(run, "status", None)
        status_value = status.value if hasattr(status, "value") else status
        if status_value == "paused":
            return run
    return None
