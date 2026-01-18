from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from openai.types.chat import ChatCompletion, ChatCompletionChunk
from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput


@dataclass
class OpenRouter(OpenAILike):
    """
    A class for using models hosted on OpenRouter.

    Attributes:
        id (str): The model id. Defaults to "gpt-4o".
        name (str): The model name. Defaults to "OpenRouter".
        provider (str): The provider name. Defaults to "OpenRouter".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://openrouter.ai/api/v1".
        max_tokens (int): The maximum number of tokens. Defaults to 1024.
        fallback_models (Optional[List[str]]): List of fallback model IDs to use if the primary model
            fails due to rate limits, timeouts, or unavailability. OpenRouter will automatically try
            these models in order. Example: ["anthropic/claude-sonnet-4", "deepseek/deepseek-r1"]
    """

    id: str = "gpt-4o"
    name: str = "OpenRouter"
    provider: str = "OpenRouter"

    api_key: Optional[str] = None
    base_url: str = "https://openrouter.ai/api/v1"
    max_tokens: int = 1024
    models: Optional[List[str]] = None  # Dynamic model routing https://openrouter.ai/docs/features/model-routing

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for OPENROUTER_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("OPENROUTER_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="OPENROUTER_API_KEY not set. Please set the OPENROUTER_API_KEY environment variable.",
                    model_name=self.name,
                )

        return super()._get_client_params()

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests, including fallback models configuration.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        # Get base request params from parent class
        request_params = super().get_request_params(
            response_format=response_format, tools=tools, tool_choice=tool_choice, run_response=run_response
        )

        # Add fallback models to extra_body if specified
        if self.models:
            # Get existing extra_body or create new dict
            extra_body = request_params.get("extra_body") or {}

            # Merge fallback models into extra_body
            extra_body["models"] = self.models

            # Update request params
            request_params["extra_body"] = extra_body

        return request_params

    def _format_message(self, message: Message, compress_tool_results: bool = False) -> Dict[str, Any]:
        message_dict = super()._format_message(message, compress_tool_results)

        if message.role == "assistant" and message.provider_data:
            if message.provider_data.get("reasoning_details"):
                message_dict["reasoning_details"] = message.provider_data["reasoning_details"]

        return message_dict

    def _parse_provider_response(
        self,
        response: ChatCompletion,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> ModelResponse:
        model_response = super()._parse_provider_response(response, response_format)

        if response.choices and len(response.choices) > 0:
            response_message = response.choices[0].message
            if hasattr(response_message, "reasoning_details") and response_message.reasoning_details:
                if model_response.provider_data is None:
                    model_response.provider_data = {}
                model_response.provider_data["reasoning_details"] = response_message.reasoning_details
            elif hasattr(response_message, "model_extra"):
                extra = getattr(response_message, "model_extra", None)
                if extra and isinstance(extra, dict) and extra.get("reasoning_details"):
                    if model_response.provider_data is None:
                        model_response.provider_data = {}
                    model_response.provider_data["reasoning_details"] = extra["reasoning_details"]

        return model_response

    def _parse_provider_response_delta(self, response_delta: ChatCompletionChunk) -> ModelResponse:
        model_response = super()._parse_provider_response_delta(response_delta)

        if response_delta.choices and len(response_delta.choices) > 0:
            choice_delta = response_delta.choices[0].delta
            if hasattr(choice_delta, "reasoning_details") and choice_delta.reasoning_details:
                if model_response.provider_data is None:
                    model_response.provider_data = {}
                model_response.provider_data["reasoning_details"] = choice_delta.reasoning_details

        return model_response
