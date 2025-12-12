from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.models.openai.like import OpenAILike


@dataclass
class ZAI(OpenAILike):
    """
    A class for interacting with ZAI models.

    Attributes:
        id (str): The model id. Defaults to "glm-4.6".
        name (str): The model name. Defaults to "GLM".
        provider (str): The provider name. Defaults to "ZAI".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.z.ai/api/paas/v4/".
    """

    id: str = "glm-4.6"
    name: str = "GLM"
    provider: str = "ZAI"

    api_key: Optional[str] = getenv("ZAI_API_KEY")
    base_url: str = "https://api.z.ai/api/paas/v4/"

    # Thinking parameters
    enable_thinking: bool = True

    # Supports structured outputs
    supports_native_structured_outputs: bool = True
    supports_json_schema_outputs: bool = True

    def _get_client_params(self) -> Dict[str, Any]:
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("ZAI_API_KEY")
            if not self.api_key:
                raise ModelProviderError("ZAI API key is not set. Please set the ZAI_API_KEY environment variable.")

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

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        params = super().get_request_params(response_format=response_format, tools=tools, tool_choice=tool_choice)

        params["extra_body"] = {"thinking": {"type": "enabled" if self.enable_thinking else "disabled"}}

        return params
