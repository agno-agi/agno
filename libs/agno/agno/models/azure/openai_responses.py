from __future__ import annotations

from dataclasses import dataclass
from os import getenv
from typing import Any

import httpx

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.responses import OpenAIResponses
from agno.utils.log import log_warning

try:
    from openai import AsyncAzureOpenAI as AsyncAzureOpenAIClient
    from openai import AzureOpenAI as AzureOpenAIClient
except ImportError as e:
    raise ImportError("`openai` not installed. Please install using `pip install openai -U`") from e


@dataclass
class AzureOpenAIResponses(OpenAIResponses):
    """Azure OpenAI model using the Responses API.

    ``id`` must be the Azure deployment name. Unlike deployment-based chat
    completion endpoints, Azure's Responses endpoint selects the deployment
    from the request body's ``model`` field.
    """

    name: str = "AzureOpenAIResponses"
    provider: str = "Azure"

    api_version: str | None = None
    azure_endpoint: str | None = None
    azure_deployment: str | None = None
    azure_ad_token: str | None = None
    azure_ad_token_provider: Any | None = None

    client: AzureOpenAIClient | None = None
    async_client: AsyncAzureOpenAIClient | None = None

    def _get_client_params(self) -> dict[str, Any]:
        """Build Azure client parameters without mixing authentication methods."""
        self.azure_endpoint = self.azure_endpoint or getenv("AZURE_OPENAI_ENDPOINT")
        self.azure_deployment = self.azure_deployment or getenv("AZURE_OPENAI_DEPLOYMENT")
        self.api_version = self.api_version or getenv("OPENAI_API_VERSION")

        if not (self.api_key or self.azure_ad_token or self.azure_ad_token_provider):
            self.azure_ad_token = getenv("AZURE_OPENAI_AD_TOKEN")
            if not self.azure_ad_token:
                self.api_key = getenv("AZURE_OPENAI_API_KEY")

        if not (self.api_key or self.azure_ad_token or self.azure_ad_token_provider):
            raise ModelAuthenticationError(
                message="Azure OpenAI authentication not configured. Please provide one of: "
                "AZURE_OPENAI_API_KEY, azure_ad_token, or azure_ad_token_provider",
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
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
        }
        client_params = {key: value for key, value in params_mapping.items() if value is not None}
        if self.client_params:
            client_params.update(self.client_params)
        return client_params

    def get_client(self) -> AzureOpenAIClient:
        """Return a cached synchronous Azure OpenAI client."""
        if self.client is not None and not self.client.is_closed():
            return self.client

        client_params = self._get_client_params()
        if self.http_client:
            if isinstance(self.http_client, httpx.Client):
                client_params["http_client"] = self.http_client
            else:
                log_warning("http_client is not an instance of httpx.Client. Ignoring and using SDK default.")

        self.client = AzureOpenAIClient(**client_params)
        return self.client

    def get_async_client(self) -> AsyncAzureOpenAIClient:
        """Return a cached asynchronous Azure OpenAI client."""
        if self.async_client is not None and not self.async_client.is_closed():
            return self.async_client

        client_params = self._get_client_params()
        if self.http_client:
            if isinstance(self.http_client, httpx.AsyncClient):
                client_params["http_client"] = self.http_client
            else:
                log_warning("http_client is not an instance of httpx.AsyncClient. Ignoring and using SDK default.")

        self.async_client = AsyncAzureOpenAIClient(**client_params)
        return self.async_client
