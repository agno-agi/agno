from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.metrics import Metrics
from agno.session.workflow import WorkflowSession
from agno.utils.media import (
    reconstruct_audio_list,
    reconstruct_files,
    reconstruct_images,
    reconstruct_videos,
)
from agno.utils.timer import Timer


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
            "files": [file for file in self.files] if self.files else None,
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
    metrics: Optional[Metrics] = None

    success: bool = True
    error: Optional[str] = None

    stop: bool = False

    steps: Optional[List["StepOutput"]] = None

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
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "success": self.success,
            "error": self.error,
            "stop": self.stop,
            "files": [file for file in self.files] if self.files else None,
        }

        # Add nested steps if they exist
        if self.steps:
            result["steps"] = [step.to_dict() for step in self.steps]

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
                # Convert dict to Metrics object
                from agno.models.metrics import Metrics

                metrics = Metrics(**metrics_data)
            else:
                # Already a Metrics object
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
            steps=steps,
        )


@dataclass
class StepMetrics:
    """Metrics for a single step execution"""

    step_name: str
    executor_type: str  # "agent", "team", etc.
    executor_name: str
    metrics: Optional[Metrics] = None

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
                # Convert dict to Metrics object
                from agno.models.metrics import Metrics

                metrics = Metrics(**metrics_data)
            else:
                # Already a Metrics object
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


@dataclass
class UserInputField:
    """A field that requires user input"""

    name: str
    field_type: str  # "str", "int", "float", "bool", "list", "dict"
    description: Optional[str] = None
    value: Optional[Any] = None
    required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "field_type": self.field_type,
            "description": self.description,
            "value": self.value,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserInputField":
        return cls(
            name=data["name"],
            field_type=data.get("field_type", "str"),
            description=data.get("description"),
            value=data.get("value"),
            required=data.get("required", True),
        )


@dataclass
class StepRequirement:
    """Requirement to complete a paused step (used in step-level HITL flows)"""

    step_id: str
    step_name: Optional[str] = None
    step_index: Optional[int] = None

    # Confirmation fields
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None
    confirmed: Optional[bool] = None

    # User input fields
    requires_user_input: bool = False
    user_input_message: Optional[str] = None
    user_input_schema: Optional[List[UserInputField]] = None
    user_input: Optional[Dict[str, Any]] = None  # The actual user input values

    # The step input that was prepared before pausing
    step_input: Optional["StepInput"] = None

    def confirm(self) -> None:
        """Confirm the step execution"""
        self.confirmed = True

    def reject(self) -> None:
        """Reject the step execution"""
        self.confirmed = False

    def set_user_input(self, **kwargs) -> None:
        """Set user input values"""
        if self.user_input is None:
            self.user_input = {}
        self.user_input.update(kwargs)

        # Also update the schema values if present
        if self.user_input_schema:
            for field in self.user_input_schema:
                if field.name in kwargs:
                    field.value = kwargs[field.name]

    def get_user_input(self, field_name: str) -> Optional[Any]:
        """Get a specific user input value"""
        if self.user_input:
            return self.user_input.get(field_name)
        return None

    @property
    def needs_confirmation(self) -> bool:
        """Check if this requirement still needs confirmation"""
        if self.confirmed is not None:
            return False
        return self.requires_confirmation

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
    def is_resolved(self) -> bool:
        """Check if this requirement has been resolved"""
        if self.requires_confirmation and self.confirmed is None:
            return False
        if self.requires_user_input and self.needs_user_input:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        result = {
            "step_id": self.step_id,
            "step_name": self.step_name,
            "step_index": self.step_index,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_message": self.confirmation_message,
            "confirmed": self.confirmed,
            "requires_user_input": self.requires_user_input,
            "user_input_message": self.user_input_message,
            "user_input": self.user_input,
        }
        if self.user_input_schema is not None:
            result["user_input_schema"] = [f.to_dict() for f in self.user_input_schema]
        if self.step_input is not None:
            result["step_input"] = self.step_input.to_dict()
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

        return cls(
            step_id=data["step_id"],
            step_name=data.get("step_name"),
            step_index=data.get("step_index"),
            requires_confirmation=data.get("requires_confirmation", False),
            confirmation_message=data.get("confirmation_message"),
            confirmed=data.get("confirmed"),
            requires_user_input=data.get("requires_user_input", False),
            user_input_message=data.get("user_input_message"),
            user_input_schema=user_input_schema,
            user_input=data.get("user_input"),
            step_input=step_input,
        )


@dataclass
class RouterRequirement:
    """Requirement to complete a paused router (used for user-driven routing decisions).

    When a Router has `requires_user_input=True`, it pauses and creates this requirement.
    The user selects which route(s) to take from the available choices.
    """

    router_id: str
    router_name: Optional[str] = None

    # User input for route selection
    requires_user_input: bool = True
    user_input_message: Optional[str] = None
    user_input_schema: Optional[List[UserInputField]] = None

    # Available choices (step names)
    available_choices: Optional[List[str]] = None
    allow_multiple_selections: bool = False

    # User's selection
    selected_choices: Optional[List[str]] = None

    # The step input at the time of pausing
    step_input: Optional["StepInput"] = None

    def select(self, *choices: str) -> None:
        """Select one or more choices by name."""
        if not self.allow_multiple_selections and len(choices) > 1:
            raise ValueError("This router only allows single selection. Use select() with one choice.")
        self.selected_choices = list(choices)

    def select_single(self, choice: str) -> None:
        """Select a single choice by name."""
        self.selected_choices = [choice]

    def select_multiple(self, choices: List[str]) -> None:
        """Select multiple choices by name."""
        if not self.allow_multiple_selections:
            raise ValueError("This router does not allow multiple selections.")
        self.selected_choices = choices

    @property
    def needs_selection(self) -> bool:
        """Check if this requirement still needs user selection."""
        return self.selected_choices is None or len(self.selected_choices) == 0

    @property
    def is_resolved(self) -> bool:
        """Check if this requirement has been resolved."""
        return not self.needs_selection

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "router_id": self.router_id,
            "router_name": self.router_name,
            "requires_user_input": self.requires_user_input,
            "user_input_message": self.user_input_message,
            "available_choices": self.available_choices,
            "allow_multiple_selections": self.allow_multiple_selections,
            "selected_choices": self.selected_choices,
        }
        if self.user_input_schema is not None:
            result["user_input_schema"] = [f.to_dict() for f in self.user_input_schema]
        if self.step_input is not None:
            result["step_input"] = self.step_input.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RouterRequirement":
        """Create RouterRequirement from dictionary."""
        step_input = None
        if data.get("step_input"):
            step_input = StepInput.from_dict(data["step_input"])

        user_input_schema = None
        if data.get("user_input_schema"):
            user_input_schema = [UserInputField.from_dict(f) for f in data["user_input_schema"]]

        return cls(
            router_id=data["router_id"],
            router_name=data.get("router_name"),
            requires_user_input=data.get("requires_user_input", True),
            user_input_message=data.get("user_input_message"),
            user_input_schema=user_input_schema,
            available_choices=data.get("available_choices"),
            allow_multiple_selections=data.get("allow_multiple_selections", False),
            selected_choices=data.get("selected_choices"),
            step_input=step_input,
        )
