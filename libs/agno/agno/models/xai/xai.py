from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import getenv
from typing import Iterator, List, Optional

from agno.exceptions import ModelProviderError
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.utils.log import log_error

try:
    from openai import APIConnectionError, APIStatusError, RateLimitError
    from openai.types.chat.chat_completion_chunk import (
        ChatCompletionChunk,
    )
except (ImportError, ModuleNotFoundError):
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


@dataclass
class xAI(OpenAILike):
    """
    Class for interacting with the xAI API.

    Attributes:
        id (str): The ID of the language model.
        name (str): The name of the API.
        provider (str): The provider of the API.
        api_key (Optional[str]): The API key for the xAI API.
        base_url (Optional[str]): The base URL for the xAI API.
    """

    id: str = "grok-beta"
    name: str = "xAI"
    provider: str = "xAI"

    api_key: Optional[str] = getenv("XAI_API_KEY")
    base_url: Optional[str] = "https://api.x.ai/v1"
