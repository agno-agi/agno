from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.metrics import RunMetrics
from agno.session.workflow import WorkflowSession
from agno.utils.media import (
    reconstruct_audio_list,
    reconstruct_files,
    reconstruct_images,
    reconstruct_videos,
)
from agno.utils.timer import Timer


class OnReject(str, Enum):
    """Action to take when a step requiring confirmation is rejected.

    Attributes:
        skip: Skip the rejected step and continue with the next step in the workflow.
        cancel: Cancel the entire workflow when the step is rejected.
        else_branch: For Condition only - execute the else_steps branch when rejected.
        retry: Re-execute the rejected step (optionally with feedback).
    """

    skip = "skip"
    cancel = "cancel"
    else_branch = "else"
    retry = "retry"


class OnTimeout(str, Enum):
    """Action to take when a HITL pause times out.

    Attributes:
        cancel: Cancel the workflow when the timeout expires (default).
        skip: Skip the timed-out step and continue with the next step.
        approve: Auto-approve the step output and continue.
    """

    cancel = "cancel"
    skip = "skip"
    approve = "approve"


class OnError(str, Enum):
    """Action to take when a step encounters an error during execution.

    Attributes:
        fail: Fail the workflow immediately when an error occurs (default).
        skip: Skip the failed step and continue with the next step.
        pause: Pause the workflow and allow the user to decide (retry or skip) via HITL.
    """

    fail = "fail"
    skip = "skip"
    pause = "pause"


@dataclass
class HumanReview:
    """Human-in-the-loop configuration for workflow components.

    Groups all HITL parameters into a single config object. Pass it via
    ``human_review=HumanReview(...)`` on Step, Loop, or Router.

    Not all fields apply to all components. Each component validates
    at construction time and raises ``ValueError`` for unsupported fields.

    Field compatibility:
        requires_confirmation   - Step, Loop, Router, Condition, Steps
        requires_user_input     - Step, Router
        requires_output_review  - Step, Router
        requires_iteration_review - Loop
    """

    # Pre-execution confirmation (Step, Loop, Router, Condition, Steps)
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None

    # User input collection (Step, Router only)
    requires_user_input: bool = False
    user_input_message: Optional[str] = None
    user_input_schema: Optional[List[Dict[str, Any]]] = None

    # Post-execution output review (Step, Router only)
    requires_output_review: Union[bool, Any] = False  # Union[bool, Callable[[StepOutput], bool]]
    output_review_message: Optional[str] = None

    # Per-iteration review (Loop only)
    requires_iteration_review: bool = False
    iteration_review_message: Optional[str] = None

    # Shared behavior
    on_reject: Union[OnReject, str] = OnReject.skip
    on_error: Union[OnError, str] = OnError.skip
    max_retries: int = 3
    timeout: Optional[int] = None
    on_timeout: Union[OnTimeout, str] = OnTimeout.cancel

    def __post_init__(self) -> None:
        # Fail early on conflicting flags
        if self.requires_output_review and self.requires_iteration_review:
            raise ValueError(
                "requires_output_review and requires_iteration_review cannot both be set. "
                "Use requires_output_review on Step/Router, requires_iteration_review on Loop."
            )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "requires_confirmation": self.requires_confirmation,
            "confirmation_message": self.confirmation_message,
            "requires_user_input": self.requires_user_input,
            "user_input_message": self.user_input_message,
            "user_input_schema": self.user_input_schema,
            "requires_output_review": self.requires_output_review
            if isinstance(self.requires_output_review, bool)
            else True,
            "output_review_message": self.output_review_message,
            "requires_iteration_review": self.requires_iteration_review,
            "iteration_review_message": self.iteration_review_message,
            "on_reject": self.on_reject.value if isinstance(self.on_reject, OnReject) else self.on_reject,
            "on_error": self.on_error.value if isinstance(self.on_error, OnError) else self.on_error,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
            "on_timeout": self.on_timeout.value if isinstance(self.on_timeout, OnTimeout) else self.on_timeout,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HumanReview":
        """Create HITL from dictionary."""
        return cls(
            requires_confirmation=data.get("requires_confirmation", False),
            confirmation_message=data.get("confirmation_message"),
            requires_user_input=data.get("requires_user_input", False),
            user_input_message=data.get("user_input_message"),
            user_input_schema=data.get("user_input_schema"),
            requires_output_review=data.get("requires_output_review", False),
            output_review_message=data.get("output_review_message"),
            requires_iteration_review=data.get("requires_iteration_review", False),
            iteration_review_message=data.get("iteration_review_message"),
            on_reject=data.get("on_reject", "skip"),
            on_error=data.get("on_error", "skip"),
            max_retries=data.get("max_retries", 3),
            timeout=data.get("timeout"),
            on_timeout=data.get("on_timeout", "cancel"),
        )


def validate_human_review_for_step(hr: "HumanReview") -> None:
    """Validate HumanReview config for use on a Step.

    Raises ValueError if unsupported fields are set.
    Supported: requires_confirmation, requires_user_input, requires_output_review.
    """
    if hr.requires_iteration_review:
        raise ValueError(
            "requires_iteration_review is not supported on Step. "
            "Supported: requires_confirmation, requires_user_input, requires_output_review."
        )


