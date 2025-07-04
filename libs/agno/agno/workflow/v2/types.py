from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

from agno.media import AudioArtifact, ImageArtifact, VideoArtifact
from agno.run.response import RunResponse
from agno.run.team import TeamRunResponse


@dataclass
class WorkflowExecutionInput:
    """Input data for a step execution"""

    message: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None

    # Media inputs
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None

    def get_message_as_string(self) -> Optional[str]:
        """Convert message to string representation"""
        if self.message is None:
            return None

        if isinstance(self.message, str):
            return self.message
        elif isinstance(self.message, BaseModel):
            return self.message.model_dump_json(indent=2, exclude_none=True)
        elif isinstance(self.message, (dict, list)):
            import json

            return json.dumps(self.message, indent=2, default=str)
        else:
            return str(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        message_dict = None
        if self.message is not None:
            if isinstance(self.message, BaseModel):
                message_dict = self.message.model_dump(exclude_none=True)
            elif isinstance(self.message, (dict, list)):
                message_dict = self.message
            else:
                message_dict = str(self.message)

        return {
            "message": message_dict,
            "images": [img.to_dict() for img in self.images] if self.images else None,
            "videos": [vid.to_dict() for vid in self.videos] if self.videos else None,
            "audio": [aud.to_dict() for aud in self.audio] if self.audio else None,
        }


@dataclass
class StepInput:
    """Input data for a step execution"""

    message: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None

    previous_step_content: Optional[Any] = None
    previous_steps_outputs: Optional[Dict[str, "StepOutput"]] = None
    workflow_message: Optional[str] = None  # Original workflow message

    # Media inputs
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None

    def get_message_as_string(self) -> Optional[str]:
        """Convert message to string representation"""
        if self.message is None:
            return None

        if isinstance(self.message, str):
            return self.message
        elif isinstance(self.message, BaseModel):
            return self.message.model_dump_json(indent=2, exclude_none=True)
        elif isinstance(self.message, (dict, list)):
            import json

            return json.dumps(self.message, indent=2, default=str)
        else:
            return str(self.message)

    def get_step_output(self, step_name: str) -> Optional["StepOutput"]:
        """Get output from a specific previous step by name"""
        if not self.previous_steps_outputs:
            return None
        return self.previous_steps_outputs.get(step_name)

    def get_step_content(self, step_name: str) -> Optional[str]:
        """Get content from a specific previous step by name"""
        step_output = self.get_step_output(step_name)
        return step_output.content if step_output else None

    def get_all_previous_content(self) -> str:
        """Get concatenated content from all previous steps"""
        if not self.previous_steps_outputs:
            return ""

        content_parts = []
        for step_name, output in self.previous_steps_outputs.items():
            if output.content:
                content_parts.append(f"=== {step_name} ===\n{output.content}")

        return "\n\n".join(content_parts)

    def get_last_step_content(self) -> Optional[str]:
        """Get content from the most recent step (for backward compatibility)"""
        if not self.previous_steps_outputs:
            return None

        last_output = list(self.previous_steps_outputs.values())[-1] if self.previous_steps_outputs else None
        return last_output.content if last_output else None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        # Handle the unified message field
        message_dict = None
        if self.message is not None:
            if isinstance(self.message, BaseModel):
                message_dict = self.message.model_dump(exclude_none=True)
            elif isinstance(self.message, (dict, list)):
                message_dict = self.message
            else:
                message_dict = str(self.message)

        # Handle workflow_message (also updated to support all types)
        workflow_message_dict = None
        if self.workflow_message is not None:
            if isinstance(self.workflow_message, BaseModel):
                workflow_message_dict = self.workflow_message.model_dump(exclude_none=True)
            elif isinstance(self.workflow_message, (dict, list)):
                workflow_message_dict = self.workflow_message
            else:
                workflow_message_dict = str(self.workflow_message)

        # Handle previous_step_content (keep existing logic)
        if isinstance(self.previous_step_content, BaseModel):
            previous_step_content_str = self.previous_step_content.model_dump_json(indent=2, exclude_none=True)
        elif isinstance(self.previous_step_content, dict):
            import json

            previous_step_content_str = json.dumps(self.previous_step_content, indent=2, default=str)
        else:
            previous_step_content_str = str(self.previous_step_content) if self.previous_step_content else None

        # Convert previous_steps_outputs to serializable format (keep existing logic)
        previous_steps_dict = {}
        if self.previous_steps_outputs:
            for step_name, output in self.previous_steps_outputs.items():
                previous_steps_dict[step_name] = output.to_dict()

        return {
            "message": message_dict,
            "workflow_message": workflow_message_dict,
            "previous_steps_outputs": previous_steps_dict,
            "previous_step_content": previous_step_content_str,
            "images": [img.to_dict() for img in self.images] if self.images else None,
            "videos": [vid.to_dict() for vid in self.videos] if self.videos else None,
            "audio": [aud.to_dict() for aud in self.audio] if self.audio else None,
        }


@dataclass
class StepOutput:
    """Output data from a step execution"""

    step_name: Optional[str] = None
    step_id: Optional[str] = None
    executor_type: Optional[str] = None
    executor_name: Optional[str] = None

    # Primary output
    content: Optional[str] = None

    # Execution response
    response: Optional[Union[RunResponse, TeamRunResponse]] = None

    # Media outputs
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None

    # Metrics for this step execution
    metrics: Optional[Dict[str, Any]] = None

    success: bool = True
    error: Optional[str] = None

    stop: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "content": self.content,
            "response": self.response.to_dict() if self.response else None,
            "images": [img.to_dict() for img in self.images] if self.images else None,
            "videos": [vid.to_dict() for vid in self.videos] if self.videos else None,
            "audio": [aud.to_dict() for aud in self.audio] if self.audio else None,
            "metrics": self.metrics,
            "success": self.success,
            "error": self.error,
            "stop": self.stop,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepOutput":
        """Create StepOutput from dictionary"""
        from agno.run.response import RunResponse
        from agno.run.team import TeamRunResponse

        # Reconstruct response if present
        response_data = data.get("response")
        response = None
        if response_data:
            # Determine if it's RunResponse or TeamRunResponse based on structure
            if "team_id" in response_data or "team_name" in response_data:
                response = TeamRunResponse.from_dict(response_data)
            else:
                response = RunResponse.from_dict(response_data)

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

        return cls(
            content=data.get("content"),
            response=response,
            images=images,
            videos=videos,
            audio=audio,
            metrics=data.get("metrics"),
            success=data.get("success", True),
            error=data.get("error"),
            stop=data.get("stop", False),
        )


@dataclass
class StepMetrics:
    """Metrics for a single step execution"""

    step_name: str
    executor_type: str  # "agent", "team", etc.
    executor_name: str

    # For regular steps: actual metrics data
    metrics: Optional[Dict[str, Any]] = None

    # For parallel steps: nested step metrics
    parallel_steps: Optional[Dict[str, "StepMetrics"]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary - only include relevant fields"""
        result = {
            "step_name": self.step_name,
            "executor_type": self.executor_type,
            "executor_name": self.executor_name,
        }

        # Only include the relevant field based on executor type
        if self.executor_type == "parallel" and self.parallel_steps:
            result["parallel_steps"] = {name: step.to_dict() for name, step in self.parallel_steps.items()}
        elif self.executor_type != "parallel":
            # For non-parallel steps, include metrics (even if None)
            result["metrics"] = self.metrics

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepMetrics":
        """Create StepMetrics from dictionary"""

        # Parse nested parallel steps if they exist
        parallel_steps = None
        if "parallel_steps" in data and data["parallel_steps"] is not None:
            parallel_steps = {name: cls.from_dict(step_data) for name, step_data in data["parallel_steps"].items()}

        return cls(
            step_name=data["step_name"],
            executor_type=data["executor_type"],
            executor_name=data["executor_name"],
            metrics=data.get("metrics") if data.get("executor_type") != "parallel" else None,
            parallel_steps=parallel_steps,
        )


@dataclass
class WorkflowMetrics:
    """Complete metrics for a workflow execution"""

    total_steps: int
    steps: Dict[str, StepMetrics]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "total_steps": self.total_steps,
            "steps": {name: step.to_dict() for name, step in self.steps.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowMetrics":
        """Create WorkflowMetrics from dictionary"""
        steps = {name: StepMetrics.from_dict(step_data) for name, step_data in data["steps"].items()}

        return cls(
            total_steps=data["total_steps"],
            steps=steps,
        )
