from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.models.openai.like import OpenAILike
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

    api_key: Optional[str] = field(default_factory=lambda: getenv("OPENROUTER_API_KEY"))
    base_url: str = "https://openrouter.ai/api/v1"
    max_tokens: int = 1024
    models: Optional[List[str]] = None  # Dynamic model routing https://openrouter.ai/docs/features/model-routing

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
