from dataclasses import dataclass
from enum import Enum
from time import time
from typing import Any, Dict, List, Optional

from agno.media import AudioOutput


class ModelResponseEvent(str, Enum):
    """Events that can be sent by the Model.response() method"""

    tool_call_started = "ToolCallStarted"
    tool_call_completed = "ToolCallCompleted"
    assistant_response = "AssistantResponse"


@dataclass
class ModelResponse:
    """Response returned by Model.response()"""

    content: Optional[str] = None
    parsed: Optional[Any] = None
    audio: Optional[AudioOutput] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    event: str = ModelResponseEvent.assistant_response.value
    created_at: int = int(time())


class FileType(str, Enum):
    MP4 = "mp4"
    GIF = "gif"
