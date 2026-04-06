"""Helper classes and functions for workflow HITL (Human-in-the-Loop) execution.

This module contains shared utilities used by the execute and continue_run methods
(sync/async, streaming/non-streaming) to reduce code duplication.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

from agno.run.base import RunStatus
from agno.utils.log import log_debug
from agno.workflow.types import StepOutput

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
    workflow_run_response.step_results = collected_step_outputs

    if pause_result.step_requirement:
        workflow_run_response.step_requirements = [pause_result.step_requirement]


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
