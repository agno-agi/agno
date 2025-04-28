from dataclasses import asdict, dataclass, field
from enum import Enum
from time import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from agno.media import AudioArtifact, AudioResponse, ImageArtifact, VideoArtifact
from agno.models.message import Citations, Message, MessageReferences
from agno.reasoning.step import ReasoningStep


class RunEvent(str, Enum):
    """Events that can be sent by the run() functions"""

    run_started = "RunStarted"
    run_response = "RunResponse"
    run_completed = "RunCompleted"
    run_error = "RunError"
    run_cancelled = "RunCancelled"
    tool_call_started = "ToolCallStarted"
    tool_call_completed = "ToolCallCompleted"
    reasoning_started = "ReasoningStarted"
    reasoning_step = "ReasoningStep"
    reasoning_completed = "ReasoningCompleted"
    updating_memory = "UpdatingMemory"
    workflow_started = "WorkflowStarted"
    workflow_completed = "WorkflowCompleted"


@dataclass
class RunResponseExtraData:
    references: Optional[List[MessageReferences]] = None
    add_messages: Optional[List[Message]] = None
    reasoning_steps: Optional[List[ReasoningStep]] = None
    reasoning_messages: Optional[List[Message]] = None

    def to_dict(self) -> Dict[str, Any]:
        _dict = {}
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
        add_messages = [Message.model_validate(message) for message in add_messages] if add_messages else None

        history = data.pop("history", None)
        history = [Message.model_validate(message) for message in history] if history else None

        reasoning_steps = data.pop("reasoning_steps", None)
        reasoning_steps = [ReasoningStep.model_validate(step) for step in reasoning_steps] if reasoning_steps else None

        reasoning_messages = data.pop("reasoning_messages", None)
        reasoning_messages = (
            [Message.model_validate(message) for message in reasoning_messages] if reasoning_messages else None
        )

        references = data.pop("references", None)
        references = [MessageReferences.model_validate(reference) for reference in references] if references else None

        return cls(
            add_messages=add_messages,
            reasoning_steps=reasoning_steps,
            reasoning_messages=reasoning_messages,
            references=references,
        )


@dataclass
class RunResponse:
    """Response returned by Agent.run() or Workflow.run() functions"""

    content: Optional[Any] = None
    content_type: str = "str"
    thinking: Optional[str] = None
    reasoning_content: Optional[str] = None
    event: str = RunEvent.run_response.value
    messages: Optional[List[Message]] = None
    metrics: Optional[Dict[str, Any]] = None
    model: Optional[str] = None
    run_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    workflow_id: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    formatted_tool_calls: Optional[List[str]] = None
    images: Optional[List[ImageArtifact]] = None  # Images attached to the response
    videos: Optional[List[VideoArtifact]] = None  # Videos attached to the response
    audio: Optional[List[AudioArtifact]] = None  # Audio attached to the response
    response_audio: Optional[AudioResponse] = None  # Model audio response
    citations: Optional[Citations] = None
    extra_data: Optional[RunResponseExtraData] = None
    created_at: int = field(default_factory=lambda: int(time()))

    def to_dict(self) -> Dict[str, Any]:
        _dict = {
            k: v
            for k, v in asdict(self).items()
            if v is not None
            and k not in ["messages", "extra_data", "images", "videos", "audio", "response_audio", "citations"]
        }
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
                    _dict["images"].append(img.model_dump(exclude_none=True))
                else:
                    _dict["images"].append(img)

        if self.videos is not None:
            _dict["videos"] = []
            for vid in self.videos:
                if isinstance(vid, VideoArtifact):
                    _dict["videos"].append(vid.model_dump(exclude_none=True))
                else:
                    _dict["videos"].append(vid)

        if self.audio is not None:
            _dict["audio"] = []
            for aud in self.audio:
                if isinstance(aud, AudioArtifact):
                    _dict["audio"].append(aud.model_dump(exclude_none=True))
                else:
                    _dict["audio"].append(aud)

        if self.response_audio is not None:
            _dict["response_audio"] = (
                self.response_audio.to_dict() if isinstance(self.response_audio, AudioResponse) else self.response_audio
            )

        if isinstance(self.content, BaseModel):
            _dict["content"] = self.content.model_dump(exclude_none=True)

        if self.citations is not None:
            _dict["citations"] = self.citations.model_dump(exclude_none=True)

        return _dict

    def to_json(self) -> str:
        import json

        _dict = self.to_dict()

        return json.dumps(_dict, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunResponse":
        messages = data.pop("messages", None)
        messages = [Message.model_validate(message) for message in messages] if messages else None

        return cls(messages=messages, **data)

    def get_content_as_string(self, **kwargs) -> str:
        import json

        from pydantic import BaseModel

        if isinstance(self.content, str):
            return self.content
        elif isinstance(self.content, BaseModel):
            return self.content.model_dump_json(exclude_none=True, **kwargs)
        else:
            return json.dumps(self.content, **kwargs)