def validate_human_review_for_loop(hr: "HumanReview") -> None:
    """Validate HumanReview config for use on a Loop.

    Raises ValueError if unsupported fields are set.
    Supported: requires_confirmation, requires_iteration_review.
    """
    if hr.requires_output_review:
        raise ValueError(
            "requires_output_review is not supported on Loop. "
            "Supported: requires_confirmation, requires_iteration_review."
        )
    if hr.requires_user_input:
        raise ValueError(
            "requires_user_input is not supported on Loop. Supported: requires_confirmation, requires_iteration_review."
        )


def validate_human_review_for_router(hr: "HumanReview") -> None:
    """Validate HumanReview config for use on a Router.

    Raises ValueError if unsupported fields are set.
    Supported: requires_confirmation, requires_user_input, requires_output_review.
    """
    if hr.requires_iteration_review:
        raise ValueError(
            "requires_iteration_review is not supported on Router. "
            "Supported: requires_confirmation, requires_user_input, requires_output_review."
        )


def validate_human_review_for_condition(hr: "HumanReview") -> None:
    """Validate HumanReview config for use on a Condition.

    Raises ValueError if unsupported fields are set.
    Supported: requires_confirmation.
    """
    if hr.requires_output_review:
        raise ValueError("requires_output_review is not supported on Condition. Supported: requires_confirmation.")
    if hr.requires_user_input:
        raise ValueError("requires_user_input is not supported on Condition. Supported: requires_confirmation.")
    if hr.requires_iteration_review:
        raise ValueError("requires_iteration_review is not supported on Condition. Supported: requires_confirmation.")


def validate_human_review_for_steps(hr: "HumanReview") -> None:
    """Validate HumanReview config for use on a Steps pipeline.

    Raises ValueError if unsupported fields are set.
    Supported: requires_confirmation.
    """
    if hr.requires_output_review:
        raise ValueError("requires_output_review is not supported on Steps. Supported: requires_confirmation.")
    if hr.requires_user_input:
        raise ValueError("requires_user_input is not supported on Steps. Supported: requires_confirmation.")
    if hr.requires_iteration_review:
        raise ValueError("requires_iteration_review is not supported on Steps. Supported: requires_confirmation.")


def validate_human_review_for_parallel(hr: "HumanReview") -> None:
    """Validate HumanReview config for use on a Parallel.

    Raises ValueError if any HITL fields are set. Parallel does not support
    HITL pauses — steps inside a Parallel execute concurrently and cannot
    be individually paused for human review.
    """
    if hr.requires_confirmation:
        raise ValueError("requires_confirmation is not supported on Parallel.")
    if hr.requires_output_review:
        raise ValueError("requires_output_review is not supported on Parallel.")
    if hr.requires_user_input:
        raise ValueError("requires_user_input is not supported on Parallel.")
    if hr.requires_iteration_review:
        raise ValueError("requires_iteration_review is not supported on Parallel.")


@dataclass
class WorkflowExecutionInput:
    """Input data for a step execution"""

    input: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None

    additional_data: Optional[Dict[str, Any]] = None

    # Media inputs
    images: Optional[List[Image]] = None
    videos: Optional[List[Video]] = None
    audio: Optional[List[Audio]] = None
    files: Optional[List[File]] = None

    def get_input_as_string(self) -> Optional[str]:
        """Convert input to string representation"""
        if self.input is None:
            return None

        if isinstance(self.input, str):
            return self.input
        elif isinstance(self.input, BaseModel):
            return self.input.model_dump_json(indent=2, exclude_none=True)
        elif isinstance(self.input, (dict, list)):
            import json

            return json.dumps(self.input, indent=2, default=str)
        else:
            return str(self.input)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        input_dict: Optional[Union[str, Dict[str, Any], List[Any]]] = None
        if self.input is not None:
            if isinstance(self.input, BaseModel):
                input_dict = self.input.model_dump(exclude_none=True)
            elif isinstance(self.input, (dict, list)):
                input_dict = self.input
            else:
                input_dict = str(self.input)

        return {
            "input": input_dict,
            "additional_data": self.additional_data,
            "images": [img.to_dict() for img in self.images] if self.images else None,
            "videos": [vid.to_dict() for vid in self.videos] if self.videos else None,
            "audio": [aud.to_dict() for aud in self.audio] if self.audio else None,
            "files": [file.to_dict() for file in self.files] if self.files else None,
        }


