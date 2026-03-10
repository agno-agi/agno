from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError
from agno.models.message import Message
from agno.models.openai.open_responses import OpenResponses


@dataclass
class OpenRouterResponses(OpenResponses):
    """
    A class for interacting with OpenRouter models using the OpenAI Responses API.

    OpenRouter's Responses API (currently in beta) provides OpenAI-compatible access
    to multiple AI models through a unified interface. It supports tools, reasoning,
    streaming, and plugins.

    Note: OpenRouter's Responses API is stateless - each request is independent and
    no server-side state is persisted.

    For more information, see: https://openrouter.ai/docs/api/reference/responses/overview

    Attributes:
        id (str): The model id. Defaults to "openai/gpt-oss-20b".
        name (str): The model name. Defaults to "OpenRouterResponses".
        provider (str): The provider name. Defaults to "OpenRouter".
        api_key (Optional[str]): The API key. Uses OPENROUTER_API_KEY env var if not set.
        base_url (str): The base URL. Defaults to "https://openrouter.ai/api/v1".
        models (Optional[List[str]]): List of fallback model IDs to use if the primary model
            fails due to rate limits, timeouts, or unavailability. OpenRouter will automatically
            try these models in order. Example: ["anthropic/claude-sonnet-4", "deepseek/deepseek-r1"]

    Example:
        ```python
        from agno.agent import Agent
        from agno.models.openrouter import OpenRouterResponses

        agent = Agent(
            model=OpenRouterResponses(id="anthropic/claude-sonnet-4"),
            markdown=True,
        )
        agent.print_response("Write a haiku about coding")
        ```
    """

    id: str = "openai/gpt-oss-20b"
    name: str = "OpenRouterResponses"
    provider: str = "OpenRouter"

    api_key: Optional[str] = None
    base_url: str = "https://openrouter.ai/api/v1"

    # Dynamic model routing - fallback models if primary fails
    # https://openrouter.ai/docs/features/model-routing
    models: Optional[List[str]] = None

    # OpenRouter's Responses API is stateless
    store: Optional[bool] = False

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for OPENROUTER_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.

        Raises:
            ModelAuthenticationError: If OPENROUTER_API_KEY is not set.
        """
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("OPENROUTER_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="OPENROUTER_API_KEY not set. Please set the OPENROUTER_API_KEY environment variable.",
                    model_name=self.name,
                )

        # Build client params
        base_params: Dict[str, Any] = {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "organization": self.organization,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
        }

        # Filter out None values
        client_params = {k: v for k, v in base_params.items() if v is not None}

        # Add additional client params if provided
        if self.client_params:
            client_params.update(self.client_params)

        return client_params

    def get_request_params(
        self,
        messages: Optional[List[Message]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests, including fallback models configuration.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        # Get base request params from parent class
        request_params = super().get_request_params(
            messages=messages,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
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

    def _using_reasoning_model(self) -> bool:
        """
        Check if the model is a reasoning model that requires special handling.

        OpenRouter hosts various reasoning models, but they may not all use
        OpenAI's reasoning API format. We check for known reasoning model patterns.
        """
        # Check for OpenAI reasoning models hosted on OpenRouter
        if self.id.startswith("openai/o3") or self.id.startswith("openai/o4"):
            return True
        return False
