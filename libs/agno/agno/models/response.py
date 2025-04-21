from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any, Dict, List, Optional

from agno.media import AudioResponse, ImageArtifact
from agno.models.message import Citations


class ModelResponseEvent(str, Enum):
    """Events that can be sent by the model provider"""

    tool_call_confirmation_required = "ToolCallConfirmationRequired"
    tool_call_external_execution_required = "ToolCallExternalExecutionRequired"
    tool_call_started = "ToolCallStarted"
    tool_call_completed = "ToolCallCompleted"
    assistant_response = "AssistantResponse"


@dataclass
class ToolExecution:
    """Execution of a tool"""

    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_call_error: Optional[bool] = None
    result: Optional[str] = None

    # If True, the agent will stop executing after this tool call.
    stop_after_tool_call: bool = False

    created_at: int = int(time())

    confirmation_required: Optional[bool] = None
    confirmed: Optional[bool] = None

    external_execution_required: Optional[bool] = None

@dataclass
class ModelResponse:
    """Response from the model provider"""

    role: Optional[str] = None

    content: Optional[str] = None
    parsed: Optional[Any] = None
    audio: Optional[AudioResponse] = None
    image: Optional[ImageArtifact] = None

    # Model tool calls
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    # Actual tool executions
    tool_executions: Optional[List[ToolExecution]] = field(default_factory=list)

    event: str = ModelResponseEvent.assistant_response.value

    provider_data: Optional[Dict[str, Any]] = None

    thinking: Optional[str] = None
    redacted_thinking: Optional[str] = None
    reasoning_content: Optional[str] = None

    citations: Optional[Citations] = None

    response_usage: Optional[Any] = None

    created_at: int = int(time())

    extra: Optional[Dict[str, Any]] = None


class FileType(str, Enum):
    MP4 = "mp4"
    GIF = "gif"
    MP3 = "mp3"
