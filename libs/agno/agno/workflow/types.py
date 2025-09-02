from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from fastapi import WebSocket
from pydantic import BaseModel

from agno.media import AudioArtifact, File, ImageArtifact, VideoArtifact
from agno.models.metrics import Metrics
from agno.utils.log import log_warning


@dataclass
class WorkflowExecutionInput:
    """Input data for a step execution"""

    input: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None

    additional_data: Optional[Dict[str, Any]] = None

    # Media inputs
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None
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
        }


@dataclass
class StepInput:
    """Input data for a step execution"""

    input: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None

    previous_step_content: Optional[Any] = None
    previous_step_outputs: Optional[Dict[str, "StepOutput"]] = None

    additional_data: Optional[Dict[str, Any]] = None

    # Media inputs
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None
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

    def get_step_output(self, step_name: str) -> Optional["StepOutput"]:
        """Get output from a specific previous step by name"""
        if not self.previous_step_outputs:
            return None
        return self.previous_step_outputs.get(step_name)

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

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        # Handle the unified message field
        input_dict: Optional[Union[str, Dict[str, Any], List[Any]]] = None
        if self.input is not None:
            if isinstance(self.input, BaseModel):
                input_dict = self.input.model_dump(exclude_none=True)
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
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None
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
                content_dict = self.content.model_dump(exclude_none=True)
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
        images = data.get("images")
        if images:
            images = [ImageArtifact.model_validate(img) for img in images]

        videos = data.get("videos")
        if videos:
            videos = [VideoArtifact.model_validate(vid) for vid in videos]

        audio = data.get("audio")
        if audio:
            audio = [AudioArtifact.model_validate(aud) for aud in audio]

        files = data.get("files")
        if files:
            files = [File.model_validate(file) for file in files]

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

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "steps": {name: step.to_dict() for name, step in self.steps.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowMetrics":
        """Create WorkflowMetrics from dictionary"""
        steps = {name: StepMetrics.from_dict(step_data) for name, step_data in data["steps"].items()}

        return cls(
            steps=steps,
        )


@dataclass
class WebSocketHandler:
    """Generic WebSocket handler for real-time workflow events"""

    websocket: Optional[WebSocket] = None

    def format_sse_event(self, json_data: str) -> str:
        """Parse JSON data into SSE-compliant format.

        Args:
            json_data: JSON string containing the event data

        Returns:
            SSE-formatted response with event type and data
        """
        import json

        try:
            # Parse the JSON to extract the event type
            data = json.loads(json_data)
            event_type = data.get("event", "message")

            # Format as SSE: event: <event_type>\ndata: <json_data>\n\n
            return f"event: {event_type}\ndata: {json_data}\n\n"
        except (json.JSONDecodeError, KeyError):
            # Fallback to generic message event if parsing fails
            return f"event: message\ndata: {json_data}\n\n"

    async def handle_event(self, event: Any) -> None:
        """Handle an event object - serializes and sends via WebSocket"""
        if not self.websocket:
            return

        try:
            if hasattr(event, "to_dict"):
                data = event.to_dict()
            elif hasattr(event, "__dict__"):
                data = event.__dict__
            elif isinstance(event, dict):
                data = event
            else:
                data = {"type": "message", "content": str(event)}

            import json

            await self.websocket.send_text(self.format_sse_event(json.dumps(data)))

        except Exception as e:
            log_warning(f"Failed to handle WebSocket event: {e}")

    async def handle_text(self, message: str) -> None:
        """Handle a plain text message"""
        if not self.websocket:
            return

        try:
            await self.websocket.send_text(self.format_sse_event(message))
        except Exception as e:
            log_warning(f"Failed to send WebSocket text: {e}")

    async def handle_dict(self, data: Dict[str, Any]) -> None:
        """Handle a dictionary directly"""
        if not self.websocket:
            return

        try:
            import json

            await self.websocket.send_text(self.format_sse_event(json.dumps(data)))
        except Exception as e:
            log_warning(f"Failed to send WebSocket dict: {e}")


class StepType(str, Enum):
    FUNCTION = "Function"
    STEP = "Step"
    STEPS = "Steps"
    LOOP = "Loop"
    PARALLEL = "Parallel"
    CONDITION = "Condition"
    ROUTER = "Router"
