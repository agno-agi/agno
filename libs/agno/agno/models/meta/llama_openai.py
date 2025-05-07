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

    api_key: Optional[str] = getenv("LLAMA_API_KEY")
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

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        # Define base request parameters
        base_params = {
            "max_completion_tokens": self.max_completion_tokens,
            "repetition_penalty": self.repetition_penalty,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "extra_headers": self.extra_headers,
            "extra_query": self.extra_query,
            "extra_body": self.extra_body,
            "request_params": self.request_params,
        }

        # Filter out None values
        request_params = {k: v for k, v in base_params.items() if v is not None}

        # Add tools
        if self._tools is not None and len(self._tools) > 0:
            request_params["tools"] = self._tools

            # Fix optional parameters where the "type" is [<type>, null]
            for tool in request_params["tools"]:  # type: ignore
                if "parameters" in tool["function"] and "properties" in tool["function"]["parameters"]:  # type: ignore
                    for _, obj in tool["function"]["parameters"].get("properties", {}).items():  # type: ignore
                        if isinstance(obj["type"], list):
                            obj["type"] = obj["type"][0]

        if self.response_format is not None:
            request_params["response_format"] = self.response_format

        # Add additional request params if provided
        if self.request_params:
            request_params.update(self.request_params)

        return request_params

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
