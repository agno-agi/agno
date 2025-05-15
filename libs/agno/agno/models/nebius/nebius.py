from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelProviderError
from agno.models.openai.like import OpenAILike


@dataclass
class Nebius(OpenAILike):
    """
    A class for interacting with Nebius AI Studio models.

    Attributes:
        id (str): The model id. Defaults to "Qwen/Qwen3-235B-A22B"".
        name (str): The model name. Defaults to "Nebius".
        provider (str): The provider name. Defaults to "Nebius".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.studio.nebius.com/v1".
    """

    id: str = "Qwen/Qwen3-4B-fast"  # Default model for chat
    name: str = "Nebius"
    provider: str = "Nebius"

    api_key: Optional[str] = getenv("NEBIUS_API_KEY")
    base_url: str = "https://api.studio.nebius.com/v1/"

    def _get_client_params(self) -> Dict[str, Any]:
        if not self.api_key:
            raise ModelProviderError(
                message="NEBIUS_API_KEY not set. Please set the NEBIUS_API_KEY environment variable.",
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
