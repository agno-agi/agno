from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any, Dict, List, Optional

from agno.media import AudioOutput


class ModelResponseEvent(str, Enum):
    """Events that can be sent by the model provider"""

    tool_call_started = "ToolCallStarted"
    tool_call_completed = "ToolCallCompleted"
    assistant_response = "AssistantResponse"


@dataclass
class ModelResponse:
    """Response from the model provider"""

    role: Optional[str] = None
    content: Optional[str] = None
    parsed: Optional[Any] = None
    audio: Optional[AudioOutput] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    response_usage: Optional[Any] = None
    extra: Optional[Dict[str, Any]] = field(default_factory=dict)
    event: str = ModelResponseEvent.assistant_response.value
    created_at: int = int(time())


@dataclass
class ProviderResponse:
    """Response parsed from the response that the model provider returns"""

    role: Optional[str] = None
    content: Optional[str] = None
    parsed: Optional[Any] = None
    audio: Optional[AudioOutput] = None
    tool_calls: Optional[List[Dict[str, Any]]] = field(default_factory=list)
    response_usage: Optional[Any] = None

    extra: Optional[Dict[str, Any]] = field(default_factory=dict)


class FileType(str, Enum):
    MP4 = "mp4"
    GIF = "gif"
