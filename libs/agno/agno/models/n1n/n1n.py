from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class N1N(OpenAILike):
    """
    A class for interacting with n1n.ai models.

    Attributes:
        id (str): The model id. Defaults to "gpt-4o".
        name (str): The model name. Defaults to "N1N".
        provider (str): The provider name. Defaults to "N1N".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.n1n.ai/v1".
    """

    id: str = "gpt-4o"
    name: str = "N1N"
    provider: str = "N1N"

    api_key: Optional[str] = field(default_factory=lambda: getenv("N1N_API_KEY"))
    base_url: str = "https://api.n1n.ai/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("N1N_API_KEY")
            if not self.api_key:
                # Raise error immediately if key is missing
                raise ModelAuthenticationError(
                    message="N1N_API_KEY not set. Please set the N1N_API_KEY environment variable.",
                    model_name=self.name,
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
