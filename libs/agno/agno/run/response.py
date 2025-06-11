from dataclasses import asdict, dataclass, field
from enum import Enum
from time import time
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

from agno.media import AudioArtifact, AudioResponse, ImageArtifact, VideoArtifact
from agno.models.message import Citations, Message
from agno.models.response import ToolExecution
from agno.run.base import BaseRunResponseEvent, RunResponseExtraData, RunStatus
from agno.utils.log import logger


class RunEvent(str, Enum):
    """Events that can be sent by the run() functions"""

    run_started = "RunStarted"
    run_response_content = "RunResponseContent"
    run_completed = "RunCompleted"
    run_error = "RunError"
    run_cancelled = "RunCancelled"

    run_paused = "RunPaused"
    run_continued = "RunContinued"

    tool_call_started = "ToolCallStarted"
    tool_call_completed = "ToolCallCompleted"

    reasoning_started = "ReasoningStarted"
    reasoning_step = "ReasoningStep"
    reasoning_completed = "ReasoningCompleted"

    memory_update_started = "MemoryUpdateStarted"
    memory_update_completed = "MemoryUpdateCompleted"


@dataclass
class BaseAgentRunResponseEvent(BaseRunResponseEvent):
    created_at: int = field(default_factory=lambda: int(time()))
    event: str = ""
    agent_id: str = ""
    run_id: Optional[str] = None
    session_id: Optional[str] = None

    # For backwards compatibility
    content: Optional[Any] = None


@dataclass
class RunResponseStartedEvent(BaseAgentRunResponseEvent):
    """Event sent when the run starts"""

    event: str = RunEvent.run_started.value
    model: str = ""
    model_provider: str = ""


@dataclass
class RunResponseContentEvent(BaseAgentRunResponseEvent):
    """Main event for each delta of the RunResponse"""

    event: str = RunEvent.run_response_content.value
    content: Optional[Any] = None
    content_type: str = "str"
    thinking: Optional[str] = None
    citations: Optional[Citations] = None
    response_audio: Optional[AudioResponse] = None  # Model audio response
    image: Optional[ImageArtifact] = None  # Image attached to the response
    extra_data: Optional[RunResponseExtraData] = None


@dataclass
class RunResponseCompletedEvent(BaseAgentRunResponseEvent):
    event: str = RunEvent.run_completed.value
    content: Optional[Any] = None
    content_type: str = "str"
    reasoning_content: Optional[str] = None
    thinking: Optional[str] = None
    citations: Optional[Citations] = None
    images: Optional[List[ImageArtifact]] = None  # Images attached to the response
    videos: Optional[List[VideoArtifact]] = None  # Videos attached to the response
    audio: Optional[List[AudioArtifact]] = None  # Audio attached to the response
    response_audio: Optional[AudioResponse] = None  # Model audio response
    extra_data: Optional[RunResponseExtraData] = None


@dataclass
class RunResponsePausedEvent(BaseAgentRunResponseEvent):
    event: str = RunEvent.run_paused.value
    tools: Optional[List[ToolExecution]] = None

    @property
    def is_paused(self):
        return True


@dataclass
class RunResponseContinuedEvent(BaseAgentRunResponseEvent):
    event: str = RunEvent.run_continued.value


@dataclass
class RunResponseErrorEvent(BaseAgentRunResponseEvent):
    event: str = RunEvent.run_error.value
    content: Optional[str] = None


@dataclass
class RunResponseCancelledEvent(BaseAgentRunResponseEvent):
    event: str = RunEvent.run_cancelled.value
    reason: Optional[str] = None

    @property
    def is_cancelled(self):
        return True


@dataclass
class MemoryUpdateStartedEvent(BaseAgentRunResponseEvent):
    event: str = RunEvent.memory_update_started.value


@dataclass
class MemoryUpdateCompletedEvent(BaseAgentRunResponseEvent):
    event: str = RunEvent.memory_update_completed.value


@dataclass
class ReasoningStartedEvent(BaseAgentRunResponseEvent):
    event: str = RunEvent.reasoning_started.value


@dataclass
class ReasoningStepEvent(BaseAgentRunResponseEvent):
    event: str = RunEvent.reasoning_step.value
    content: Optional[Any] = None
    content_type: str = "str"
    reasoning_content: str = ""


@dataclass
class ReasoningCompletedEvent(BaseAgentRunResponseEvent):
    event: str = RunEvent.reasoning_completed.value
    content: Optional[Any] = None
    content_type: str = "str"


@dataclass
class ToolCallStartedEvent(BaseAgentRunResponseEvent):
    event: str = RunEvent.tool_call_started.value
    tool: Optional[ToolExecution] = None


@dataclass
class ToolCallCompletedEvent(BaseAgentRunResponseEvent):
    event: str = RunEvent.tool_call_completed.value
    tool: Optional[ToolExecution] = None
    content: Optional[Any] = None
    images: Optional[List[ImageArtifact]] = None  # Images produced by the tool call
    videos: Optional[List[VideoArtifact]] = None  # Videos produced by the tool call
    audio: Optional[List[AudioArtifact]] = None  # Audio produced by the tool call


RunResponseEvent = Union[
    RunResponseStartedEvent,
    RunResponseContentEvent,
    RunResponseCompletedEvent,
    RunResponseErrorEvent,
    RunResponseCancelledEvent,
    RunResponsePausedEvent,
    RunResponseContinuedEvent,
    ReasoningStartedEvent,
    ReasoningStepEvent,
    ReasoningCompletedEvent,
    MemoryUpdateStartedEvent,
    MemoryUpdateCompletedEvent,
    ToolCallStartedEvent,
    ToolCallCompletedEvent,
]


