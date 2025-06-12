from dataclasses import asdict, dataclass, field
from enum import Enum
from time import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from pydantic import BaseModel

from agno.media import AudioArtifact, AudioResponse, ImageArtifact, VideoArtifact
from agno.models.message import Message
from agno.utils.log import log_error

if TYPE_CHECKING:
    from agno.workflow.v2.task import TaskOutput


class WorkflowRunEvent(str, Enum):
    """Events that can be sent by workflow execution"""

    workflow_started = "WorkflowStarted"
    workflow_completed = "WorkflowCompleted"
    workflow_error = "WorkflowError"

    task_started = "TaskStarted"
    task_completed = "TaskCompleted"
    task_error = "TaskError"


@dataclass
class BaseWorkflowRunResponseEvent:
    """Base class for all workflow run response events"""

    run_id: str
    created_at: int = field(default_factory=lambda: int(time()))
    event: str = ""

    # Workflow-specific fields
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None
    pipeline_name: Optional[str] = None
    task_name: Optional[str] = None
    task_index: Optional[int] = None
    session_id: Optional[str] = None

    # For backwards compatibility
    content: Optional[Any] = None

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

    # Store actual task execution results as TaskOutput objects
    task_responses: List["TaskOutput"] = field(default_factory=list)
    extra_data: Optional[Dict[str, Any]] = None


@dataclass
class WorkflowErrorEvent(BaseWorkflowRunResponseEvent):
    """Event sent when workflow execution fails"""

    event: str = WorkflowRunEvent.workflow_error.value
    error: Optional[str] = None


@dataclass
class TaskStartedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when task execution starts"""

    event: str = WorkflowRunEvent.task_started.value


@dataclass
class TaskCompletedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when task execution completes"""

    event: str = WorkflowRunEvent.task_completed.value
    content: Optional[Any] = None
    content_type: str = "str"

    # Media content fields
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None
    response_audio: Optional[AudioResponse] = None

    # Messages and metrics from task execution
    messages: Optional[List[Message]] = None
    metrics: Optional[Dict[str, Any]] = None

    # Store actual task execution results as TaskOutput objects
    task_responses: List["TaskOutput"] = field(default_factory=list)


@dataclass
class TaskErrorEvent(BaseWorkflowRunResponseEvent):
    """Event sent when task execution fails"""

    event: str = WorkflowRunEvent.task_error.value
    error: Optional[str] = None


# Union type for all workflow run response events
WorkflowRunResponseEvent = Union[
    WorkflowStartedEvent,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
    TaskStartedEvent,
    TaskCompletedEvent,
    TaskErrorEvent,
]


@dataclass
class WorkflowRunResponse:
    """Response returned by Workflow.run() functions - kept for backwards compatibility"""

    event: str = WorkflowRunEvent.task_completed.value

    content: Optional[Any] = None
    content_type: str = "str"
    messages: Optional[List[Message]] = None
    metrics: Optional[Dict[str, Any]] = None

    # Workflow-specific fields
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None
    pipeline_name: Optional[str] = None
    task_name: Optional[str] = None
    task_index: Optional[int] = None

    run_id: Optional[str] = None
    session_id: Optional[str] = None

    # Media content fields
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None
    response_audio: Optional[AudioResponse] = None

    # Store actual task execution results as TaskOutput objects
    task_responses: List["TaskOutput"] = field(default_factory=list)

    extra_data: Optional[Dict[str, Any]] = None
    created_at: int = field(default_factory=lambda: int(time()))

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
                "task_responses",
            ]
        }

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

        if self.task_responses:
            _dict["task_responses"] = [task_output.to_dict() for task_output in self.task_responses]

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
        from agno.workflow.v2.task import TaskOutput

        messages = data.pop("messages", None)
        messages = [Message.model_validate(message) for message in messages] if messages else None

        task_responses = data.pop("task_responses", None)
        parsed_task_responses: List["TaskOutput"] = []
        if task_responses is not None:
            for task_output_dict in task_responses:
                # Reconstruct TaskOutput from dict
                parsed_task_responses.append(TaskOutput.from_dict(task_output_dict))

        extra_data = data.pop("extra_data", None)

        images = data.pop("images", None)
        images = [ImageArtifact.model_validate(image) for image in images] if images else None

        videos = data.pop("videos", None)
        videos = [VideoArtifact.model_validate(video) for video in videos] if videos else None

        audio = data.pop("audio", None)
        audio = [AudioArtifact.model_validate(audio) for audio in audio] if audio else None

        response_audio = data.pop("response_audio", None)
        response_audio = AudioResponse.model_validate(response_audio) if response_audio else None

        return cls(
            messages=messages,
            task_responses=parsed_task_responses,
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
