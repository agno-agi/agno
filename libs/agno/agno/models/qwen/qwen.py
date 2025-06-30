from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelProviderError
from agno.models.openai.like import OpenAILike


@dataclass
class Qwen(OpenAILike):
    """
    A class for interacting with Qwen models.

    Attributes:
        id (str): The model id. Defaults to "qwen-max".
        name (str): The model name. Defaults to "Qwen".
        provider (str): The provider name. Defaults to "Qwen".
        api_key (Optional[str]): The API key from DashScope.
        base_url (str): The base URL. Defaults to "https://dashscope.aliyuncs.com/compatible-mode/v1".
    """

    id: str = "qwen-max"
    name: str = "Qwen"
    provider: str = "Qwen"

    api_key: Optional[str] = getenv("QWEN_API_KEY")
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # Qwen supports structured outputs through OpenAI-compatible API
    supports_native_structured_outputs: bool = True

    def _get_client_params(self) -> Dict[str, Any]:
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("QWEN_API_KEY")
            if not self.api_key:
                # Also try DASHSCOPE_API_KEY as an alternative
                self.api_key = getenv("DASHSCOPE_API_KEY")
                if not self.api_key:
                    # Raise error immediately if key is missing
                    raise ModelProviderError(
                        message="QWEN_API_KEY or DASHSCOPE_API_KEY not set. Please set one of these environment variables.",
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