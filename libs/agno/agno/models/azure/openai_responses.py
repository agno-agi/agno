from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

import httpx

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.responses import OpenAIResponses
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import log_warning

try:
    from openai import AsyncAzureOpenAI as AsyncAzureOpenAIClient
    from openai import AzureOpenAI as AzureOpenAIClient
except ImportError:
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


@dataclass
class AzureOpenAIResponses(OpenAIResponses):
    """
    Azure OpenAI Responses API model.

    A class for interacting with Azure OpenAI models using the Responses API.

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
        client (Optional[AzureOpenAIClient]): The Azure OpenAI client to use.
        async_client (Optional[AsyncAzureOpenAIClient]): The async Azure OpenAI client to use.
    """

    id: str = "gpt-4o"
    name: str = "AzureOpenAIResponses"
    provider: str = "Azure"

    # Azure-specific parameters
    # Note: Responses API requires api-version 2025-03-01-preview or later
    api_version: Optional[str] = "2025-03-01-preview"
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    azure_ad_token: Optional[str] = None
    azure_ad_token_provider: Optional[Any] = None

    # Override parent's client types with Azure clients
    client: Optional[AzureOpenAIClient] = None
    async_client: Optional[AsyncAzureOpenAIClient] = None

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Get Azure-specific client parameters for API requests.

        Returns:
            Dict[str, Any]: Client parameters for Azure OpenAI
        """
        _client_params: Dict[str, Any] = {}

        # Get credentials from environment if not set
        self.api_key = self.api_key or getenv("AZURE_OPENAI_API_KEY")
        self.azure_endpoint = self.azure_endpoint or getenv("AZURE_OPENAI_ENDPOINT")
        self.azure_deployment = self.azure_deployment or getenv("AZURE_OPENAI_DEPLOYMENT")

        # Validate authentication
        if not (self.api_key or self.azure_ad_token):
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="AZURE_OPENAI_API_KEY not set. Please set the AZURE_OPENAI_API_KEY environment variable.",
                    model_name=self.name,
                )
            if not self.azure_ad_token:
                raise ModelAuthenticationError(
                    message="AZURE_AD_TOKEN not set. Please set the AZURE_AD_TOKEN environment variable.",
                    model_name=self.name,
                )

        # Build params mapping
        params_mapping = {
            "api_key": self.api_key,
            "api_version": self.api_version,
            "organization": self.organization,
            "azure_endpoint": self.azure_endpoint,
            "azure_deployment": self.azure_deployment,
            "base_url": self.base_url,
            "azure_ad_token": self.azure_ad_token,
            "azure_ad_token_provider": self.azure_ad_token_provider,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }

        # Add custom headers/query if provided
        if self.default_headers is not None:
            _client_params["default_headers"] = self.default_headers
        if self.default_query is not None:
            _client_params["default_query"] = self.default_query

        # Add non-None params
        _client_params.update({k: v for k, v in params_mapping.items() if v is not None})

        # Merge user-provided client params
        if self.client_params:
            _client_params.update(self.client_params)

        return _client_params

    def get_client(self) -> AzureOpenAIClient:
        """
        Get the Azure OpenAI client. Caches the client to avoid recreating it on every request.

        Returns:
            AzureOpenAIClient: The Azure OpenAI client.
        """
        if self.client is not None and not self.client.is_closed():
            return self.client

        _client_params: Dict[str, Any] = self._get_client_params()

        # Handle HTTP client
        if self.http_client:
            if isinstance(self.http_client, httpx.Client):
                _client_params["http_client"] = self.http_client
            else:
                log_warning("http_client is not an instance of httpx.Client. Using default global httpx.Client.")
                _client_params["http_client"] = get_default_sync_client()
        else:
            _client_params["http_client"] = get_default_sync_client()

        # Create client
        self.client = AzureOpenAIClient(**_client_params)
        return self.client

    def get_async_client(self) -> AsyncAzureOpenAIClient:
        """
        Returns an asynchronous Azure OpenAI client. Caches the client to avoid recreating it on every request.

        Returns:
            AsyncAzureOpenAIClient: An instance of the asynchronous Azure OpenAI client.
        """
        if self.async_client and not self.async_client.is_closed():
            return self.async_client

        _client_params: Dict[str, Any] = self._get_client_params()

        # Handle HTTP client
        if self.http_client:
            if isinstance(self.http_client, httpx.AsyncClient):
                _client_params["http_client"] = self.http_client
            else:
                log_warning(
                    "http_client is not an instance of httpx.AsyncClient. Using default global httpx.AsyncClient."
                )
                _client_params["http_client"] = get_default_async_client()
        else:
            _client_params["http_client"] = get_default_async_client()

        self.async_client = AsyncAzureOpenAIClient(**_client_params)
        return self.async_client
