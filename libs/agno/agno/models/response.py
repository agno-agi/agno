from dataclasses import asdict, dataclass, field
from enum import Enum
from time import time
from typing import Any, Dict, List, Optional

from agno.media import Audio, File, Image, Video
from agno.metrics import ToolCallMetrics
from agno.models.message import Citations
from agno.models.metrics import MessageMetrics
from agno.tools.function import UserFeedbackQuestion, UserInputField


class ModelResponseEvent(str, Enum):
    """Events that can be sent by the model provider"""

    tool_call_paused = "ToolCallPaused"
    tool_call_started = "ToolCallStarted"
    tool_call_completed = "ToolCallCompleted"
    assistant_response = "AssistantResponse"
    compression_started = "CompressionStarted"
    compression_completed = "CompressionCompleted"
    model_request_started = "ModelRequestStarted"
    model_request_completed = "ModelRequestCompleted"


@dataclass
class ToolExecution:
    """Execution of a tool"""

    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_call_error: Optional[bool] = None
    result: Optional[str] = None
    metrics: Optional[ToolCallMetrics] = None

    # In the case where a tool call creates a run of an agent/team/workflow
    child_run_id: Optional[str] = None

    # If True, the agent will stop executing after this tool call.
    stop_after_tool_call: bool = False

    created_at: int = field(default_factory=lambda: int(time()))

    # User control flow (HITL) fields
    requires_confirmation: Optional[bool] = None
    confirmed: Optional[bool] = None
    confirmation_note: Optional[str] = None

    requires_user_input: Optional[bool] = None
    user_input_schema: Optional[List[UserInputField]] = None
    user_feedback_schema: Optional[List[UserFeedbackQuestion]] = None
    answered: Optional[bool] = None

    external_execution_required: Optional[bool] = None

    # If True (and external_execution_required=True), suppresses verbose paused messages
    external_execution_silent: Optional[bool] = None

    # Approval type: "required" (blocking) or "audit" (non-blocking audit trail).
    approval_type: Optional[str] = None

    @property
    def is_paused(self) -> bool:
        return bool(self.requires_confirmation or self.requires_user_input or self.external_execution_required)

    def to_dict(self) -> Dict[str, Any]:
        _dict = asdict(self)
        if self.metrics is not None:
            _dict["metrics"] = self.metrics.to_dict()

        if self.user_input_schema is not None:
            _dict["user_input_schema"] = [field.to_dict() for field in self.user_input_schema]

        if self.user_feedback_schema is not None:
            _dict["user_feedback_schema"] = [q.to_dict() for q in self.user_feedback_schema]

        return _dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolExecution":
        return cls(
            tool_call_id=data.get("tool_call_id"),
            tool_name=data.get("tool_name"),
            tool_args=data.get("tool_args"),
            tool_call_error=data.get("tool_call_error"),
            result=data.get("result"),
            child_run_id=data.get("child_run_id"),
            stop_after_tool_call=data.get("stop_after_tool_call", False),
            requires_confirmation=data.get("requires_confirmation"),
            confirmed=data.get("confirmed"),
            confirmation_note=data.get("confirmation_note"),
            requires_user_input=data.get("requires_user_input"),
            user_input_schema=[UserInputField.from_dict(field) for field in data.get("user_input_schema") or []]
            if "user_input_schema" in data
            else None,
            user_feedback_schema=[UserFeedbackQuestion.from_dict(q) for q in data.get("user_feedback_schema") or []]
            if "user_feedback_schema" in data
            else None,
            external_execution_required=data.get("external_execution_required"),
            external_execution_silent=data.get("external_execution_silent"),
            approval_type=data.get("approval_type"),
            metrics=ToolCallMetrics.from_dict(data["metrics"]) if data.get("metrics") else None,
            **{"created_at": data["created_at"]} if "created_at" in data else {},
        )


@dataclass
class ModelResponse:
    """Response from the model provider"""

    role: Optional[str] = None

    content: Optional[Any] = None
    parsed: Optional[Any] = None
    audio: Optional[Audio] = None

    # Unified media fields for LLM-generated and tool-generated media artifacts
    images: Optional[List[Image]] = None
    videos: Optional[List[Video]] = None
    audios: Optional[List[Audio]] = None
    files: Optional[List[File]] = None

    # Model tool calls
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    # Actual tool executions
    tool_executions: Optional[List[ToolExecution]] = field(default_factory=list)

    event: str = ModelResponseEvent.assistant_response.value

    provider_data: Optional[Dict[str, Any]] = None

    redacted_reasoning_content: Optional[str] = None
    reasoning_content: Optional[str] = None

    citations: Optional[Citations] = None

    response_usage: Optional[MessageMetrics] = None

    created_at: int = int(time())

    extra: Optional[Dict[str, Any]] = None

    updated_session_state: Optional[Dict[str, Any]] = None

    # Compression stats
    compression_stats: Optional[Dict[str, Any]] = None

    # Model request metrics (for model_request_completed events)
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    time_to_first_token: Optional[float] = None
    reasoning_tokens: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    cache_write_tokens: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize ModelResponse to dictionary for caching."""
        _dict = asdict(self)

        # Handle special serialization for audio
        if self.audio is not None:
            _dict["audio"] = self.audio.to_dict()

        # Handle lists of media objects
        if self.images is not None:
            _dict["images"] = [img.to_dict() for img in self.images]
        if self.videos is not None:
            _dict["videos"] = [vid.to_dict() for vid in self.videos]
        if self.audios is not None:
            _dict["audios"] = [aud.to_dict() for aud in self.audios]
        if self.files is not None:
            _dict["files"] = [f.to_dict() for f in self.files]

        # Handle tool executions
        if self.tool_executions is not None:
            _dict["tool_executions"] = [tool_execution.to_dict() for tool_execution in self.tool_executions]

        # Handle response usage which might be a Pydantic BaseModel
        response_usage = _dict.pop("response_usage", None)
        if response_usage is not None:
            try:
                from pydantic import BaseModel

                if isinstance(response_usage, BaseModel):
                    _dict["response_usage"] = response_usage.model_dump()
                else:
                    _dict["response_usage"] = response_usage
            except ImportError:
                _dict["response_usage"] = response_usage

        return _dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelResponse":
        """Reconstruct ModelResponse from cached dictionary."""
        # Reconstruct media objects
        if data.get("audio"):
            data["audio"] = Audio(**data["audio"])

        if data.get("images"):
            data["images"] = [Image(**img) for img in data["images"]]
        if data.get("videos"):
            data["videos"] = [Video(**vid) for vid in data["videos"]]
        if data.get("audios"):
            data["audios"] = [Audio(**aud) for aud in data["audios"]]
        if data.get("files"):
            data["files"] = [File(**f) for f in data["files"]]

        # Reconstruct tool executions
        if data.get("tool_executions"):
            data["tool_executions"] = [ToolExecution.from_dict(te) for te in data["tool_executions"]]

        # Reconstruct citations
        if data.get("citations") and isinstance(data["citations"], dict):
            data["citations"] = Citations(**data["citations"])

        # Reconstruct response usage (Metrics)
        if data.get("response_usage") and isinstance(data["response_usage"], dict):
            from agno.models.metrics import MessageMetrics as _MessageMetrics

            data["response_usage"] = _MessageMetrics.from_dict(data["response_usage"])

        return cls(**data)


class FileType(str, Enum):
    MP4 = "mp4"
    GIF = "gif"
    MP3 = "mp3"
    WAV = "wav"
