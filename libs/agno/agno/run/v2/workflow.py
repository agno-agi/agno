from dataclasses import asdict, dataclass, field
from enum import Enum
from time import time
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

from agno.media import AudioArtifact, AudioResponse, ImageArtifact, VideoArtifact
from agno.models.message import Message
from agno.run.base import RunStatus
from agno.utils.log import log_error


class WorkflowRunEvent(str, Enum):
    """Events that can be sent by workflow execution"""

    workflow_started = "WorkflowStarted"
    workflow_completed = "WorkflowCompleted"
    workflow_cancelled = "WorkflowCancelled"
    workflow_error = "WorkflowError"

    step_started = "StepStarted"
    step_completed = "StepCompleted"
    step_error = "StepError"


@dataclass
class BaseWorkflowRunResponseEvent:
    """Base class for all workflow run response events"""

    run_id: str
    created_at: int = field(default_factory=lambda: int(time()))
    event: str = ""

    # Workflow-specific fields
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None
    session_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        _dict = {k: v for k, v in asdict(self).items() if v is not None}

        if hasattr(self, "content") and self.content and isinstance(self.content, BaseModel):
            _dict["content"] = self.content.model_dump(exclude_none=True)

        return _dict

    def to_json(self) -> str:
        import json

        try:
            _dict = self.to_dict()
        except Exception:
            log_error("Failed to convert response to json", exc_info=True)
            raise

        return json.dumps(_dict, indent=2)

    @property
    def is_cancelled(self):
        return False

    @property
    def is_error(self):
        return False

    @property
    def status(self):
        status = "Completed"
        if self.is_error:
            status = "Error"
        if self.is_cancelled:
            status = "Cancelled"

        return status


@dataclass
class WorkflowStartedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when workflow execution starts"""

    event: str = WorkflowRunEvent.workflow_started.value


@dataclass
class WorkflowCompletedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when workflow execution completes"""

    event: str = WorkflowRunEvent.workflow_completed.value
    content: Optional[Any] = None
    content_type: str = "str"

    # Store actual step execution results as StepOutput objects
    step_responses: List["StepOutput"] = field(default_factory=list)  # noqa: F821
    extra_data: Optional[Dict[str, Any]] = None


@dataclass
class WorkflowErrorEvent(BaseWorkflowRunResponseEvent):
    """Event sent when workflow execution fails"""

    event: str = WorkflowRunEvent.workflow_error.value
    error: Optional[str] = None


@dataclass
class WorkflowCancelledEvent(BaseWorkflowRunResponseEvent):
    """Event sent when workflow execution is cancelled"""

    event: str = WorkflowRunEvent.workflow_cancelled.value
    reason: Optional[str] = None

    @property
    def is_cancelled(self):
        return True


@dataclass
class StepStartedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when step execution starts"""

    event: str = WorkflowRunEvent.step_started.value
    step_name: Optional[str] = None
    step_index: Optional[int] = None


@dataclass
class StepCompletedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when step execution completes"""

    event: str = WorkflowRunEvent.step_completed.value
    step_name: Optional[str] = None
    step_index: Optional[int] = None

    content: Optional[Any] = None
    content_type: str = "str"

    # Media content fields
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None
    response_audio: Optional[AudioResponse] = None

    # Store actual step execution results as StepOutput objects
    step_response: Optional["StepOutput"] = None  # noqa: F821


@dataclass
class StepErrorEvent(BaseWorkflowRunResponseEvent):
    """Event sent when step execution fails"""

    event: str = WorkflowRunEvent.step_error.value
    step_name: Optional[str] = None
    step_index: Optional[int] = None
    error: Optional[str] = None


# Union type for all workflow run response events
WorkflowRunResponseEvent = Union[
    WorkflowStartedEvent,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
    StepStartedEvent,
    StepCompletedEvent,
    StepErrorEvent,
]


@dataclass
class WorkflowRunResponse:
    """Response returned by Workflow.run() functions - kept for backwards compatibility"""

    content: Optional[Any] = None
    content_type: str = "str"
    messages: Optional[List[Message]] = None
    metrics: Optional[Dict[str, Any]] = None

    # Workflow-specific fields
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None

    run_id: Optional[str] = None
    session_id: Optional[str] = None

    # Media content fields
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None
    response_audio: Optional[AudioResponse] = None

    # Store actual step execution results as StepOutput objects
    step_responses: List[Union["StepOutput", List["StepOutput"]]] = field(default_factory=list)  # noqa: F821

    extra_data: Optional[Dict[str, Any]] = None
    created_at: int = field(default_factory=lambda: int(time()))

    status: RunStatus = RunStatus.pending

    @property
    def is_cancelled(self):
        return self.status == RunStatus.cancelled

    def to_dict(self) -> Dict[str, Any]:
        _dict = {
            k: v
            for k, v in asdict(self).items()
            if v is not None
            and k
            not in [
                "messages",
                "extra_data",
                "images",
                "videos",
                "audio",
                "response_audio",
                "step_responses",
            ]
        }

        if self.status is not None:
            _dict["status"] = self.status.value if isinstance(self.status, RunStatus) else self.status

        if self.messages is not None:
            _dict["messages"] = [m.to_dict() for m in self.messages]

        if self.extra_data is not None:
            _dict["extra_data"] = self.extra_data

        if self.images is not None:
            _dict["images"] = [img.to_dict() for img in self.images]

        if self.videos is not None:
            _dict["videos"] = [vid.to_dict() for vid in self.videos]

        if self.audio is not None:
            _dict["audio"] = [aud.to_dict() for aud in self.audio]

        if self.response_audio is not None:
            _dict["response_audio"] = self.response_audio.to_dict()

        if self.step_responses:
            _dict["step_responses"] = [step_output.to_dict() for step_output in self.step_responses]

        if self.content and isinstance(self.content, BaseModel):
            _dict["content"] = self.content.model_dump(exclude_none=True)

        return _dict

    def to_json(self) -> str:
        import json

        _dict = self.to_dict()
        return json.dumps(_dict, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowRunResponse":
        # Import here to avoid circular import
        from libs.agno.agno.workflow.v2.step import StepOutput

        messages = data.pop("messages", [])
        messages = [Message.model_validate(message) for message in messages] if messages else None

        step_responses = data.pop("step_responses", [])
        parsed_step_responses: List["StepOutput"] = []
        if step_responses:
            for step_output_dict in step_responses:
                # Reconstruct StepOutput from dict
                parsed_step_responses.append(StepOutput.from_dict(step_output_dict))

        extra_data = data.pop("extra_data", None)

        images = data.pop("images", [])
        images = [ImageArtifact.model_validate(image) for image in images] if images else None

        videos = data.pop("videos", [])
        videos = [VideoArtifact.model_validate(video) for video in videos] if videos else None

        audio = data.pop("audio", [])
        audio = [AudioArtifact.model_validate(audio) for audio in audio] if audio else None

        response_audio = data.pop("response_audio", None)
        response_audio = AudioResponse.model_validate(response_audio) if response_audio else None

        return cls(
            messages=messages,
            step_responses=parsed_step_responses,
            extra_data=extra_data,
            images=images,
            videos=videos,
            audio=audio,
            response_audio=response_audio,
            **data,
        )

    def get_content_as_string(self, **kwargs) -> str:
        import json

        from pydantic import BaseModel

        if isinstance(self.content, str):
            return self.content
        elif isinstance(self.content, BaseModel):
            return self.content.model_dump_json(exclude_none=True, **kwargs)
        else:
            return json.dumps(self.content, **kwargs)
