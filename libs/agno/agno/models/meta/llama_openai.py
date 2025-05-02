from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

import httpx

try:
    from openai import AsyncOpenAI as AsyncOpenAIClient
except (ModuleNotFoundError, ImportError):
    raise ImportError("`openai` not installed. Please install using `pip install openai`")

from agno.models.meta.llama import Message
from agno.models.openai.like import OpenAILike
from agno.utils.log import log_warning


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

    api_key: Optional[str] = getenv("LLAMA_API_KEY")
    base_url: Optional[str] = "https://api.llama.com/compat/v1/"

    def _format_message(self, message: Message) -> Dict[str, Any]:
        """
        Format a message into the format expected by Llama API.

        Args:
            message (Message): The message to format.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        message_dict: Dict[str, Any] = {
            "role": self.role_map[message.role],
            "content": message.content,
            "name": message.name,
            "tool_call_id": message.tool_call_id,
            "tool_calls": message.tool_calls,
        }
        message_dict = {k: v for k, v in message_dict.items() if v is not None}

        if message.images is not None and len(message.images) > 0:
            log_warning("Image input is currently unsupported.")

        if message.videos is not None and len(message.videos) > 0:
            log_warning("Video input is currently unsupported.")

        if message.audio is not None and len(message.audio) > 0:
            log_warning("Audio input is currently unsupported.")

        # OpenAI expects the tool_calls to be None if empty, not an empty list
        if message.tool_calls is not None and len(message.tool_calls) == 0:
            message_dict["tool_calls"] = None

        # Manually add the content field even if it is None
        if message.content is None:
            message_dict["content"] = " "

        return message_dict

    def get_async_client(self):
        """Override to provide custom httpx client that properly handles redirects"""
        if self.async_client:
            return self.async_client

        client_params = self._get_client_params()

        # Llama gives a 307 redirect error, so we need to set up a custom client to allow redirects
        client_params["http_client"] = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100),
            follow_redirects=True,
            timeout=httpx.Timeout(30.0),
        )

        self.async_client = AsyncOpenAIClient(**client_params)
        return self.async_client
