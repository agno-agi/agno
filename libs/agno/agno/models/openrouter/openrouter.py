from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike
from agno.models.message import Message
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
        models (Optional[List[str]]): List of fallback model IDs to use if the primary model
            fails due to rate limits, timeouts, or unavailability. OpenRouter will automatically try
            these models in order. Example: ["anthropic/claude-sonnet-4", "deepseek/deepseek-r1"]
        preserve_reasoning (bool): Enable reasoning blocks preservation for models that require it.
            Required for Gemini models with function calling. Defaults to False.
            See: https://openrouter.ai/docs/guides/best-practices/reasoning-tokens#preserving-reasoning-blocks
    """

    id: str = "gpt-4o"
    name: str = "OpenRouter"
    provider: str = "OpenRouter"

    api_key: Optional[str] = None
    base_url: str = "https://openrouter.ai/api/v1"
    max_tokens: int = 1024
    models: Optional[List[str]] = None  # Dynamic model routing https://openrouter.ai/docs/features/model-routing
    preserve_reasoning: bool = False  # Enable for models requiring reasoning blocks preservation

    def _should_preserve_reasoning(self) -> bool:
        """Check if reasoning blocks should be preserved."""
        return self.preserve_reasoning

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
        """Returns request params with fallback models and reasoning preservation."""
        request_params = super().get_request_params(
            response_format=response_format, tools=tools, tool_choice=tool_choice, run_response=run_response
        )
        extra_body = request_params.get("extra_body") or {}
        if self.models:
            extra_body["models"] = self.models
        if extra_body:
            request_params["extra_body"] = extra_body
        return request_params

    def _format_message(self, message: Message, compress_tool_results: bool = False) -> Dict[str, Any]:
        """Format message, preserving reasoning_details for Gemini function calling."""
        message_dict = super()._format_message(message, compress_tool_results=compress_tool_results)
        # Preserve reasoning_details in assistant messages with tool calls
        if self._should_preserve_reasoning() and message.role == "assistant" and message.tool_calls:
            if message.provider_data and message.provider_data.get("reasoning_details"):
                message_dict["reasoning_details"] = message.provider_data["reasoning_details"]
        return message_dict

    def _extract_reasoning_from_obj(self, obj: Any) -> tuple[Any, Optional[str]]:
        """Extract reasoning_details and reasoning text from a response object."""
        reasoning_details = getattr(obj, 'reasoning_details', None)
        if not reasoning_details and hasattr(obj, 'model_extra') and obj.model_extra:
            reasoning_details = obj.model_extra.get('reasoning_details')
        reasoning_text = getattr(obj, 'reasoning', None)
        if not reasoning_text and hasattr(obj, 'model_extra') and obj.model_extra:
            reasoning_text = obj.model_extra.get('reasoning')
        return reasoning_details, reasoning_text

    def _apply_reasoning_to_response(self, model_response: ModelResponse, obj: Any) -> None:
        """Apply extracted reasoning data to model response."""
        reasoning_details, reasoning_text = self._extract_reasoning_from_obj(obj)
        if reasoning_details:
            if model_response.provider_data is None:
                model_response.provider_data = {}
            model_response.provider_data["reasoning_details"] = reasoning_details
        if reasoning_text and model_response.reasoning_content is None:
            model_response.reasoning_content = reasoning_text

    def _parse_provider_response(
        self,
        response: Any,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> ModelResponse:
        """Parse response, extracting reasoning_details for Gemini models."""
        model_response = super()._parse_provider_response(response, response_format=response_format)
        if self._should_preserve_reasoning() and hasattr(response, 'choices') and response.choices:
            message = getattr(response.choices[0], 'message', None)
            if message:
                self._apply_reasoning_to_response(model_response, message)
        return model_response

    def _parse_provider_response_delta(self, response_delta: Any) -> ModelResponse:
        """Parse streaming delta, extracting reasoning_details."""
        model_response = super()._parse_provider_response_delta(response_delta)
        if self._should_preserve_reasoning() and hasattr(response_delta, 'choices') and response_delta.choices:
            delta = getattr(response_delta.choices[0], 'delta', None)
            if delta:
                self._apply_reasoning_to_response(model_response, delta)
        return model_response
