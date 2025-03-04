from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

import httpx

from agno.models.openai.like import OpenAILike

try:
    from openai import AsyncAzureOpenAI as AsyncAzureOpenAIClient
    from openai import AzureOpenAI as AzureOpenAIClient
except (ModuleNotFoundError, ImportError):
    raise ImportError("`azure openai` not installed. Please install using `pip install openai`")


@dataclass
class AzureOpenAI(OpenAILike):
    """
    Azure OpenAI Chat model

    Args:

        id (str): The model name to use.
        name (str): The model name to use.
        provider (str): The provider to use.
        api_key (Optional[str]): The API key to use.
        api_version (str): The API version to use.
        azure_endpoint (Optional[str]): The Azure endpoint to use.
        azure_deployment (Optional[str]): The Azure deployment to use.
        base_url (Optional[str]): The base URL to use.
        azure_ad_token (Optional[str]): The Azure AD token to use.
        azure_ad_token_provider (Optional[Any]): The Azure AD token provider to use.
        organization (Optional[str]): The organization to use.
        client (Optional[AzureOpenAIClient]): The OpenAI client to use.
        async_client (Optional[AsyncAzureOpenAIClient]): The OpenAI client to use.
    """

    id: str
    name: str = "AzureOpenAI"
    provider: str = "Azure"

    supports_structured_outputs: bool = True

    api_key: Optional[str] = None
    api_version: Optional[str] = "2024-10-21"
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    base_url: Optional[str] = None
    azure_ad_token: Optional[str] = None
    azure_ad_token_provider: Optional[Any] = None

    client: Optional[AzureOpenAIClient] = None
    async_client: Optional[AsyncAzureOpenAIClient] = None

    def _get_client_params(self) -> Dict[str, Any]:
        _client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("AZURE_OPENAI_API_KEY")
        self.azure_endpoint = self.azure_endpoint or getenv("AZURE_OPENAI_ENDPOINT")
        self.azure_deployment = self.azure_deployment or getenv("AZURE_OPENAI_DEPLOYMENT")
        params_mapping = {
            "api_key": self.api_key,
            "api_version": self.api_version,
            "organization": self.organization,
            "azure_endpoint": self.azure_endpoint,
            "azure_deployment": self.azure_deployment,
            "base_url": self.base_url,
            "azure_ad_token": self.azure_ad_token,
            "azure_ad_token_provider": self.azure_ad_token_provider,
            "http_client": self.http_client,
        }

        _client_params.update({k: v for k, v in params_mapping.items() if v is not None})
        if self.client_params:
            _client_params.update(self.client_params)
        return _client_params

    def get_client(self) -> AzureOpenAIClient:
        """
        Get the OpenAI client.

        Returns:
            AzureOpenAIClient: The OpenAI client.

        """
        if self.client is not None:
            return self.client

        _client_params: Dict[str, Any] = self._get_client_params()

        # -*- Create client
        self.client = AzureOpenAIClient(**_client_params)
        return self.client

    def get_async_client(self) -> AsyncAzureOpenAIClient:
        """
        Returns an asynchronous OpenAI client.

        Returns:
            AsyncAzureOpenAIClient: An instance of the asynchronous OpenAI client.
        """
        if self.async_client:
            return self.async_client

        _client_params: Dict[str, Any] = self._get_client_params()

        if self.http_client:
            _client_params["http_client"] = self.http_client
        else:
            # Create a new async HTTP client with custom limits
            _client_params["http_client"] = httpx.AsyncClient(
                limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100)
            )

        self.async_client = AsyncAzureOpenAIClient(**_client_params)
        return self.async_client
