from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

from agno.media import AudioArtifact, ImageArtifact, VideoArtifact
from agno.run.response import RunResponse
from agno.run.team import TeamRunResponse


@dataclass
class WorkflowExecutionInput:
    """Input data for a step execution"""

    message: Optional[str] = None
    message_data: Optional[Union[BaseModel, Dict[str, Any]]] = (None,)

    # Media inputs
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        message_data_dict = {}
        if isinstance(self.message_data, BaseModel):
            message_data_dict = self.message_data.model_dump(exclude_none=True)
        elif isinstance(self.message_data, dict):
            message_data_dict = self.message_data

        return {
            "message": self.message,
            "message_data": message_data_dict,
            "images": [img.to_dict() for img in self.images] if self.images else None,
            "videos": [vid.to_dict() for vid in self.videos] if self.videos else None,
            "audio": [aud.to_dict() for aud in self.audio] if self.audio else None,
        }


@dataclass
class StepInput:
    """Input data for a step execution"""

    message: Optional[str] = None
    message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None
    previous_step_content: Optional[Any] = None

    # Media inputs
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        message_data_dict = {}
        if isinstance(self.message_data, BaseModel):
            message_data_dict = self.message_data.model_dump(exclude_none=True)
        elif isinstance(self.message_data, dict):
            message_data_dict = self.message_data

        if isinstance(self.previous_step_content, BaseModel):
            previous_step_content_str = self.previous_step_content.model_dump_json(indent=2, exclude_none=True)
        elif isinstance(self.previous_step_content, dict):
            import json

            previous_step_content_str = json.dumps(self.previous_step_content, indent=2, default=str)
        else:
            previous_step_content_str = str(self.previous_step_content)

        return {
            "message": self.message,
            "message_data": message_data_dict,
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

    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "content": self.content,
            "response": self.response.to_dict() if self.response else None,
            "images": [img.to_dict() for img in self.images] if self.images else None,
            "videos": [vid.to_dict() for vid in self.videos] if self.videos else None,
            "audio": [aud.to_dict() for aud in self.audio] if self.audio else None,
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
            success=data.get("success", True),
            error=data.get("error"),
        )
