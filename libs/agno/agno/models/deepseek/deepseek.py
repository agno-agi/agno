from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.models.openai.like import OpenAILike


@dataclass
class DeepSeek(OpenAILike):
    """
    A class for interacting with DeepSeek models.

    For more information, see: https://api-docs.deepseek.com/
    """

    id: str = "deepseek-chat"
    name: str = "DeepSeek"
    provider: str = "DeepSeek"

    api_key: Optional[str] = getenv("DEEPSEEK_API_KEY", None)
    base_url: str = "https://api.deepseek.com"

    # Their support for structured outputs is currently broken
    supports_native_structured_outputs: bool = False
