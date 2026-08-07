"""Helper classes and functions for workflow HITL (Human-in-the-Loop) execution.

This module contains shared utilities used by the execute and continue_run methods
(sync/async, streaming/non-streaming) to reduce code duplication.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

from agno.run.base import RunStatus
from agno.utils.log import log_debug
from agno.workflow.types import PauseKind, StepOutput

if TYPE_CHECKING:
    from agno.media import Audio, File, Image, Video
    from agno.run.workflow import WorkflowRunOutput
    from agno.session.workflow import WorkflowSession
    from agno.workflow.types import StepInput, StepRequirement, WorkflowExecutionInput


@dataclass
class StepPauseResult:
    """Result of a step pause status check.

    Attributes:
        should_pause: Whether the workflow should pause for user interaction.
        step_requirement: The step requirement for any pause type (confirmation, user input, or route selection).
    """

    should_pause: bool = False
    step_requirement: Optional["StepRequirement"] = None


def step_pause_status(
    step: Any,
    step_index: int,
    step_input: "StepInput",
    step_type: str,
    for_route_selection: bool = False,
) -> StepPauseResult:
    """Check if a workflow component requires pausing for user interaction.

    This is a unified function that handles pause checks for all component types:
    - Step: confirmation or user input
    - Loop, Condition, Steps, Router: confirmation
    - Router: route selection (when for_route_selection=True)

    Args:
        step: The workflow component to check (Step, Loop, Condition, Steps, or Router).
        step_index: Index of the step in the workflow.
        step_input: The prepared input for the step.
        step_type: Type of the component ("Step", "Loop", "Condition", "Steps", "Router").
        for_route_selection: If True, check for Router route selection instead of confirmation.

    Returns:
        StepPauseResult indicating whether to pause and the requirement.
    """
    # Determine if pause is required
    if for_route_selection:
        requires_pause = getattr(step, "requires_user_input", False)
        pause_type = "user selection"
    elif step_type == "Step":
        requires_pause = getattr(step, "requires_confirmation", False) or getattr(step, "requires_user_input", False)
        pause_type = "confirmation" if getattr(step, "requires_confirmation", False) else "user input"
    else:
        requires_pause = getattr(step, "requires_confirmation", False)
        pause_type = "confirmation"

    if not requires_pause:
        return StepPauseResult(should_pause=False)

    # Get step name with fallback
    step_name = getattr(step, "name", None) or f"{step_type.lower()}_{step_index + 1}"
    log_debug(f"{step_type} '{step_name}' requires {pause_type} - pausing workflow")

    # Create the requirement
    if for_route_selection:
        step_requirement = step.create_step_requirement(
            step_index=step_index,
            step_input=step_input,
            for_route_selection=True,
        )
    else:
        step_requirement = step.create_step_requirement(step_index, step_input)

    return StepPauseResult(should_pause=True, step_requirement=step_requirement)


def create_step_paused_event(
    workflow_run_response: "WorkflowRunOutput",
    step: Any,
    step_name: str,
    step_index: int,
    pause_result: StepPauseResult,
) -> Any:
    """Create a StepPausedEvent for streaming.

    Args:
        workflow_run_response: The workflow run output.
        step: The step that triggered the pause.
        step_name: Name of the step.
        step_index: Index of the step.
        pause_result: The step pause result.

    Returns:
        StepPausedEvent instance.
    """
    from agno.run.workflow import StepPausedEvent

    req = pause_result.step_requirement

    # Serialize user_input_schema so the FE knows what fields to render
    user_input_schema = None
    if req and req.user_input_schema:
        user_input_schema = [f.to_dict() for f in req.user_input_schema]

    return StepPausedEvent(
        run_id=workflow_run_response.run_id or "",
        workflow_name=workflow_run_response.workflow_name,
        workflow_id=workflow_run_response.workflow_id,
        session_id=workflow_run_response.session_id,
        step_name=step_name,
        step_index=step_index,
        step_id=getattr(step, "step_id", None),
        requires_confirmation=req.requires_confirmation if req else False,
        confirmation_message=req.confirmation_message if req else None,
        requires_user_input=req.requires_user_input if req else False,
        user_input_message=req.user_input_message if req else None,
        user_input_schema=user_input_schema,
    )


def create_router_paused_event(
    workflow_run_response: "WorkflowRunOutput",
    step_name: str,
    step_index: int,
    pause_result: StepPauseResult,
) -> Any:
    """Create a RouterPausedEvent for streaming.

    Args:
        workflow_run_response: The workflow run output.
        step_name: Name of the router.
        step_index: Index of the router.
        pause_result: The step pause result.

    Returns:
        RouterPausedEvent instance.
    """
    from agno.run.workflow import RouterPausedEvent

    req = pause_result.step_requirement
    return RouterPausedEvent(
        run_id=workflow_run_response.run_id or "",
        workflow_name=workflow_run_response.workflow_name,
        workflow_id=workflow_run_response.workflow_id,
        session_id=workflow_run_response.session_id,
        step_name=step_name,
        step_index=step_index,
        available_choices=req.available_choices if req and req.available_choices else [],
        user_input_message=req.user_input_message if req else None,
        allow_multiple_selections=req.allow_multiple_selections if req else False,
    )


def apply_pause_state(
    workflow_run_response: "WorkflowRunOutput",
    step_index: int,
    step_name: Optional[str],
    collected_step_outputs: List[Union["StepOutput", List["StepOutput"]]],
    pause_result: StepPauseResult,
) -> None:
    """Apply the paused state to the workflow run response.

    Args:
        workflow_run_response: The workflow run output to update.
        step_index: Index of the step that triggered the pause.
        step_name: Name of the step that triggered the pause.
        collected_step_outputs: The step outputs collected so far.
        pause_result: The step pause result containing the requirement.
    """
    workflow_run_response.status = RunStatus.paused
    workflow_run_response.paused_step_index = step_index
    workflow_run_response.paused_step_name = step_name
    workflow_run_response.pause_kind = PauseKind.STEP
    workflow_run_response.step_results = collected_step_outputs

    if pause_result.step_requirement:
        # Append to existing resolved requirements so the FE can see the full
        # HITL history on completed runs.  Only the last entry is "active".
        existing = workflow_run_response.step_requirements or []
        workflow_run_response.step_requirements = existing + [pause_result.step_requirement]


def save_paused_session(
    workflow: Any,
    session: "WorkflowSession",
    workflow_run_response: "WorkflowRunOutput",
) -> None:
    """Save the session with paused state.

    Args:
        workflow: The workflow instance.
        session: The workflow session.
        workflow_run_response: The workflow run output.
    """
    workflow._update_session_metrics(session=session, workflow_run_response=workflow_run_response)
    session.upsert_run(run=workflow_run_response)
    workflow.save_session(session=session)


async def asave_paused_session(
    workflow: Any,
    session: "WorkflowSession",
    workflow_run_response: "WorkflowRunOutput",
) -> None:
    """Save the session with paused state (async version).

    Args:
        workflow: The workflow instance.
        session: The workflow session.
        workflow_run_response: The workflow run output.
    """
    workflow._update_session_metrics(session=session, workflow_run_response=workflow_run_response)
    session.upsert_run(run=workflow_run_response)
    if workflow._has_async_db():
        await workflow.asave_session(session=session)
    else:
        workflow.save_session(session=session)


def check_output_review_status(
    step: Any,
    step_index: int,
    step_input: "StepInput",
    step_output: "StepOutput",
    retry_count: int = 0,
) -> StepPauseResult:
    """Check if a step requires post-execution output review.

    Handles both bool and callable for requires_output_review (conditional HITL).

    Args:
        step: The step component that was executed.
        step_index: Index of the step in the workflow.
        step_input: The input that was used for the step.
        step_output: The output produced by the step.
        retry_count: Number of previous retry attempts.

    Returns:
        StepPauseResult indicating whether to pause for review.
    """
    requires_review = getattr(step, "requires_output_review", False)

    # Handle callable predicate (conditional HITL)
    if callable(requires_review):
        try:
            requires_review = requires_review(step_output)
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(
                "requires_output_review predicate raised %s: %s — defaulting to no review",
                type(e).__name__,
                e,
            )
            requires_review = False

    if not requires_review:
        return StepPauseResult(should_pause=False)

    step_name = getattr(step, "name", None) or f"step_{step_index + 1}"
    log_debug(f"Step '{step_name}' requires output review - pausing workflow")

    step_requirement = step.create_output_review_requirement(
        step_index, step_input, step_output, retry_count=retry_count
    )
    return StepPauseResult(should_pause=True, step_requirement=step_requirement)


def check_timeout(step_requirement: "StepRequirement") -> Optional[str]:
    """Check if a step requirement has timed out.

    Returns the on_timeout action if timed out, None otherwise.
    Timeout is checked at continue_run() time, not via a background timer.

    Args:
        step_requirement: The step requirement to check.

    Returns:
        The on_timeout action string ("cancel", "skip", "approve") if timed out, None otherwise.
    """
    if step_requirement.timeout_at is None:
        return None

    from datetime import datetime, timezone

    if datetime.now(timezone.utc) >= step_requirement.timeout_at:
        return step_requirement.on_timeout
    return None


def apply_post_execution_pause_state(
    workflow_run_response: "WorkflowRunOutput",
    step_index: int,
    step_name: Optional[str],
    collected_step_outputs: List[Union["StepOutput", List["StepOutput"]]],
    pause_result: StepPauseResult,
    step_output: "StepOutput",
    previous_step_outputs: Optional[Dict[str, "StepOutput"]] = None,
) -> None:
    """Apply paused state after a step has already executed (for output review).

    Unlike apply_pause_state() which is for pre-execution pauses, this function
    handles the case where the step has already produced output. The step_output
    is added to collected_step_outputs before pausing so it's preserved across
    the pause/resume cycle.

    Args:
        workflow_run_response: The workflow run output to update.
        step_index: Index of the step that triggered the pause.
        step_name: Name of the step that triggered the pause.
        collected_step_outputs: The step outputs collected so far.
        pause_result: The step pause result containing the requirement.
        step_output: The output from the executed step.
        previous_step_outputs: Dict of step name -> output (updated if provided).
    """
    # Clear transient loop iteration review flag before storing.
    if getattr(step_output, "requires_iteration_review_pause", False):
        step_output.requires_iteration_review_pause = False

    # Store the output before pausing so it survives the pause/resume cycle
    if previous_step_outputs is not None and step_name:
        previous_step_outputs[step_name] = step_output
    # Guard against double-append (streaming paths may have already appended the output)
    if not collected_step_outputs or collected_step_outputs[-1] is not step_output:
        collected_step_outputs.append(step_output)

    workflow_run_response.status = RunStatus.paused
    workflow_run_response.paused_step_index = step_index
    workflow_run_response.paused_step_name = step_name
    workflow_run_response.pause_kind = PauseKind.STEP
    workflow_run_response.step_results = collected_step_outputs

    if pause_result.step_requirement:
        # Append to existing resolved requirements so the FE can see the full
        # HITL history on completed runs.  Only the last entry is "active".
        existing = workflow_run_response.step_requirements or []
        workflow_run_response.step_requirements = existing + [pause_result.step_requirement]


class ContinueExecutionState:
    """State container for continue execution methods.

    This class encapsulates the shared state used across all continue_execute variants
    (sync/async, streaming/non-streaming) to reduce code duplication.
    """

    def __init__(
        self,
        workflow_run_response: "WorkflowRunOutput",
        execution_input: "WorkflowExecutionInput",
    ):
        # Restore previous step outputs from step_results
        self.collected_step_outputs: List[Union["StepOutput", List["StepOutput"]]] = list(
            workflow_run_response.step_results or []
        )
        self.previous_step_outputs: Dict[str, "StepOutput"] = {}
        for step_output in self.collected_step_outputs:
            if isinstance(step_output, StepOutput) and step_output.step_name:
                self.previous_step_outputs[step_output.step_name] = step_output

        # Initialize media lists
        self.shared_images: List["Image"] = execution_input.images or []
        self.output_images: List["Image"] = (execution_input.images or []).copy()
        self.shared_videos: List["Video"] = execution_input.videos or []
        self.output_videos: List["Video"] = (execution_input.videos or []).copy()
        self.shared_audio: List["Audio"] = execution_input.audio or []
        self.output_audio: List["Audio"] = (execution_input.audio or []).copy()
        self.shared_files: List["File"] = execution_input.files or []
        self.output_files: List["File"] = (execution_input.files or []).copy()

        # Restore shared media from previous steps
        for step_output in self.collected_step_outputs:
            if isinstance(step_output, StepOutput):
                self.shared_images.extend(step_output.images or [])
                self.shared_videos.extend(step_output.videos or [])
                self.shared_audio.extend(step_output.audio or [])
                self.shared_files.extend(step_output.files or [])
                self.output_images.extend(step_output.images or [])
                self.output_videos.extend(step_output.videos or [])
                self.output_audio.extend(step_output.audio or [])
                self.output_files.extend(step_output.files or [])

    def extend_media_from_step(self, step_output: "StepOutput") -> None:
        """Extend shared and output media lists from a step output."""
        self.shared_images.extend(step_output.images or [])
        self.shared_videos.extend(step_output.videos or [])
        self.shared_audio.extend(step_output.audio or [])
        self.shared_files.extend(step_output.files or [])
        self.output_images.extend(step_output.images or [])
        self.output_videos.extend(step_output.videos or [])
        self.output_audio.extend(step_output.audio or [])
        self.output_files.extend(step_output.files or [])

    def add_step_output(self, step_name: str, step_output: "StepOutput") -> None:
        """Add a step output to tracking collections and extend media."""
        self.previous_step_outputs[step_name] = step_output
        self.collected_step_outputs.append(step_output)
        self.extend_media_from_step(step_output)


def finalize_workflow_completion(
    workflow_run_response: "WorkflowRunOutput",
    state: ContinueExecutionState,
) -> None:
    """Finalize workflow completion by updating metrics and status.

    This helper consolidates the common completion logic used across all
    continue_execute variants.

    Args:
        workflow_run_response: The workflow run output to finalize.
        state: The execution state containing collected outputs and media.
    """
    if state.collected_step_outputs:
        if workflow_run_response.metrics:
            workflow_run_response.metrics.stop_timer()

        # Extract final content from last step output
        last_output = cast(StepOutput, state.collected_step_outputs[-1])

        if getattr(last_output, "steps", None):
            _cur = last_output
            while getattr(_cur, "steps", None):
                _steps = _cur.steps or []
                if not _steps:
                    break
                _cur = _steps[-1]
            workflow_run_response.content = _cur.content
        else:
            workflow_run_response.content = last_output.content
    else:
        workflow_run_response.content = "No steps executed"

    workflow_run_response.step_results = state.collected_step_outputs
    workflow_run_response.images = state.output_images
    workflow_run_response.videos = state.output_videos
    workflow_run_response.audio = state.output_audio
    workflow_run_response.status = RunStatus.completed
    workflow_run_response.paused_step_index = None
    workflow_run_response.paused_step_name = None
    workflow_run_response.pause_kind = None


# -------------------------------------------------------------------------
# Executor HITL helpers — for agent/team tool-level pauses within steps
# -------------------------------------------------------------------------


def is_executor_pause(step_output: Any) -> bool:
    """Return True if step_output represents an agent/team executor HITL pause.

    Executor-level HITL only applies when the step's executor is an agent or team.
    If the executor is a nested Workflow (or anything else), its `is_paused` flag
    must not be treated as an executor pause — the nested workflow has its own
    pause/resume lifecycle.

    For composite steps (Condition, Loop, Router, Steps), the pause originates from
    an inner Step but is propagated up with step_type="Condition"/etc and no
    executor_type. In that case we check the nested steps for the actual executor.
    """
    if not getattr(step_output, "is_paused", False):
        return False
    executor_type = getattr(step_output, "executor_type", None)
    # Normalize enum -> value for comparison
    executor_type_value = getattr(executor_type, "value", executor_type)
    if executor_type_value in ("agent", "team"):
        return True
    # Check nested steps — composite steps (Condition/Loop/Router) propagate
    # is_paused but don't carry executor_type themselves.
    nested = getattr(step_output, "steps", None)
    if nested:
        for inner in reversed(nested):
            if is_executor_pause(inner):
                return True
    return False


def get_last_executor_run(workflow_run_response: "WorkflowRunOutput") -> Any:
    """Get the most recent paused executor run from step_executor_runs.

    ``step_executor_runs`` is append-only: if a Loop runs the same step multiple
    times (or multiple steps executed before the pause) it can contain several
    entries. Return the last entry whose RunOutput is actually paused; fall back
    to the absolute last entry only if none report ``is_paused`` (legacy shape
    or executor that doesn't surface the flag).
    """
    runs = workflow_run_response.step_executor_runs
    if not runs:
        return None
    for run in reversed(runs):
        if getattr(run, "is_paused", False):
            return run
    return runs[-1]


def resolve_executor_pause(
    step: Any,
    workflow_run_response: "WorkflowRunOutput",
    *,
    force_find_inner: bool = False,
) -> Optional[tuple]:
    """Resolve the inner Step and paused executor run for an executor-level pause.

    Centralizes the "how do we find the inner step + executor run" logic so all
    callers (sync/async x streaming/non-streaming, plain/router branches) stay
    consistent. Returns None when the pause cannot be resolved.

    Args:
        step: The top-level workflow component that paused. May be a Step or a
            composite (Condition/Loop/Router/Steps).
        workflow_run_response: The workflow run output (used to locate the
            paused executor's RunOutput).
        force_find_inner: If True (router branches), skip the ``isinstance(step, Step)``
            short-circuit and always search via ``_find_inner_step_by_executor``,
            falling back to ``step`` itself. Matches existing router behavior.

    Returns:
        Tuple of (inner_step, executor_run) when the pause is resolvable, else None.
    """
    # Local imports to avoid a circular import (workflow.py imports from this module).
    from agno.workflow.step import Step
    from agno.workflow.workflow import _find_inner_step_by_executor

    if force_find_inner:
        inner = _find_inner_step_by_executor(step) or step
    else:
        inner = step if isinstance(step, Step) else _find_inner_step_by_executor(step)

    executor_run = get_last_executor_run(workflow_run_response)
    if not inner or not executor_run:
        return None
    return inner, executor_run


def apply_executor_pause(
    inner_step: Any,
    step_index: int,
    step_name: str,
    executor_response: Any,
    workflow_run_response: "WorkflowRunOutput",
    collected_step_outputs: list,
) -> "StepRequirement":
    """Apply executor pause state to the workflow run response.

    Sets workflow status to paused, creates the executor StepRequirement,
    and returns it. Callers are responsible for saving the session.

    Args:
        inner_step: The Step instance containing the paused executor (may be
            resolved from a composite step via _find_inner_step_by_executor).
        step_index: Index of the top-level step in the workflow.
        step_name: Name of the top-level step.
        executor_response: The paused RunOutput/TeamRunOutput from step_executor_runs.
        workflow_run_response: The workflow run output to update.
        collected_step_outputs: Step outputs collected so far.

    Returns:
        The created StepRequirement for the executor pause.
    """
    step_req = inner_step._create_executor_step_requirement(step_index, executor_response)
    workflow_run_response.status = RunStatus.paused
    workflow_run_response.paused_step_index = step_index
    workflow_run_response.paused_step_name = step_name
    workflow_run_response.pause_kind = PauseKind.EXECUTOR
    existing = workflow_run_response.step_requirements or []
    workflow_run_response.step_requirements = existing + [step_req]
    workflow_run_response.step_results = collected_step_outputs
    return step_req


def create_executor_paused_event(
    step_req: "StepRequirement",
    step: Any,
    step_index: int,
    step_name: str,
    workflow_run_response: "WorkflowRunOutput",
) -> Any:
    """Create a StepExecutorPausedEvent for streaming.

    Args:
        step_req: The executor StepRequirement.
        step: The Step instance.
        step_index: Index of the step.
        step_name: Name of the step.
        workflow_run_response: The workflow run output.

    Returns:
        StepExecutorPausedEvent instance.
    """
    from agno.run.workflow import StepExecutorPausedEvent

    return StepExecutorPausedEvent(
        run_id=workflow_run_response.run_id or "",
        workflow_name=workflow_run_response.workflow_name or "",
        workflow_id=workflow_run_response.workflow_id or "",
        session_id=workflow_run_response.session_id or "",
        step_name=step_name,
        step_index=step_index,
        step_id=getattr(step, "step_id", None),
        executor_id=step_req.executor_id,
        executor_name=step_req.executor_name,
        executor_run_id=step_req.executor_run_id,
        executor_type=step_req.executor_type,
        executor_requirements=step_req.executor_requirements,
    )
