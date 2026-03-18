from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

import httpx

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import log_warning

try:
    from openai import AsyncAzureOpenAI as AsyncAzureOpenAIClient
    from openai import AzureOpenAI as AzureOpenAIClient
except ImportError:
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


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

    supports_native_structured_outputs: bool = True

    api_key: Optional[str] = None
    api_version: Optional[str] = "2024-10-21"
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    base_url: Optional[str] = None
    azure_ad_token: Optional[str] = None
    azure_ad_token_provider: Optional[Any] = None

    default_headers: Optional[Dict[str, str]] = None
    default_query: Optional[Dict[str, Any]] = None

    client: Optional[AzureOpenAIClient] = None
    async_client: Optional[AsyncAzureOpenAIClient] = None

    def _get_client_params(self) -> Dict[str, Any]:
        _client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("AZURE_OPENAI_API_KEY")
        self.azure_endpoint = self.azure_endpoint or getenv("AZURE_OPENAI_ENDPOINT")
        self.azure_deployment = self.azure_deployment or getenv("AZURE_OPENAI_DEPLOYMENT")

        if not (self.api_key or self.azure_ad_token or self.azure_ad_token_provider):
            raise ModelAuthenticationError(
                message="Azure OpenAI authentication not configured. Please provide one of:"
                "AZURE_OPENAI_API_KEY environment variable, azure_ad_token, or azure_ad_token_provider",
                model_name=self.name,
            )

        params_mapping = {
            "api_key": self.api_key,
            "api_version": self.api_version,
            "organization": self.organization,
            "azure_endpoint": self.azure_endpoint,
            "azure_deployment": self.azure_deployment,
            "base_url": self.base_url,
            "azure_ad_token": self.azure_ad_token,
            "azure_ad_token_provider": self.azure_ad_token_provider,
        }
        if self.default_headers is not None:
            _client_params["default_headers"] = self.default_headers
        if self.default_query is not None:
            _client_params["default_query"] = self.default_query

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
        if self.client is not None and not self.client.is_closed():
            return self.client

        _client_params: Dict[str, Any] = self._get_client_params()

        if self.http_client:
            if isinstance(self.http_client, httpx.Client):
                _client_params["http_client"] = self.http_client
            else:
                log_warning("http_client is not an instance of httpx.Client. Using default global httpx.Client.")
                # Use global sync client when user http_client is invalid
                _client_params["http_client"] = get_default_sync_client()
        else:
            # Use global sync client when no custom http_client is provided
            _client_params["http_client"] = get_default_sync_client()

        # Create client
        self.client = AzureOpenAIClient(**_client_params)
        return self.client

    def get_async_client(self) -> AsyncAzureOpenAIClient:
        """
        Returns an asynchronous OpenAI client.

        Returns:
            AsyncAzureOpenAIClient: An instance of the asynchronous OpenAI client.
        """
        if self.async_client and not self.async_client.is_closed():
            return self.async_client

        _client_params: Dict[str, Any] = self._get_client_params()

        if self.http_client:
            if isinstance(self.http_client, httpx.AsyncClient):
                _client_params["http_client"] = self.http_client
            else:
                log_warning(
                    "http_client is not an instance of httpx.AsyncClient. Using default global httpx.AsyncClient."
                )
                # Use global async client when user http_client is invalid
                _client_params["http_client"] = get_default_async_client()
        else:
            # Use global async client when no custom http_client is provided
            _client_params["http_client"] = get_default_async_client()

        self.async_client = AsyncAzureOpenAIClient(**_client_params)
        return self.async_client
