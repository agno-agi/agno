from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from agno.media import AudioArtifact, AudioResponse, ImageArtifact, VideoArtifact
from agno.models.message import Citations, Message, MessageReferences
from agno.models.response import ToolExecution
from agno.reasoning.step import ReasoningStep
from agno.utils.log import log_error


@dataclass
class BaseRunResponseEvent:
    def to_dict(self) -> Dict[str, Any]:
        _dict = {
            k: v
            for k, v in asdict(self).items()
            if v is not None
            and k
            not in [
                "tools",
                "tool",
                "extra_data",
                "image",
                "images",
                "videos",
                "audio",
                "response_audio",
                "citations",
                "member_responses",
            ]
        }

        if hasattr(self, "extra_data") and self.extra_data is not None:
            _dict["extra_data"] = (
                self.extra_data.to_dict() if isinstance(self.extra_data, RunResponseExtraData) else self.extra_data
            )

        if hasattr(self, "member_responses") and self.member_responses:
            _dict["member_responses"] = [response.to_dict() for response in self.member_responses]

        if hasattr(self, "images") and self.images is not None:
            _dict["images"] = []
            for img in self.images:
                if isinstance(img, ImageArtifact):
                    _dict["images"].append(img.to_dict())
                else:
                    _dict["images"].append(img)

        if hasattr(self, "image") and self.image is not None:
            if isinstance(self.image, ImageArtifact):
                _dict["image"] = self.image.to_dict()
            else:
                _dict["image"] = self.image

        if hasattr(self, "videos") and self.videos is not None:
            _dict["videos"] = []
            for vid in self.videos:
                if isinstance(vid, VideoArtifact):
                    _dict["videos"].append(vid.to_dict())
                else:
                    _dict["videos"].append(vid)

        if hasattr(self, "audio") and self.audio is not None:
            _dict["audio"] = []
            for aud in self.audio:
                if isinstance(aud, AudioArtifact):
                    _dict["audio"].append(aud.to_dict())
                else:
                    _dict["audio"].append(aud)

        if hasattr(self, "response_audio") and self.response_audio is not None:
            if isinstance(self.response_audio, AudioResponse):
                _dict["response_audio"] = self.response_audio.to_dict()
            else:
                _dict["response_audio"] = self.response_audio

        if hasattr(self, "citations") and self.citations is not None:
            if isinstance(self.citations, Citations):
                _dict["citations"] = self.citations.model_dump(exclude_none=True)
            else:
                _dict["citations"] = self.citations

        if hasattr(self, "content") and self.content and isinstance(self.content, BaseModel):
            _dict["content"] = self.content.model_dump(exclude_none=True)

        if hasattr(self, "tools") and self.tools is not None:
            _dict["tools"] = []
            for tool in self.tools:
                if isinstance(tool, ToolExecution):
                    _dict["tools"].append(tool.to_dict())
                else:
                    _dict["tools"].append(tool)

        if hasattr(self, "tool") and self.tool is not None:
            if isinstance(self.tool, ToolExecution):
                _dict["tool"] = self.tool.to_dict()
            else:
                _dict["tool"] = self.tool

        return _dict

    def to_json(self) -> str:
        import json

        try:
            _dict = self.to_dict()
        except Exception:
            log_error("Failed to convert response event to json", exc_info=True)
            raise

        return json.dumps(_dict, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        tool = data.pop("tool", None)
        if tool:
            data["tool"] = ToolExecution.from_dict(tool)

        images = data.pop("images", None)
        if images:
            data["images"] = [ImageArtifact.model_validate(image) for image in images]

        image = data.pop("image", None)
        if image:
            data["image"] = ImageArtifact.model_validate(image)

        videos = data.pop("videos", None)
        if videos:
            data["videos"] = [VideoArtifact.model_validate(video) for video in videos]

        audio = data.pop("audio", None)
        if audio:
            data["audio"] = [AudioArtifact.model_validate(audio) for audio in audio]

        response_audio = data.pop("response_audio", None)
        if response_audio:
            data["response_audio"] = AudioResponse.model_validate(response_audio)

        extra_data = data.pop("extra_data", None)
        if extra_data:
            data["extra_data"] = RunResponseExtraData.from_dict(extra_data)

        # To make it backwards compatible
        if "event" in data:
            data.pop("event")

        return cls(**data)

    @property
    def is_paused(self):
        return False

    @property
    def is_cancelled(self):
        return False


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
        if add_messages is not None:
            add_messages = [Message.model_validate(message) for message in add_messages]

        reasoning_steps = data.pop("reasoning_steps", None)
        if reasoning_steps is not None:
            reasoning_steps = [ReasoningStep.model_validate(step) for step in reasoning_steps]

        reasoning_messages = data.pop("reasoning_messages", None)
        if reasoning_messages is not None:
            reasoning_messages = [Message.model_validate(message) for message in reasoning_messages]

        references = data.pop("references", None)
        if references is not None:
            references = [MessageReferences.model_validate(reference) for reference in references]

        return cls(
            add_messages=add_messages,
            reasoning_steps=reasoning_steps,
            reasoning_messages=reasoning_messages,
            references=references,
        )


class RunStatus(str, Enum):
    """State of the main run response"""

    running = "RUNNING"
    paused = "PAUSED"
    cancelled = "CANCELLED"
    error = "ERROR"