@dataclass
class StepInput:
    """Input data for a step execution"""

    input: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None

    previous_step_content: Optional[Any] = None
    previous_step_outputs: Optional[Dict[str, "StepOutput"]] = None

    additional_data: Optional[Dict[str, Any]] = None

    # Media inputs
    images: Optional[List[Image]] = None
    videos: Optional[List[Video]] = None
    audio: Optional[List[Audio]] = None
    files: Optional[List[File]] = None

    workflow_session: Optional["WorkflowSession"] = None

    def get_input_as_string(self) -> Optional[str]:
        """Convert input to string representation"""
        if self.input is None:
            return None

        if isinstance(self.input, str):
            return self.input
        elif isinstance(self.input, BaseModel):
            return self.input.model_dump_json(indent=2, exclude_none=True)
        elif isinstance(self.input, (dict, list)):
            import json

            return json.dumps(self.input, indent=2, default=str)
        else:
            return str(self.input)

    def get_step_output(self, step_name: str) -> Optional["StepOutput"]:
        """Get output from a specific previous step by name

        Searches recursively through nested steps (Parallel, Condition, Router, Loop, Steps)
        to find step outputs at any depth.
        """
        if not self.previous_step_outputs:
            return None

        # First try direct lookup
        direct = self.previous_step_outputs.get(step_name)
        if direct:
            return direct

        # Search recursively in nested steps
        return self._search_nested_steps(step_name)

    def _search_nested_steps(self, step_name: str) -> Optional["StepOutput"]:
        """Recursively search for a step output in nested steps (Parallel, Condition, etc.)"""
        if not self.previous_step_outputs:
            return None

        for step_output in self.previous_step_outputs.values():
            result = self._search_in_step_output(step_output, step_name)
            if result:
                return result
        return None

    def _search_in_step_output(self, step_output: "StepOutput", step_name: str) -> Optional["StepOutput"]:
        """Helper to recursively search within a single StepOutput"""
        if not step_output.steps:
            return None

        for nested_step in step_output.steps:
            if nested_step.step_name == step_name:
                return nested_step
            # Recursively search deeper
            result = self._search_in_step_output(nested_step, step_name)
            if result:
                return result
        return None

    def get_step_content(self, step_name: str) -> Optional[Union[str, Dict[str, str]]]:
        """Get content from a specific previous step by name

        For parallel steps, if you ask for the parallel step name, returns a dict
        with {step_name: content} for each sub-step.
        For other nested steps (Condition, Router, Loop, Steps), returns the deepest content.
        """
        step_output = self.get_step_output(step_name)
        if not step_output:
            return None

        # Check if this is a parallel step with nested steps
        if step_output.step_type == "Parallel" and step_output.steps:
            # Return dict with {step_name: content} for each sub-step
            parallel_content = {}
            for sub_step in step_output.steps:
                if sub_step.step_name and sub_step.content:
                    # Check if this sub-step has its own nested steps (like Condition -> Research Step)
                    if sub_step.steps and len(sub_step.steps) > 0:
                        # This is a composite step (like Condition) - get content from its nested steps
                        for nested_step in sub_step.steps:
                            if nested_step.step_name and nested_step.content:
                                parallel_content[nested_step.step_name] = str(nested_step.content)
                    else:
                        # This is a direct step - use its content
                        parallel_content[sub_step.step_name] = str(sub_step.content)
            return parallel_content if parallel_content else str(step_output.content)

        # For other nested step types (Condition, Router, Loop, Steps), get the deepest content
        elif step_output.steps and len(step_output.steps) > 0:
            # This is a nested step structure - recursively get the deepest content
            return self._get_deepest_step_content(step_output.steps[-1])

        # Regular step, return content directly
        return step_output.content  # type: ignore[return-value]

    def _get_deepest_step_content(self, step_output: "StepOutput") -> Optional[Union[str, Dict[str, str]]]:
        """Helper method to recursively extract deepest content from nested steps"""
        # If this step has nested steps, go deeper
        if step_output.steps and len(step_output.steps) > 0:
            return self._get_deepest_step_content(step_output.steps[-1])

        # Return the content of this step
        return step_output.content  # type: ignore[return-value]

    def get_all_previous_content(self) -> str:
        """Get concatenated content from all previous steps"""
        if not self.previous_step_outputs:
            return ""

        content_parts = []
        for step_name, output in self.previous_step_outputs.items():
            if output.content:
                content_parts.append(f"=== {step_name} ===\n{output.content}")

        return "\n\n".join(content_parts)

    def get_last_step_content(self) -> Optional[str]:
        """Get content from the most recent step (for backward compatibility)"""
        if not self.previous_step_outputs:
            return None

        last_output = list(self.previous_step_outputs.values())[-1] if self.previous_step_outputs else None
        if not last_output:
            return None

        # Use the helper method to get the deepest content
        return self._get_deepest_step_content(last_output)  # type: ignore[return-value]

    def get_workflow_history(self, num_runs: Optional[int] = None) -> List[Tuple[str, str]]:
        """Get workflow conversation history as structured data for custom function steps

        Args:
            num_runs: Number of recent runs to include. If None, returns all available history.
        """
        if not self.workflow_session:
            return []

        return self.workflow_session.get_workflow_history(num_runs=num_runs)

    def get_workflow_history_context(self, num_runs: Optional[int] = None) -> Optional[str]:
        """Get formatted workflow conversation history context for custom function steps

        Args:
            num_runs: Number of recent runs to include. If None, returns all available history.
        """
        if not self.workflow_session:
            return None

        return self.workflow_session.get_workflow_history_context(num_runs=num_runs)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        # Handle the unified message field
        input_dict: Optional[Union[str, Dict[str, Any], List[Any]]] = None
        if self.input is not None:
            if isinstance(self.input, BaseModel):
                input_dict = self.input.model_dump(exclude_none=True, mode="json")
            elif isinstance(self.input, (dict, list)):
                input_dict = self.input
            else:
                input_dict = str(self.input)

        previous_step_content_str: Optional[str] = None
        # Handle previous_step_content (keep existing logic)
        if isinstance(self.previous_step_content, BaseModel):
            previous_step_content_str = self.previous_step_content.model_dump_json(indent=2, exclude_none=True)
        elif isinstance(self.previous_step_content, dict):
            import json

            previous_step_content_str = json.dumps(self.previous_step_content, indent=2, default=str)
        elif self.previous_step_content:
            previous_step_content_str = str(self.previous_step_content)

        # Convert previous_step_outputs to serializable format (keep existing logic)
        previous_steps_dict = {}
        if self.previous_step_outputs:
            for step_name, output in self.previous_step_outputs.items():
                previous_steps_dict[step_name] = output.to_dict()

        return {
            "input": input_dict,
            "previous_step_outputs": previous_steps_dict,
            "previous_step_content": previous_step_content_str,
            "additional_data": self.additional_data,
            "images": [img.to_dict() for img in self.images] if self.images else None,
            "videos": [vid.to_dict() for vid in self.videos] if self.videos else None,
            "audio": [aud.to_dict() for aud in self.audio] if self.audio else None,
            "files": [file.to_dict() for file in self.files] if self.files else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepInput":
        """Create StepInput from dictionary"""
        # Reconstruct media artifacts
        images = reconstruct_images(data.get("images"))
        videos = reconstruct_videos(data.get("videos"))
        audio = reconstruct_audio_list(data.get("audio"))
        files = reconstruct_files(data.get("files"))

        # Reconstruct previous_step_outputs
        previous_step_outputs = None
        if data.get("previous_step_outputs"):
            previous_step_outputs = {
                name: StepOutput.from_dict(output_data) for name, output_data in data["previous_step_outputs"].items()
            }

        return cls(
            input=data.get("input"),
            previous_step_content=data.get("previous_step_content"),
            previous_step_outputs=previous_step_outputs,
            additional_data=data.get("additional_data"),
            images=images,
            videos=videos,
            audio=audio,
            files=files,
        )


@dataclass
class StepOutput:
    """Output data from a step execution"""

    step_name: Optional[str] = None
    step_id: Optional[str] = None
    step_type: Optional[str] = None
    executor_type: Optional[str] = None
    executor_name: Optional[str] = None
    # Primary output
    content: Optional[Union[str, Dict[str, Any], List[Any], BaseModel, Any]] = None

    # Link to the run ID of the step execution
    step_run_id: Optional[str] = None

    # Media outputs
    images: Optional[List[Image]] = None
    videos: Optional[List[Video]] = None
    audio: Optional[List[Audio]] = None
    files: Optional[List[File]] = None

    # Metrics for this step execution
    metrics: Optional[RunMetrics] = None

    success: bool = True
    error: Optional[str] = None

    stop: bool = False

    # Executor HITL: indicates the step's agent/team is paused for tool-level HITL
    is_paused: bool = False

    steps: Optional[List["StepOutput"]] = None

    # Loop iteration review: signals the workflow to pause for per-iteration review.
    # This is a transient flag — NOT serialized. It is cleared after the workflow
    # processes it.
    requires_iteration_review_pause: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        # Handle the unified content field
        content_dict: Optional[Union[str, Dict[str, Any], List[Any]]] = None
        if self.content is not None:
            if isinstance(self.content, BaseModel):
                content_dict = self.content.model_dump(exclude_none=True, mode="json")
            elif isinstance(self.content, (dict, list)):
                content_dict = self.content
            else:
                content_dict = str(self.content)

        result = {
            "content": content_dict,
            "step_name": self.step_name,
            "step_id": self.step_id,
            "step_type": self.step_type,
            "executor_type": self.executor_type,
            "executor_name": self.executor_name,
            "step_run_id": self.step_run_id,
            "images": [img.to_dict() for img in self.images] if self.images else None,
            "videos": [vid.to_dict() for vid in self.videos] if self.videos else None,
            "audio": [aud.to_dict() for aud in self.audio] if self.audio else None,
            "files": [f.to_dict() for f in self.files] if self.files else None,
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "success": self.success,
            "error": self.error,
            "stop": self.stop,
            "is_paused": self.is_paused,
        }

        # Add nested steps if they exist
        if self.steps:
            result["steps"] = [step.to_dict() if hasattr(step, "to_dict") else step for step in self.steps]

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepOutput":
        """Create StepOutput from dictionary"""
        # Reconstruct media artifacts
        images = reconstruct_images(data.get("images"))
        videos = reconstruct_videos(data.get("videos"))
        audio = reconstruct_audio_list(data.get("audio"))
        files = reconstruct_files(data.get("files"))

        metrics_data = data.get("metrics")
        metrics = None
        if metrics_data:
            if isinstance(metrics_data, dict):
                metrics = RunMetrics.from_dict(metrics_data)
            else:
                metrics = metrics_data

        # Handle nested steps
        steps_data = data.get("steps")
        steps = None
        if steps_data:
            steps = [cls.from_dict(step_data) for step_data in steps_data]

        return cls(
            step_name=data.get("step_name"),
            step_id=data.get("step_id"),
            step_type=data.get("step_type"),
            executor_type=data.get("executor_type"),
            executor_name=data.get("executor_name"),
            content=data.get("content"),
            step_run_id=data.get("step_run_id"),
            images=images,
            videos=videos,
            audio=audio,
            files=files,
            metrics=metrics,
            success=data.get("success", True),
            error=data.get("error"),
            stop=data.get("stop", False),
            is_paused=data.get("is_paused", False),
            steps=steps,
        )


@dataclass
class StepMetrics:
    """Metrics for a single step execution"""

    step_name: str
    executor_type: str  # "agent", "team", etc.
    executor_name: str
    metrics: Optional[RunMetrics] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "step_name": self.step_name,
            "executor_type": self.executor_type,
            "executor_name": self.executor_name,
            "metrics": self.metrics.to_dict() if self.metrics else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepMetrics":
        """Create StepMetrics from dictionary"""

        # Handle metrics properly
        metrics_data = data.get("metrics")
        metrics = None
        if metrics_data:
            if isinstance(metrics_data, dict):
                metrics = RunMetrics.from_dict(metrics_data)
            else:
                metrics = metrics_data

        return cls(
            step_name=data["step_name"],
            executor_type=data["executor_type"],
            executor_name=data["executor_name"],
            metrics=metrics,
        )


@dataclass
class WorkflowMetrics:
    """Complete metrics for a workflow execution"""

    steps: Dict[str, StepMetrics]
    # Timer utility for tracking execution time
    timer: Optional[Timer] = None
    # Total workflow execution time
    duration: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        result: Dict[str, Any] = {
            "steps": {name: step.to_dict() for name, step in self.steps.items()},
            "duration": self.duration,
        }
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowMetrics":
        """Create WorkflowMetrics from dictionary"""
        steps = {name: StepMetrics.from_dict(step_data) for name, step_data in data["steps"].items()}

        return cls(
            steps=steps,
            duration=data.get("duration"),
        )

    def start_timer(self):
        if self.timer is None:
            self.timer = Timer()
        self.timer.start()

    def stop_timer(self, set_duration: bool = True):
        if self.timer is not None:
            self.timer.stop()
            if set_duration:
                self.duration = self.timer.elapsed


class StepType(str, Enum):
    FUNCTION = "Function"
    STEP = "Step"
    STEPS = "Steps"
    LOOP = "Loop"
    PARALLEL = "Parallel"
    CONDITION = "Condition"
    ROUTER = "Router"
    WORKFLOW = "Workflow"


class ExecutorType(str, Enum):
    """Type of executor that raises executor-level HITL pauses inside a Step.

    Only agent/team executors can bubble tool-level HITL up to the workflow;
    nested workflows and plain functions are not covered by this enum.
    """

    AGENT = "agent"
    TEAM = "team"


class PauseKind(str, Enum):
    """Kind of HITL pause currently active on a WorkflowRunOutput."""

    STEP = "step"
    EXECUTOR = "executor"


@dataclass
class UserInputField:
    """A field that requires user input.

    Attributes:
        name: The field name (used as the key in user input).
        field_type: The expected type ("str", "int", "float", "bool", "list", "dict").
        description: Optional description shown to the user.
        value: The value provided by the user (set after input).
        required: Whether this field is required.
        allowed_values: Optional list of allowed values for validation.
    """

    name: str
    field_type: str  # "str", "int", "float", "bool", "list", "dict"
    description: Optional[str] = None
    value: Optional[Any] = None
    required: bool = True
    allowed_values: Optional[List[Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "name": self.name,
            "field_type": self.field_type,
            "description": self.description,
            "value": self.value,
            "required": self.required,
        }
        if self.allowed_values is not None:
            result["allowed_values"] = self.allowed_values
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserInputField":
        return cls(
            name=data["name"],
            field_type=data.get("field_type", "str"),
            description=data.get("description"),
            value=data.get("value"),
            required=data.get("required", True),
            allowed_values=data.get("allowed_values"),
        )


@dataclass
class StepRequirement:
    """Unified requirement for all HITL (Human-in-the-Loop) workflow pauses.

    This class handles three types of HITL scenarios:
    1. **Confirmation**: User confirms or rejects execution (Step, Loop, Condition, Steps, Router)
    2. **User Input**: User provides custom input values (Step with user_input_schema)
    3. **Route Selection**: User selects which route(s) to take (Router with requires_user_input)

    The `step_type` field indicates what kind of component created this requirement.
    It accepts both StepType enum values and strings for flexibility.

    The `on_reject` field determines behavior when a step is rejected:
    - OnReject.skip / "skip": Skip the step and continue workflow
    - OnReject.cancel / "cancel": Cancel the entire workflow
    - OnReject.else_branch / "else": For Condition only, execute else_steps
    """

    step_id: str
    step_name: Optional[str] = None
    step_index: Optional[int] = None

    # Component type that created this requirement
    # Accepts StepType enum or string for flexibility
    step_type: Optional[Union[StepType, str]] = None

    # Confirmation fields (for Step, Loop, Condition, Steps, Router confirmation mode)
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None
    confirmed: Optional[bool] = None
    # What to do when step is rejected
    # Accepts OnReject enum or string for flexibility
    on_reject: Union[OnReject, str] = OnReject.cancel

    # User input fields (for Step with custom input)
    requires_user_input: bool = False
    user_input_message: Optional[str] = None
    user_input_schema: Optional[List[UserInputField]] = None
    user_input: Optional[Dict[str, Any]] = None  # The actual user input values

    # Route selection fields (for Router user selection mode)
    requires_route_selection: bool = False
    available_choices: Optional[List[str]] = None  # Available route names
    allow_multiple_selections: bool = False  # If True, user can select multiple routes
    selected_choices: Optional[List[str]] = None  # User's selected route(s)

    # The step input that was prepared before pausing
    step_input: Optional["StepInput"] = None

    # Executor HITL fields (for agent/team tool-level pauses within a step)
    requires_executor_input: bool = False
    executor_requirements: Optional[List[Any]] = None  # List of RunRequirement dicts
    executor_id: Optional[str] = None
    executor_name: Optional[str] = None
    executor_run_id: Optional[str] = None
    executor_type: Optional[Union[ExecutorType, str]] = None  # "agent" or "team"
    # Session ID for the executor's session (needed for DB-based continue_run)
    executor_session_id: Optional[str] = None

    # Post-execution output review fields
    requires_output_review: bool = False
    output_review_message: Optional[str] = None
    step_output: Optional["StepOutput"] = None  # The executed output available for review
    is_post_execution: bool = False  # True when this is a post-execution pause (step already ran)

    # Rejection feedback (used with OnReject.retry to provide context to the agent)
    rejection_feedback: Optional[str] = None

    # Edited output (human modifies step output before continuing)
    edited_output: Optional[Any] = None

    # Retry tracking
    retry_count: int = 0
    max_retries: Optional[int] = None

    # Timeout / expiration
    timeout_at: Optional[datetime] = None
    on_timeout: Union[OnTimeout, str] = OnTimeout.cancel

    def confirm(self) -> None:
        """Confirm the step execution."""
        self.confirmed = True

    def reject(self, feedback: Optional[str] = None) -> None:
        """Reject the step execution.

        Args:
            feedback: Optional feedback explaining why the step was rejected.
                      When used with on_reject=OnReject.retry, this feedback
                      is passed to the agent on the next attempt.
        """
        self.confirmed = False
        if feedback is not None:
            self.rejection_feedback = feedback

    def edit(self, new_output: Any) -> None:
        """Accept the step with modifications.

        Marks the step as confirmed but replaces the step output with
        the human-provided content before continuing the workflow.

        Args:
            new_output: The modified output to use instead of the original step output.
        """
        self.confirmed = True
        self.edited_output = new_output

    def set_user_input(self, validate: bool = True, **kwargs) -> None:
        """Set user input values.

        Args:
            validate: Whether to validate the input against the schema. Defaults to True.
            **kwargs: The user input values as key-value pairs.

        Raises:
            ValueError: If validation is enabled and required fields are missing,
                        or if field types don't match the schema.
        """
        if self.user_input is None:
            self.user_input = {}
        self.user_input.update(kwargs)

        # Also update the schema values if present
        if self.user_input_schema:
            for field in self.user_input_schema:
                if field.name in kwargs:
                    field.value = kwargs[field.name]

        # Validate if schema is present and validation is enabled
        if validate and self.user_input_schema:
            self._validate_user_input(kwargs)

    def _validate_user_input(self, user_input: Dict[str, Any]) -> None:
        """Validate user input against the schema.

        Args:
            user_input: The user input values to validate.

        Raises:
            ValueError: If required fields are missing or types don't match.
        """
        if not self.user_input_schema:
            return

        errors = []

        for field in self.user_input_schema:
            value = user_input.get(field.name)

            # Check required fields
            if field.required and (value is None or value == ""):
                errors.append(f"Required field '{field.name}' is missing or empty")
                continue

            # Skip type validation if value is not provided (and not required)
            if value is None:
                continue

            # Validate type
            expected_type = field.field_type
            if expected_type == "str" and not isinstance(value, str):
                errors.append(f"Field '{field.name}' expected str, got {type(value).__name__}")
            elif expected_type == "int":
                if not isinstance(value, int) or isinstance(value, bool):
                    errors.append(f"Field '{field.name}' expected int, got {type(value).__name__}")
            elif expected_type == "float":
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    errors.append(f"Field '{field.name}' expected float, got {type(value).__name__}")
            elif expected_type == "bool" and not isinstance(value, bool):
                errors.append(f"Field '{field.name}' expected bool, got {type(value).__name__}")

            # Validate allowed values if specified
            if field.allowed_values and value not in field.allowed_values:
                errors.append(f"Field '{field.name}' value '{value}' is not in allowed values: {field.allowed_values}")

        if errors:
            raise ValueError("User input validation failed:\n  - " + "\n  - ".join(errors))

    def get_user_input(self, field_name: str) -> Optional[Any]:
        """Get a specific user input value"""
        if self.user_input:
            return self.user_input.get(field_name)
        return None

    # Route selection methods (for Router)
    def select(self, *choices: str) -> None:
        """Select one or more route choices by name."""
        if not self.allow_multiple_selections and len(choices) > 1:
            raise ValueError("This router only allows single selection. Use select() with one choice.")
        self.selected_choices = list(choices)

    def select_single(self, choice: str) -> None:
        """Select a single route choice by name."""
        self.selected_choices = [choice]

    def select_multiple(self, choices: List[str]) -> None:
        """Select multiple route choices by name."""
        if not self.allow_multiple_selections:
            raise ValueError("This router does not allow multiple selections.")
        self.selected_choices = choices

    @property
    def needs_confirmation(self) -> bool:
        """Check if this requirement still needs confirmation (excludes output review)"""
        if self.confirmed is not None:
            return False
        # Output review uses requires_confirmation internally but should not
        # appear in the confirmation-specific list
        if self.requires_output_review:
            return False
        return self.requires_confirmation

    @property
    def needs_output_review(self) -> bool:
        """Check if this requirement still needs output review"""
        if self.confirmed is not None:
            return False
        return self.requires_output_review

    @property
    def is_timed_out(self) -> bool:
        """Check if this requirement has exceeded its timeout."""
        if self.timeout_at is None:
            return False
        return datetime.now(timezone.utc) >= self.timeout_at

    @property
    def needs_user_input(self) -> bool:
        """Check if this requirement still needs user input"""
        if not self.requires_user_input:
            return False
        if self.user_input_schema:
            # Check if all required fields have values
            for field in self.user_input_schema:
                if field.required and field.value is None:
                    return True
            return False
        # If no schema, check if user_input dict has any values
        return self.user_input is None or len(self.user_input) == 0

    @property
    def needs_route_selection(self) -> bool:
        """Check if this requirement still needs route selection"""
        if not self.requires_route_selection:
            return False
        return self.selected_choices is None or len(self.selected_choices) == 0

    @property
    def needs_executor_resolution(self) -> bool:
        """Check if this requirement needs executor (agent/team) HITL resolution.

        True while any of the underlying RunRequirements are still unresolved.
        """
        if not self.requires_executor_input or not self.executor_requirements:
            return False

        from agno.run.requirement import RunRequirement

        for req in self.executor_requirements:
            if isinstance(req, dict):
                parsed = RunRequirement.from_dict(req)
                if not parsed.is_resolved():
                    return True
            elif isinstance(req, RunRequirement):
                if not req.is_resolved():
                    return True
            else:
                # Unknown shape — treat conservatively as unresolved.
                return True
        return False

    @property
    def is_resolved(self) -> bool:
        """Check if this requirement has been resolved"""
        if self.requires_confirmation and self.confirmed is None:
            return False
        if self.requires_output_review and self.confirmed is None:
            return False
        if self.requires_user_input and self.needs_user_input:
            return False
        if self.requires_route_selection and self.needs_route_selection:
            return False
        if self.requires_executor_input and self.needs_executor_resolution:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        # Convert enum values to strings for serialization
        step_type_str = self.step_type.value if isinstance(self.step_type, StepType) else self.step_type
        on_reject_str = self.on_reject.value if isinstance(self.on_reject, OnReject) else self.on_reject

        result: Dict[str, Any] = {
            "step_id": self.step_id,
            "step_name": self.step_name,
            "step_index": self.step_index,
            "step_type": step_type_str,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_message": self.confirmation_message,
            "confirmed": self.confirmed,
            "on_reject": on_reject_str,
            "requires_user_input": self.requires_user_input,
            "user_input_message": self.user_input_message,
            "user_input": self.user_input,
            "requires_route_selection": self.requires_route_selection,
            "available_choices": self.available_choices,
            "allow_multiple_selections": self.allow_multiple_selections,
            "selected_choices": self.selected_choices,
            # Post-execution output review
            "requires_output_review": self.requires_output_review,
            "output_review_message": self.output_review_message,
            "is_post_execution": self.is_post_execution,
            # Rejection feedback
            "rejection_feedback": self.rejection_feedback,
            # Retry tracking
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            # Timeout
            "timeout_at": self.timeout_at.isoformat() if self.timeout_at else None,
            "on_timeout": self.on_timeout.value if isinstance(self.on_timeout, OnTimeout) else self.on_timeout,
        }
        if self.user_input_schema is not None:
            result["user_input_schema"] = [f.to_dict() for f in self.user_input_schema]
        if self.step_input is not None:
            result["step_input"] = self.step_input.to_dict()

        # Executor HITL fields
        if self.requires_executor_input:
            result["requires_executor_input"] = self.requires_executor_input
            result["executor_requirements"] = self.executor_requirements
            result["executor_id"] = self.executor_id
            result["executor_name"] = self.executor_name
            result["executor_run_id"] = self.executor_run_id
            result["executor_type"] = (
                self.executor_type.value if isinstance(self.executor_type, ExecutorType) else self.executor_type
            )
            result["executor_session_id"] = self.executor_session_id

        if self.step_output is not None:
            result["step_output"] = self.step_output.to_dict()
        if self.edited_output is not None:
            if isinstance(self.edited_output, BaseModel):
                result["edited_output"] = self.edited_output.model_dump(exclude_none=True, mode="json")
            elif isinstance(self.edited_output, (dict, list)):
                result["edited_output"] = self.edited_output
            else:
                result["edited_output"] = str(self.edited_output)
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepRequirement":
        """Create StepRequirement from dictionary"""
        step_input = None
        if data.get("step_input"):
            step_input = StepInput.from_dict(data["step_input"])

        user_input_schema = None
        if data.get("user_input_schema"):
            user_input_schema = [UserInputField.from_dict(f) for f in data["user_input_schema"]]

        step_output = None
        if data.get("step_output"):
            step_output = StepOutput.from_dict(data["step_output"])

        timeout_at = None
        if data.get("timeout_at"):
            raw = data["timeout_at"]
            # Replace 'Z' suffix with '+00:00' for Python < 3.11 compatibility
            if isinstance(raw, str) and raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            timeout_at = datetime.fromisoformat(raw)

        return cls(
            step_id=data["step_id"],
            step_name=data.get("step_name"),
            step_index=data.get("step_index"),
            step_type=data.get("step_type"),
            requires_confirmation=data.get("requires_confirmation", False),
            confirmation_message=data.get("confirmation_message"),
            confirmed=data.get("confirmed"),
            on_reject=data.get("on_reject", "cancel"),
            requires_user_input=data.get("requires_user_input", False),
            user_input_message=data.get("user_input_message"),
            user_input_schema=user_input_schema,
            user_input=data.get("user_input"),
            requires_route_selection=data.get("requires_route_selection", False),
            available_choices=data.get("available_choices"),
            allow_multiple_selections=data.get("allow_multiple_selections", False),
            selected_choices=data.get("selected_choices"),
            step_input=step_input,
            requires_executor_input=data.get("requires_executor_input", False),
            executor_requirements=data.get("executor_requirements"),
            executor_id=data.get("executor_id"),
            executor_name=data.get("executor_name"),
            executor_run_id=data.get("executor_run_id"),
            executor_type=data.get("executor_type"),
            executor_session_id=data.get("executor_session_id"),
            # Post-execution output review
            requires_output_review=data.get("requires_output_review", False),
            output_review_message=data.get("output_review_message"),
            step_output=step_output,
            is_post_execution=data.get("is_post_execution", False),
            # Rejection feedback
            rejection_feedback=data.get("rejection_feedback"),
            # Edited output
            edited_output=data.get("edited_output"),
            # Retry tracking
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries"),
            # Timeout
            timeout_at=timeout_at,
            on_timeout=data.get("on_timeout", "cancel"),
        )


@dataclass
class ErrorRequirement:
    """Requirement to handle a step error (used for error-based HITL flows).

    When a Step has `on_error="pause"` and encounters an exception,
    the workflow pauses and creates this requirement. The user can
    decide to retry the step or skip it and continue with the next step.
    """

    step_id: str
    step_name: Optional[str] = None
    step_index: Optional[int] = None

    # Error information
    error_message: str = ""
    error_type: Optional[str] = None  # e.g., "ValueError", "TimeoutError"
    retry_count: int = 0  # How many times this step has been retried

    # User's decision: "retry" or "skip"
    decision: Optional[str] = None

    # The step input that was used when the error occurred
    step_input: Optional["StepInput"] = None

    def retry(self) -> None:
        """Retry the failed step."""
        self.decision = "retry"

    def skip(self) -> None:
        """Skip the failed step and continue with the next step."""
        self.decision = "skip"

    @property
    def needs_decision(self) -> bool:
        """Check if this requirement still needs a user decision."""
        return self.decision is None

    @property
    def is_resolved(self) -> bool:
        """Check if this requirement has been resolved."""
        return self.decision is not None

    @property
    def should_retry(self) -> bool:
        """Check if the user decided to retry."""
        return self.decision == "retry"

    @property
    def should_skip(self) -> bool:
        """Check if the user decided to skip."""
        return self.decision == "skip"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        # Note: We intentionally don't serialize step_input to avoid circular reference issues
        # The step_input will be reconstructed when resuming the workflow
        return {
            "step_id": self.step_id,
            "step_name": self.step_name,
            "step_index": self.step_index,
            "error_message": self.error_message,
            "error_type": self.error_type,
            "retry_count": self.retry_count,
            "decision": self.decision,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ErrorRequirement":
        """Create ErrorRequirement from dictionary."""
        # Note: step_input is not serialized/deserialized to avoid circular reference issues
        return cls(
            step_id=data["step_id"],
            step_name=data.get("step_name"),
            step_index=data.get("step_index"),
            error_message=data.get("error_message", ""),
            error_type=data.get("error_type"),
            retry_count=data.get("retry_count", 0),
            decision=data.get("decision"),
        )
