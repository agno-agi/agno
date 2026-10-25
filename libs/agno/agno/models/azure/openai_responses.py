from __future__ import annotations

from copy import copy, deepcopy
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

    Deployment names are arbitrary, so model detection based on the name can
    misfire; set ``is_reasoning_model`` when a deployment's name does not start
    with the underlying model's name. Deep research deployments must include
    ``deep-research`` in the deployment name to get the required request shaping.
    """

    id: str = "not-provided"
    name: str = "AzureOpenAIResponses"
    provider: str = "Azure"

    api_version: str | None = None
    azure_endpoint: str | None = None
    azure_ad_token: str | None = None
    azure_ad_token_provider: Any | None = None

    # Deployment names are arbitrary, so the name-based detection inherited from
    # OpenAIResponses cannot be trusted here. None falls back to matching on the
    # deployment name, which is only correct when it starts with the model name.
    is_reasoning_model: bool | None = None

    client: AzureOpenAIClient | None = None
    async_client: AsyncAzureOpenAIClient | None = None

    def __post_init__(self):
        # id defaults to a sentinel instead of inheriting the parent's model id,
        # because a deployment name cannot have a meaningful default.
        if not self.id or self.id == "not-provided":
            raise ValueError("AzureOpenAIResponses requires `id` to be set to your Azure deployment name.")
        super().__post_init__()

    def _using_reasoning_model(self) -> bool:
        """Return True if the deployment serves a reasoning model."""
        if self.is_reasoning_model is not None:
            return self.is_reasoning_model
        return super()._using_reasoning_model()

    def __deepcopy__(self, memo: dict) -> AzureOpenAIResponses:
        """Create a deep copy that preserves client references.

        Azure OpenAI clients may carry authentication state (e.g. AD tokens,
        token providers) that cannot be reconstructed from the model's own
        fields alone. Preserving the client references avoids authentication
        errors when the copied model is used (e.g. in the reasoning flow).
        """
        cls = self.__class__
        new_model = cls.__new__(cls)
        memo[id(self)] = new_model

        for k, v in self.__dict__.items():
            if k in {"response_format", "_tools", "_functions"}:
                continue
            # Preserve client references instead of nullifying them
            if k in {"client", "async_client", "http_client"}:
                setattr(new_model, k, v)
                continue
            try:
                setattr(new_model, k, deepcopy(v, memo))
            except Exception:
                try:
                    setattr(new_model, k, copy(v))
                except Exception:
                    setattr(new_model, k, v)

        return new_model

    def _get_client_params(self) -> dict[str, Any]:
        """Build Azure client parameters without mixing authentication methods."""
        # base_url and azure_endpoint are mutually exclusive in the Azure client,
        # so only fall back to the endpoint env var when no base_url is given.
        if self.base_url is None:
            self.azure_endpoint = self.azure_endpoint or getenv("AZURE_OPENAI_ENDPOINT")
        # Explicit value wins, then the OPENAI_API_VERSION env var, then a version known to support the Responses API.
        self.api_version = self.api_version or getenv("OPENAI_API_VERSION") or "2025-04-01-preview"

        if not (self.api_key or self.azure_ad_token or self.azure_ad_token_provider):
            self.api_key = getenv("AZURE_OPENAI_API_KEY")
            if not self.api_key:
                self.azure_ad_token = getenv("AZURE_OPENAI_AD_TOKEN")

        if not (self.api_key or self.azure_ad_token or self.azure_ad_token_provider):
            raise ModelAuthenticationError(
                message="Azure OpenAI authentication not configured. Please provide one of: "
                "api_key (or AZURE_OPENAI_API_KEY), azure_ad_token (or AZURE_OPENAI_AD_TOKEN), "
                "or azure_ad_token_provider",
                model_name=self.name,
            )

        params_mapping = {
            "api_key": self.api_key,
            "api_version": self.api_version,
            "organization": self.organization,
            "azure_endpoint": self.azure_endpoint,
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
