from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

import httpx

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.responses import OpenAIResponses
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import log_warning

try:
    from openai import AsyncOpenAI, OpenAI
except ImportError:
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


@dataclass
class AzureOpenAIResponses(OpenAIResponses):
    """
    Azure OpenAI Responses API model.

    A class for interacting with Azure OpenAI models using the Responses API.
    Per Microsoft's documentation, the Responses API uses the regular OpenAI client
    with a special base_url pointing to Azure.

    Args:
        id (str): The model/deployment name to use.
        name (str): The model name for identification.
        provider (str): The provider name.
        api_key (Optional[str]): The Azure OpenAI API key.
        azure_endpoint (Optional[str]): The Azure endpoint (e.g., https://your-resource.openai.azure.com/).
        azure_deployment (Optional[str]): The Azure deployment name (used as model if id not specified).
        azure_ad_token (Optional[str]): The Azure AD token for authentication (alternative to api_key).
        azure_ad_token_provider (Optional[Any]): A callable that returns an Azure AD token.
        client (Optional[OpenAI]): The OpenAI client to use.
        async_client (Optional[AsyncOpenAI]): The async OpenAI client to use.
    """

    id: str = "gpt-4o"
    name: str = "AzureOpenAIResponses"
    provider: str = "Azure"

    # Azure-specific parameters
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    azure_ad_token: Optional[str] = None
    azure_ad_token_provider: Optional[Any] = None

    # Override parent's client types - use regular OpenAI clients with Azure base_url
    client: Optional[OpenAI] = None
    async_client: Optional[AsyncOpenAI] = None

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Get client parameters for Azure OpenAI Responses API.

        Per Microsoft's documentation, the Responses API uses the regular OpenAI client
        with base_url set to: https://{resource}.openai.azure.com/openai/v1/

        Returns:
            Dict[str, Any]: Client parameters for OpenAI client
        """
        _client_params: Dict[str, Any] = {}

        # Get credentials from environment if not set
        self.api_key = self.api_key or getenv("AZURE_OPENAI_API_KEY")
        self.azure_endpoint = self.azure_endpoint or getenv("AZURE_OPENAI_ENDPOINT")
        self.azure_deployment = self.azure_deployment or getenv("AZURE_OPENAI_DEPLOYMENT")

        # Handle Azure AD token provider
        if self.azure_ad_token_provider is not None and self.azure_ad_token is None:
            # Call the token provider to get the token
            self.azure_ad_token = self.azure_ad_token_provider()

        # Validate authentication - need EITHER api_key OR azure_ad_token
        if not self.api_key and not self.azure_ad_token:
            raise ModelAuthenticationError(
                message="Authentication required. Please set either AZURE_OPENAI_API_KEY environment variable "
                "or provide azure_ad_token/azure_ad_token_provider.",
                model_name=self.name,
            )

        # Validate endpoint
        if not self.azure_endpoint:
            raise ModelAuthenticationError(
                message="AZURE_OPENAI_ENDPOINT not set. Please set the AZURE_OPENAI_ENDPOINT environment variable.",
                model_name=self.name,
            )

        # Build base_url from azure_endpoint
        # Per Microsoft docs: https://{resource}.openai.azure.com/openai/v1/
        base_url = f"{self.azure_endpoint.rstrip('/')}/openai/v1/"

        # Use azure_ad_token as api_key if api_key not provided
        api_key = self.api_key or self.azure_ad_token

        # Build params for regular OpenAI client
        params_mapping = {
            "api_key": api_key,
            "base_url": base_url,
            "organization": self.organization,
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

    def get_client(self) -> OpenAI:
        """
        Get the OpenAI client configured for Azure. Caches the client to avoid recreating it on every request.

        Returns:
            OpenAI: The OpenAI client configured with Azure base_url.
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

        # Create regular OpenAI client with Azure base_url
        self.client = OpenAI(**_client_params)
        return self.client

    def get_async_client(self) -> AsyncOpenAI:
        """
        Returns an asynchronous OpenAI client configured for Azure.
        Caches the client to avoid recreating it on every request.

        Returns:
            AsyncOpenAI: An instance of the asynchronous OpenAI client configured with Azure base_url.
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

        # Create regular AsyncOpenAI client with Azure base_url
        self.async_client = AsyncOpenAI(**_client_params)
        return self.async_client
