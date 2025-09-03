from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.models.openai.like import OpenAILike


@dataclass
class DashScope(OpenAILike):
    """
    A class for interacting with Qwen models via DashScope API.

    Attributes:
        id (str): The model id. Defaults to "qwen-plus".
        name (str): The model name. Defaults to "Qwen".
        provider (str): The provider name. Defaults to "Qwen".
        api_key (Optional[str]): The DashScope API key.
        base_url (str): The base URL. Defaults to "https://dashscope-intl.aliyuncs.com/compatible-mode/v1".
        enable_thinking (bool): Enable thinking process (DashScope native parameter). Defaults to False.
        include_thoughts (Optional[bool]): Include thinking process in response (alternative parameter). Defaults to None.
    """

    id: str = "qwen-plus"
    name: str = "Qwen"
    provider: str = "Dashscope"

    api_key: Optional[str] = getenv("DASHSCOPE_API_KEY") or getenv("QWEN_API_KEY")
    base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

    # Thinking parameters
    enable_thinking: bool = False
    include_thoughts: Optional[bool] = None
    thinking_budget: Optional[int] = None

    # DashScope supports structured outputs
    supports_native_structured_outputs: bool = True
    supports_json_schema_outputs: bool = True

    def _get_client_params(self) -> Dict[str, Any]:
        if not self.api_key:
            self.api_key = getenv("DASHSCOPE_API_KEY")
            if not self.api_key:
                raise ModelProviderError(
                    message="DASHSCOPE_API_KEY not set. Please set the DASHSCOPE_API_KEY environment variable.",
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

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        params = super().get_request_params(response_format=response_format, tools=tools, tool_choice=tool_choice)

        if self.include_thoughts is not None:
            self.enable_thinking = self.include_thoughts

        if self.enable_thinking is not None:
            params["extra_body"] = {
                "enable_thinking": self.enable_thinking,
            }

            if self.thinking_budget is not None:
                params["extra_body"]["thinking_budget"] = self.thinking_budget

        return params
