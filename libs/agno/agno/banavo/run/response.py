"""
Custom Run Response types for Banavo.

Extends agno's base response types with Banavo-specific metadata and event structures.
Note: Standard events (RunStartedEvent, etc.) are now available in agno.run.agent.
This module provides Banavo-extended versions with additional agent/session context.
"""

from dataclasses import asdict, dataclass, field
from time import time
from typing import Any, Dict, List, Optional, Union

from agno.media import Audio as AudioArtifact, Audio as AudioResponse, Image as ImageArtifact, Video as VideoArtifact
from agno.models.message import Citations, Message, MessageReferences
from agno.models.response import ToolExecution
from agno.reasoning.step import ReasoningStep
from agno.run.base import BaseRunOutputEvent, RunStatus
from agno.utils.log import logger
from pydantic import BaseModel


@dataclass
class RunResponseExtraData:
    """Preserved locally — removed from agno 2.x."""

    references: Optional[List[MessageReferences]] = None
    add_messages: Optional[List[Message]] = None
    reasoning_steps: Optional[List[ReasoningStep]] = None
    reasoning_messages: Optional[List[Message]] = None

    def to_dict(self) -> Dict[str, Any]:
        _dict: Dict[str, Any] = {}
        if self.add_messages is not None:
            _dict["add_messages"] = [m.to_dict() for m in self.add_messages]
        if self.reasoning_messages is not None:
            _dict["reasoning_messages"] = [m.to_dict() for m in self.reasoning_messages]
        if self.reasoning_steps is not None:
            _dict["reasoning_steps"] = [rs.model_dump() for rs in self.reasoning_steps]
        if self.references is not None:
            _dict["references"] = [r.model_dump() for r in self.references]
        return _dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunResponseExtraData":
        add_messages = data.pop("add_messages", None)
        if add_messages is not None:
            add_messages = [Message.model_validate(m) for m in add_messages]
        reasoning_steps = data.pop("reasoning_steps", None)
        if reasoning_steps is not None:
            reasoning_steps = [ReasoningStep.model_validate(s) for s in reasoning_steps]
        reasoning_messages = data.pop("reasoning_messages", None)
        if reasoning_messages is not None:
            reasoning_messages = [Message.model_validate(m) for m in reasoning_messages]
        references = data.pop("references", None)
        if references is not None:
            references = [MessageReferences.model_validate(r) for r in references]
        return cls(
            add_messages=add_messages,
            reasoning_steps=reasoning_steps,
            reasoning_messages=reasoning_messages,
            references=references,
        )


@dataclass
class BaseAgentRunResponseEvent(BaseRunOutputEvent):
    """Banavo-extended base event with agent/session context."""

    created_at: int = field(default_factory=lambda: int(time()))
    event: str = ""
    agent_id: str = ""
    agent_name: str = ""
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    team_session_id: Optional[str] = None

    # For backwards compatibility
    content: Optional[Any] = None


@dataclass
class ArtifactPublishedEvent(BaseAgentRunResponseEvent):
    """Banavo-specific: Event for artifact publication."""

    event_type: str = "artifact_initiated"
    request_id: str = ""
    artifact_id: str = ""
    artifact_name: str = ""
    artifact_type: str = ""
    artifact_subtype: str = ""


@dataclass
class ArtifactPublishFailureEvent(BaseAgentRunResponseEvent):
    """Banavo-specific: Event for artifact publication failures."""

    event_type: str = "artifact_publish_failure"
    request_id: str = ""
    artifact_id: str = ""
    artifact_name: str = ""
    artifact_type: str = ""
    artifact_subtype: str = ""
    error_message: str = ""


# Banavo-extended event classes - wrap agno events with agent/session context
@dataclass
class RunResponseStartedEvent(BaseAgentRunResponseEvent):
    """Event sent when the run starts - Banavo version with agent context."""

    event: str = "RunStarted"
    model: str = ""
    model_provider: str = ""


@dataclass
class RunResponseContentEvent(BaseAgentRunResponseEvent):
    """Main event for each delta of the RunResponse - Banavo version."""

    event: str = "RunResponseContent"
    content: Optional[Any] = None
    content_type: str = "str"
    thinking: Optional[str] = None
    citations: Optional[Citations] = None
    response_audio: Optional[AudioResponse] = None  # Model audio response
    image: Optional[ImageArtifact] = None  # Image attached to the response
    extra_data: Optional[RunResponseExtraData] = None


@dataclass
class RunResponseCompletedEvent(BaseAgentRunResponseEvent):
    """Event sent when run completes - Banavo version."""

    event: str = "RunCompleted"
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
    """Event sent when run is paused - Banavo version."""

    event: str = "RunPaused"
    tools: Optional[List[ToolExecution]] = None

    @property
    def is_paused(self):
        return True


@dataclass
class RunResponseContinuedEvent(BaseAgentRunResponseEvent):
    """Event sent when paused run continues - Banavo version."""

    event: str = "RunContinued"


