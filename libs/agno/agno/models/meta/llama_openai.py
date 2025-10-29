from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

try:
    from openai import AsyncOpenAI as AsyncOpenAIClient
except ImportError:
    raise ImportError("`openai` not installed. Please install using `pip install openai`")

from agno.models.meta.llama import Message
from agno.models.openai.like import OpenAILike
from agno.utils.http import get_default_async_client
from agno.utils.models.llama import format_message


@dataclass
class LlamaOpenAI(OpenAILike):
    """
    Class for interacting with the Llama API via OpenAI-like interface.

    Attributes:
        id (str): The ID of the language model.
        name (str): The name of the API.
        provider (str): The provider of the API.
        api_key (Optional[str]): The API key for the xAI API.
        base_url (Optional[str]): The base URL for the xAI API.
    """

    id: str = "Llama-4-Maverick-17B-128E-Instruct-FP8"
    name: str = "LlamaOpenAI"
    provider: str = "LlamaOpenAI"

    api_key: Optional[str] = field(default_factory=lambda: getenv("LLAMA_API_KEY"))
    base_url: Optional[str] = "https://api.llama.com/compat/v1/"

    # Request parameters
    max_completion_tokens: Optional[int] = None
    repetition_penalty: Optional[float] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    extra_headers: Optional[Any] = None
    extra_query: Optional[Any] = None
    extra_body: Optional[Any] = None
    request_params: Optional[Dict[str, Any]] = None

    supports_native_structured_outputs: bool = False
    supports_json_schema_outputs: bool = True

    # Cached async client
    openai_async_client: Optional[AsyncOpenAIClient] = None

    def _format_message(self, message: Message) -> Dict[str, Any]:
        """
        Format a message into the format expected by Llama API.

        Args:
            message (Message): The message to format.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        return format_message(message, openai_like=True)

    def get_async_client(self):
        """Override to provide custom httpx client that properly handles redirects"""
        # Return cached client if it exists
        if self.openai_async_client is not None:
            return self.openai_async_client

        client_params = self._get_client_params()

        # Use global async client - it's configured with proper limits
        client_params["http_client"] = get_default_async_client()

        # Create and cache the client
        self.openai_async_client = AsyncOpenAIClient(**client_params)
        return self.openai_async_client
