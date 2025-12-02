from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.models.response import ModelResponse
from agno.utils.log import log_debug

try:
    from openai.types.chat import ChatCompletion, ChatCompletionChunk
except (ImportError, ModuleNotFoundError):
    pass  # Will be handled by parent class


@dataclass
class DeepSeek(OpenAILike):
    """
    A class for interacting with DeepSeek models.

    Attributes:
        id (str): The model id. Defaults to "deepseek-chat".
        name (str): The model name. Defaults to "DeepSeek".
        provider (str): The provider name. Defaults to "DeepSeek".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.deepseek.com".
    """

    id: str = "deepseek-chat"
    name: str = "DeepSeek"
    provider: str = "DeepSeek"

    api_key: Optional[str] = field(default_factory=lambda: getenv("DEEPSEEK_API_KEY"))
    base_url: str = "https://api.deepseek.com"

    # Their support for structured outputs is currently broken
    supports_native_structured_outputs: bool = False

    def _get_client_params(self) -> Dict[str, Any]:
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("DEEPSEEK_API_KEY")
            if not self.api_key:
                # Raise error immediately if key is missing
                raise ModelProviderError(
                    message="DEEPSEEK_API_KEY not set. Please set the DEEPSEEK_API_KEY environment variable.",
                    model_name=self.name,
                    model_id=self.id,
                )

        # Define base client params
        base_params = {
            "api_key": self.api_key,
            "organization": self.organization,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
        }

        # Create client_params dict with non-None values
        client_params = {k: v for k, v in base_params.items() if v is not None}

        # Add additional client params if provided
        if self.client_params:
            client_params.update(self.client_params)
        return client_params

    def _parse_provider_response(
        self,
        response: "ChatCompletion",
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> ModelResponse:
        model_response = super()._parse_provider_response(response, response_format)

        # Store reasoning_content in provider_data for thinking mode with tool calls
        if model_response.reasoning_content is not None:
            if model_response.provider_data is None:
                model_response.provider_data = {}
            model_response.provider_data["reasoning_content"] = model_response.reasoning_content
            log_debug(f"Stored reasoning_content in provider_data ({len(model_response.reasoning_content)} chars)")

        return model_response

    def _parse_provider_response_delta(self, response_delta: "ChatCompletionChunk") -> ModelResponse:
        model_response = super()._parse_provider_response_delta(response_delta)

        # Store reasoning_content in provider_data for thinking mode with tool calls
        if model_response.reasoning_content is not None:
            if model_response.provider_data is None:
                model_response.provider_data = {}
            model_response.provider_data["reasoning_content"] = model_response.reasoning_content
            log_debug(f"Stored reasoning_content in provider_data ({len(model_response.reasoning_content)} chars)")

        return model_response

    def _format_message(self, message: Message, compress_tool_results: bool = False) -> Dict[str, Any]:
        message_dict = super()._format_message(message, compress_tool_results)

        # Include reasoning_content from provider_data for thinking mode with tool calls
        if (
            message.role == "assistant"
            and message.provider_data is not None
            and message.provider_data.get("reasoning_content") is not None
        ):
            reasoning_content = message.provider_data["reasoning_content"]
            message_dict["reasoning_content"] = reasoning_content
            log_debug(f"Including reasoning_content in message ({len(reasoning_content)} chars)")

        return message_dict
