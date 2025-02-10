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
        openai_client (Optional[AzureOpenAIClient]): The OpenAI client to use.
    """

    id: str
    name: str = "AzureOpenAI"
    provider: str = "Azure"

    api_key: Optional[str] = getenv("AZURE_OPENAI_API_KEY")
    api_version: str = getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    azure_endpoint: Optional[str] = getenv("AZURE_OPENAI_ENDPOINT")
    azure_deployment: Optional[str] = getenv("AZURE_DEPLOYMENT")
    azure_ad_token: Optional[str] = None
    azure_ad_token_provider: Optional[Any] = None
    openai_client: Optional[AzureOpenAIClient] = None

    def get_client(self) -> AzureOpenAIClient:
        """
        Get the OpenAI client.

        Returns:
            AzureOpenAIClient: The OpenAI client.

        """
        if self.openai_client:
            return self.openai_client

        _client_params: Dict[str, Any] = self._get_client_params()

        return AzureOpenAIClient(**_client_params)

    def get_async_client(self) -> AsyncAzureOpenAIClient:
        """
        Returns an asynchronous OpenAI client.

        Returns:
            AsyncAzureOpenAIClient: An instance of the asynchronous OpenAI client.
        """

        _client_params: Dict[str, Any] = self._get_client_params()

        if self.http_client:
            _client_params["http_client"] = self.http_client
        else:
            # Create a new async HTTP client with custom limits
            _client_params["http_client"] = httpx.AsyncClient(
                limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100)
            )
        return AsyncAzureOpenAIClient(**_client_params)

    def _get_client_params(self) -> Dict[str, Any]:
        _client_params: Dict[str, Any] = {}
        if self.api_key:
            _client_params["api_key"] = self.api_key
        if self.api_version:
            _client_params["api_version"] = self.api_version
        if self.organization:
            _client_params["organization"] = self.organization
        if self.azure_endpoint:
            _client_params["azure_endpoint"] = self.azure_endpoint
        if self.azure_deployment:
            _client_params["azure_deployment"] = self.azure_deployment
        if self.base_url:
            _client_params["base_url"] = self.base_url
        if self.azure_ad_token:
            _client_params["azure_ad_token"] = self.azure_ad_token
        if self.azure_ad_token_provider:
            _client_params["azure_ad_token_provider"] = self.azure_ad_token_provider
        if self.http_client:
            _client_params["http_client"] = self.http_client
        if self.client_params:
            _client_params.update(self.client_params)
        return _client_params
