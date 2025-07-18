from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional, cast

from agno.exceptions import ModelProviderError
from agno.models.openai.like import OpenAILike

try:
    from portkey_ai import PORTKEY_GATEWAY_URL, createHeaders
except ImportError:
    raise ImportError("`portkey-ai` not installed. Please install using `pip install portkey-ai`")


@dataclass
class Portkey(OpenAILike):
    """
    A class for using models through the Portkey AI Gateway.

    Attributes:
        id (str): The model id. Defaults to "gpt-4o-mini".
        name (str): The model name. Defaults to "Portkey".
        provider (str): The provider name. Defaults to "Portkey".
        portkey_api_key (Optional[str]): The Portkey API key.
        virtual_key (Optional[str]): The virtual key for model routing.
        config (Optional[Dict[str, Any]]): Portkey configuration for routing, retries, etc.
        base_url (str): The Portkey gateway URL.
    """

    id: str = "gpt-4o-mini"
    name: str = "Portkey"
    provider: str = "Portkey"

    portkey_api_key: Optional[str] = getenv("PORTKEY_API_KEY")
    virtual_key: Optional[str] = getenv("PORTKEY_VIRTUAL_KEY")
    config: Optional[Dict[str, Any]] = None
    base_url: str = PORTKEY_GATEWAY_URL

    def _get_client_params(self) -> Dict[str, Any]:
        # Check for required keys
        if not self.portkey_api_key:
            raise ModelProviderError(
                message="PORTKEY_API_KEY not set. Please set the PORTKEY_API_KEY environment variable.",
                model_name=self.name,
                model_id=self.id,
            )

        if not self.virtual_key:
            raise ModelProviderError(
                message="PORTKEY_VIRTUAL_KEY not set. Please set the PORTKEY_VIRTUAL_KEY environment variable.",
                model_name=self.name,
                model_id=self.id,
            )

        # Create headers using Portkey's createHeaders function
        header_params: Dict[str, Any] = {
            "api_key": self.portkey_api_key,
            "virtual_key": self.virtual_key,
        }

        if self.config is not None:
            header_params["config"] = self.config

        portkey_headers = cast(Dict[str, Any], createHeaders(**header_params))

        # Merge with any existing default headers
        default_headers: Dict[str, Any] = {}
        if self.default_headers and isinstance(self.default_headers, dict):
            default_headers.update(self.default_headers)
        default_headers.update(portkey_headers)

        # Define base client params
        base_params = {
            "api_key": "not-needed",  # We use virtual keys instead
            "organization": self.organization,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": default_headers,
            "default_query": self.default_query,
        }

        # Create client_params dict with non-None values
        client_params = {k: v for k, v in base_params.items() if v is not None}

        # Add additional client params if provided
        if self.client_params:
            client_params.update(self.client_params)
        return client_params