@dataclass
class RunResponseErrorEvent(BaseAgentRunResponseEvent):
    """Event sent on error - Banavo version."""

    event: str = "RunError"
    content: Optional[str] = None


@dataclass
class RunResponseCancelledEvent(BaseAgentRunResponseEvent):
    """Event sent when run is cancelled - Banavo version."""

    event: str = "RunCancelled"
    reason: Optional[str] = None

    @property
    def is_cancelled(self):
        return True


@dataclass
class MemoryUpdateStartedEvent(BaseAgentRunResponseEvent):
    """Event sent when memory update starts - Banavo version."""

    event: str = "MemoryUpdateStarted"


@dataclass
class MemoryUpdateCompletedEvent(BaseAgentRunResponseEvent):
    """Event sent when memory update completes - Banavo version."""

    event: str = "MemoryUpdateCompleted"


@dataclass
class ReasoningStartedEvent(BaseAgentRunResponseEvent):
    """Event sent when reasoning starts - Banavo version."""

    event: str = "ReasoningStarted"


@dataclass
class ReasoningStepEvent(BaseAgentRunResponseEvent):
    """Event sent for each reasoning step - Banavo version."""

    event: str = "ReasoningStep"
    content: Optional[Any] = None
    content_type: str = "str"
    reasoning_content: str = ""


@dataclass
class ReasoningCompletedEvent(BaseAgentRunResponseEvent):
    """Event sent when reasoning completes - Banavo version."""

    event: str = "ReasoningCompleted"
    content: Optional[Any] = None
    content_type: str = "str"


@dataclass
class ToolCallStartedEvent(BaseAgentRunResponseEvent):
    """Event sent when tool call starts - Banavo version."""

    event: str = "ToolCallStarted"
    tool: Optional[ToolExecution] = None


@dataclass
class ToolCallCompletedEvent(BaseAgentRunResponseEvent):
    """Event sent when tool call completes - Banavo version."""

    event: str = "ToolCallCompleted"
    tool: Optional[ToolExecution] = None
    content: Optional[Any] = None
    images: Optional[List[ImageArtifact]] = None  # Images produced by the tool call
    videos: Optional[List[VideoArtifact]] = None  # Videos produced by the tool call
    audio: Optional[List[AudioArtifact]] = None  # Audio produced by the tool call


@dataclass
class ParserModelResponseStartedEvent(BaseAgentRunResponseEvent):
    """Event sent when parser model response starts - Banavo version."""

    event: str = "ParserModelResponseStarted"


@dataclass
class ParserModelResponseCompletedEvent(BaseAgentRunResponseEvent):
    """Event sent when parser model response completes - Banavo version."""

    event: str = "ParserModelResponseCompleted"


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
    ParserModelResponseStartedEvent,
    ParserModelResponseCompletedEvent,
    ArtifactPublishedEvent,
]


def run_response_event_from_dict(data: dict) -> BaseRunOutputEvent:
    """Deserialize event from dict."""
    event_type = data.get("event", "")

    # Map event type string to class
    event_map = {
        "RunStarted": RunResponseStartedEvent,
        "RunResponseContent": RunResponseContentEvent,
        "RunCompleted": RunResponseCompletedEvent,
        "RunError": RunResponseErrorEvent,
        "RunCancelled": RunResponseCancelledEvent,
        "RunPaused": RunResponsePausedEvent,
        "RunContinued": RunResponseContinuedEvent,
        "ReasoningStarted": ReasoningStartedEvent,
        "ReasoningStep": ReasoningStepEvent,
        "ReasoningCompleted": ReasoningCompletedEvent,
        "MemoryUpdateStarted": MemoryUpdateStartedEvent,
        "MemoryUpdateCompleted": MemoryUpdateCompletedEvent,
        "ToolCallStarted": ToolCallStartedEvent,
        "ToolCallCompleted": ToolCallCompletedEvent,
        "ParserModelResponseStarted": ParserModelResponseStartedEvent,
        "ParserModelResponseCompleted": ParserModelResponseCompletedEvent,
        "ArtifactPublished": ArtifactPublishedEvent,
    }

    cls = event_map.get(event_type)
    if not cls:
        raise ValueError(f"Unknown event type: {event_type}")
    return cls.from_dict(data)  # type: ignore


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
    agent_name: Optional[str] = None
    session_id: Optional[str] = None
    team_session_id: Optional[str] = None
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

    events: Optional[List[RunResponseEvent]] = None

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
            and k
            not in [
                "messages",
                "tools",
                "extra_data",
                "images",
                "videos",
                "audio",
                "response_audio",
                "citations",
                "events",
            ]
        }

        if self.events is not None:
            _dict["events"] = [e.to_dict() for e in self.events]

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
        events = data.pop("events", None)
        events = [run_response_event_from_dict(event) for event in events] if events else None

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

        return cls(
            messages=messages,
            tools=tools,
            images=images,
            audio=audio,
            videos=videos,
            response_audio=response_audio,
            events=events,
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
