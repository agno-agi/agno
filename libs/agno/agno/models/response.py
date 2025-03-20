from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any, Dict, List, Optional

from agno.media import AudioResponse
from agno.models.message import Citations


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
    audio: Optional[AudioResponse] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    event: str = ModelResponseEvent.assistant_response.value

    provider_data: Optional[Dict[str, Any]] = None

    thinking: Optional[str] = None
    redacted_thinking: Optional[str] = None
    reasoning_content: Optional[str] = None

    citations: Optional[Citations] = None

    response_usage: Optional[Any] = None

    created_at: int = int(time())

    extra: Optional[Dict[str, Any]] = None

    def format_tool_calls(self) -> List[str]:
        """Format tool calls for display in a readable format.

        Returns:
            List[str]: List of formatted tool call strings
        """
        formatted_tool_calls = []
        for tool_call in self.tool_calls:
            if "tool_name" in tool_call and "tool_args" in tool_call:
                tool_name = tool_call["tool_name"]
                args_str = ", ".join(f"{k}={v}" for k, v in tool_call["tool_args"].items())
                formatted_tool_calls.append(f"{tool_name}({args_str})")
        return formatted_tool_calls


class FileType(str, Enum):
    MP4 = "mp4"
    GIF = "gif"
    MP3 = "mp3"
