from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Literal, Optional, Tuple, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput


@dataclass
class ReasoningConfig:
    """
    Configuration for reasoning tokens in OpenRouter API requests.

    OpenRouter normalizes the different ways of customizing the amount of reasoning tokens
    that the model will use, providing a unified interface across different providers.

    Attributes:
        effort: Reasoning effort level. Supported by OpenAI reasoning models (o1/o3/GPT-5 series)
            and Grok models. Values: "xhigh" (~95%), "high" (~80%), "medium" (~50%),
            "low" (~20%), "minimal" (~10%), "none" (disabled).
        max_tokens: Maximum tokens for reasoning. Supported by Gemini thinking models,
            Anthropic reasoning models, and some Alibaba Qwen thinking models.
            For Anthropic: minimum 1024, maximum 32000 tokens.
        exclude: If True, the model uses reasoning internally but doesn't return it in the response.
            Useful when you want reasoning benefits without the output overhead.
        enabled: Enable reasoning with default parameters (medium effort, no exclusions).
            Typically inferred from effort or max_tokens if not set.

    Note:
        - Use either `effort` OR `max_tokens`, not both.
        - For models that only support one parameter, OpenRouter maps to the other automatically.
        - Reasoning tokens are counted as output tokens for billing purposes.

    See: https://openrouter.ai/docs/guides/best-practices/reasoning-tokens
    """

    effort: Optional[Literal["xhigh", "high", "medium", "low", "minimal", "none"]] = None
    max_tokens: Optional[int] = None
    exclude: Optional[bool] = None
    enabled: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for API request, excluding None values."""
        result = {}
        if self.effort is not None:
            result["effort"] = self.effort
        if self.max_tokens is not None:
            result["max_tokens"] = self.max_tokens
        if self.exclude is not None:
            result["exclude"] = self.exclude
        if self.enabled is not None:
            result["enabled"] = self.enabled
        return result


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
        reasoning (Optional[ReasoningConfig]): Configuration for reasoning tokens.
            Controls reasoning effort/budget and whether to preserve reasoning blocks for tool calling.
            Required for models like Gemini with function calling to maintain reasoning continuity.
            See: https://openrouter.ai/docs/guides/best-practices/reasoning-tokens
    """

    id: str = "gpt-4o"
    name: str = "OpenRouter"
    provider: str = "OpenRouter"

    api_key: Optional[str] = None
    base_url: str = "https://openrouter.ai/api/v1"
    max_tokens: int = 1024
    models: Optional[List[str]] = None  # Dynamic model routing https://openrouter.ai/docs/features/model-routing
    reasoning: Optional[ReasoningConfig] = None  # Reasoning configuration

    def _should_preserve_reasoning(self) -> bool:
        """Check if reasoning blocks should be preserved (when reasoning is configured)."""
        return self.reasoning is not None

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
        """Returns request params with fallback models and reasoning configuration."""
        request_params = super().get_request_params(
            response_format=response_format, tools=tools, tool_choice=tool_choice, run_response=run_response
        )
        extra_body = request_params.get("extra_body") or {}
        if self.models:
            extra_body["models"] = self.models
        if self.reasoning:
            extra_body["reasoning"] = self.reasoning.to_dict()
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

    def _extract_reasoning_from_obj(self, obj: Any) -> Tuple[Any, Optional[str]]:
        """Extract reasoning_details and reasoning text from a response object."""
        reasoning_details = getattr(obj, "reasoning_details", None)
        if not reasoning_details and hasattr(obj, "model_extra") and obj.model_extra:
            reasoning_details = obj.model_extra.get("reasoning_details")
        reasoning_text = getattr(obj, "reasoning", None)
        if not reasoning_text and hasattr(obj, "model_extra") and obj.model_extra:
            reasoning_text = obj.model_extra.get("reasoning")
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
        if self._should_preserve_reasoning() and hasattr(response, "choices") and response.choices:
            message = getattr(response.choices[0], "message", None)
            if message:
                self._apply_reasoning_to_response(model_response, message)
        return model_response

    def _parse_provider_response_delta(self, response_delta: Any) -> ModelResponse:
        """Parse streaming delta, extracting reasoning_details."""
        model_response = super()._parse_provider_response_delta(response_delta)
        if self._should_preserve_reasoning() and hasattr(response_delta, "choices") and response_delta.choices:
            delta = getattr(response_delta.choices[0], "delta", None)
            if delta:
                self._apply_reasoning_to_response(model_response, delta)
        return model_response
