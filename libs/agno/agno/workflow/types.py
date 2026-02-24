from dataclasses import dataclass
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
            "files": [f.to_dict() for f in self.files] if self.files else None,
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "success": self.success,
            "error": self.error,
            "stop": self.stop,
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
