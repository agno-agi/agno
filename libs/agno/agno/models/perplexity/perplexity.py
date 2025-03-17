from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.models.message import Citations, UrlCitation
from agno.models.response import ModelResponse
from agno.utils.log import logger

try:
    from openai.types.chat.chat_completion import ChatCompletion
    from openai.types.chat.chat_completion_chunk import (
        ChatCompletionChunk,
        ChoiceDelta,
    )
    from openai.types.chat.parsed_chat_completion import ParsedChatCompletion
except ModuleNotFoundError:
    raise ImportError("`openai` not installed. Please install using `pip install openai`")

from agno.models.openai.like import OpenAILike


@dataclass
class Perplexity(OpenAILike):
    """
    A class for using models hosted on Perplexity.

    Attributes:
        id (str): The model id. Defaults to "sonar".
        name (str): The model name. Defaults to "Perplexity".
        provider (str): The provider name. Defaults to "Perplexity: " + id.
        api_key (Optional[str]): The API key. Defaults to None.
        base_url (str): The base URL. Defaults to "https://api.perplexity.ai/chat/completions".
        max_tokens (int): The maximum number of tokens. Defaults to 1024.
    """

    id: str = "sonar"
    name: str = "Perplexity"
    provider: str = "Perplexity"

    api_key: Optional[str] = getenv("PERPLEXITY_API_KEY")
    base_url: str = "https://api.perplexity.ai/"
    max_tokens: int = 1024
    top_k: Optional[float] = None

    supports_structured_outputs: bool = True

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        # Define base request parameters
        base_params: Dict[str, Any] = {
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "presence_penalty": self.presence_penalty,
            "frequency_penalty": self.frequency_penalty,
        }

        if (
            self.response_format
            and isinstance(self.response_format, type)
            and issubclass(self.response_format, BaseModel)
        ):
            base_params["response_format"] = {
                "type": "json_schema",
                "json_schema": {"schema": self.response_format.model_json_schema()},
            }

        # Filter out None values
        request_params = {k: v for k, v in base_params.items() if v is not None}
        # Add additional request params if provided
        if self.request_params:
            request_params.update(self.request_params)
        return request_params

    def parse_provider_response(self, response: Union[ChatCompletion, ParsedChatCompletion]) -> ModelResponse:
        """
        Parse the OpenAI response into a ModelResponse.

        Args:
            response: Response from invoke() method

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        if hasattr(response, "error") and response.error:
            raise ModelProviderError(
                message=response.error.get("message", "Unknown model error"),
                model_name=self.name,
                model_id=self.id,
            )

        # Get response message
        response_message = response.choices[0].message

        # Parse structured outputs if enabled
        try:
            if (
                self.response_format is not None
                and self.structured_outputs
                and issubclass(self.response_format, BaseModel)
            ):
                parsed_object = response_message.parsed  # type: ignore
                if parsed_object is not None:
                    model_response.parsed = parsed_object
        except Exception as e:
            logger.warning(f"Error retrieving structured outputs: {e}")

        # Add role
        if response_message.role is not None:
            model_response.role = response_message.role

        # Add content
        if response_message.content is not None:
            model_response.content = response_message.content

        # Add tool calls
        if response_message.tool_calls is not None and len(response_message.tool_calls) > 0:
            try:
                model_response.tool_calls = [t.model_dump() for t in response_message.tool_calls]
            except Exception as e:
                logger.warning(f"Error processing tool calls: {e}")

        # Add citations if present
        if hasattr(response, "citations") and response.citations is not None:
            model_response.citations = Citations(
                urls=[UrlCitation(url=c) for c in response.citations],
            )

        if response.usage is not None:
            model_response.response_usage = response.usage

        return model_response

    def parse_provider_response_delta(self, response_delta: ChatCompletionChunk) -> ModelResponse:
        """
        Parse the OpenAI streaming response into a ModelResponse.

        Args:
            response_delta: Raw response chunk from OpenAI

        Returns:
            ProviderResponse: Iterator of parsed response data
        """
        model_response = ModelResponse()
        if response_delta.choices and len(response_delta.choices) > 0:
            delta: ChoiceDelta = response_delta.choices[0].delta

            # Add content
            if delta.content is not None:
                model_response.content = delta.content

            # Add tool calls
            if delta.tool_calls is not None:
                model_response.tool_calls = delta.tool_calls  # type: ignore

        # Add citations if present
        if hasattr(response_delta, "citations") and response_delta.citations is not None:
            model_response.citations = Citations(
                urls=[UrlCitation(url=c) for c in response_delta.citations],
            )

        # Add usage metrics if present
        if response_delta.usage is not None:
            model_response.response_usage = response_delta.usage

        return model_response
