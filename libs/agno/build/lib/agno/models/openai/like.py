from dataclasses import dataclass
from typing import Optional

from agno.models.openai.chat import OpenAIChat


@dataclass
class OpenAILike(OpenAIChat):
    id: str = "not-provided"
    name: str = "OpenAILike"
    api_key: Optional[str] = "not-provided"

    role_map = {
        "system": "system",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
    }
