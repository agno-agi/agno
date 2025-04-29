from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelProviderError
from agno.models.openai.like import OpenAILike


@dataclass
class DeepSeek(OpenAILike):
    """
    A class for interacting with DeepSeek models.

    For more information, see: https://api-docs.deepseek.com/
    """

    id: str = "deepseek-chat"
    name: str = "DeepSeek"
    provider: str = "DeepSeek"

    api_key: Optional[str] = getenv("DEEPSEEK_API_KEY", None)
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