@dataclass
class RunResponse:
    """Response returned by Agent.run() or Workflow.run() functions"""

    content: Optional[Any] = None
    content_type: str = "str"
    thinking: Optional[str] = None
    reasoning_content: Optional[str] = None
    messages: Optional[List[Message]] = None
    metrics: Optional[Dict[str, Any]] = None
    model: Optional[str] = None
    model_provider: Optional[str] = None
    run_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    workflow_id: Optional[str] = None
    tools: Optional[List[ToolExecution]] = None
    formatted_tool_calls: Optional[List[str]] = None
    images: Optional[List[ImageArtifact]] = None  # Images attached to the response
    videos: Optional[List[VideoArtifact]] = None  # Videos attached to the response
    audio: Optional[List[AudioArtifact]] = None  # Audio attached to the response
    response_audio: Optional[AudioResponse] = None  # Model audio response
    citations: Optional[Citations] = None
    extra_data: Optional[RunResponseExtraData] = None
    created_at: int = field(default_factory=lambda: int(time()))

    status: RunStatus = RunStatus.running

    @property
    def is_paused(self):
        return self.status == RunStatus.paused

    @property
    def is_cancelled(self):
        return self.status == RunStatus.cancelled

    @property
    def tools_requiring_confirmation(self):
        return [t for t in self.tools if t.requires_confirmation] if self.tools else []

    @property
    def tools_requiring_user_input(self):
        return [t for t in self.tools if t.requires_user_input] if self.tools else []

    @property
    def tools_awaiting_external_execution(self):
        return [t for t in self.tools if t.external_execution_required] if self.tools else []

    def to_dict(self) -> Dict[str, Any]:
        _dict = {
            k: v
            for k, v in asdict(self).items()
            if v is not None
            and k not in ["messages", "tools", "extra_data", "images", "videos", "audio", "response_audio", "citations"]
        }

        if self.status is not None:
            _dict["status"] = self.status.value if isinstance(self.status, RunStatus) else self.status

        if self.messages is not None:
            _dict["messages"] = [m.to_dict() for m in self.messages]

        if self.extra_data is not None:
            _dict["extra_data"] = (
                self.extra_data.to_dict() if isinstance(self.extra_data, RunResponseExtraData) else self.extra_data
            )

        if self.images is not None:
            _dict["images"] = []
            for img in self.images:
                if isinstance(img, ImageArtifact):
                    _dict["images"].append(img.to_dict())
                else:
                    _dict["images"].append(img)

        if self.videos is not None:
            _dict["videos"] = []
            for vid in self.videos:
                if isinstance(vid, VideoArtifact):
                    _dict["videos"].append(vid.to_dict())
                else:
                    _dict["videos"].append(vid)

        if self.audio is not None:
            _dict["audio"] = []
            for aud in self.audio:
                if isinstance(aud, AudioArtifact):
                    _dict["audio"].append(aud.to_dict())
                else:
                    _dict["audio"].append(aud)

        if self.response_audio is not None:
            if isinstance(self.response_audio, AudioResponse):
                _dict["response_audio"] = self.response_audio.to_dict()
            else:
                _dict["response_audio"] = self.response_audio

        if self.citations is not None:
            if isinstance(self.citations, Citations):
                _dict["citations"] = self.citations.model_dump(exclude_none=True)
            else:
                _dict["citations"] = self.citations

        if self.content and isinstance(self.content, BaseModel):
            _dict["content"] = self.content.model_dump(exclude_none=True, mode="json")

        if self.tools is not None:
            _dict["tools"] = []
            for tool in self.tools:
                if isinstance(tool, ToolExecution):
                    _dict["tools"].append(tool.to_dict())
                else:
                    _dict["tools"].append(tool)

        return _dict

    def to_json(self) -> str:
        import json

        try:
            _dict = self.to_dict()
        except Exception:
            logger.error("Failed to convert response to json", exc_info=True)
            raise

        return json.dumps(_dict, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunResponse":
        messages = data.pop("messages", None)
        messages = [Message.model_validate(message) for message in messages] if messages else None

        tools = data.pop("tools", None)
        tools = [ToolExecution.from_dict(tool) for tool in tools] if tools else None

        images = data.pop("images", None)
        images = [ImageArtifact.model_validate(image) for image in images] if images else None

        videos = data.pop("videos", None)
        videos = [VideoArtifact.model_validate(video) for video in videos] if videos else None

        audio = data.pop("audio", None)
        audio = [AudioArtifact.model_validate(audio) for audio in audio] if audio else None

        response_audio = data.pop("response_audio", None)
        response_audio = AudioResponse.model_validate(response_audio) if response_audio else None

        # To make it backwards compatible
        if "event" in data:
            data.pop("event")

        return cls(messages=messages, tools=tools, images=images, videos=videos, response_audio=response_audio, **data)

    def get_content_as_string(self, **kwargs) -> str:
        import json

        from pydantic import BaseModel

        if isinstance(self.content, str):
            return self.content
        elif isinstance(self.content, BaseModel):
            return self.content.model_dump_json(exclude_none=True, **kwargs)
        else:
            return json.dumps(self.content, **kwargs)
