from dataclasses import dataclass
from os import getenv
from typing import Any, Callable, Dict, Type, Union

import httpx
from pydantic import BaseModel

from agno.models.anthropic import Claude as AnthropicClaude
from agno.models.message import Message
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import log_debug, log_warning
from agno.utils.models.claude import format_tools_for_model

try:
    from anthropic import AnthropicFoundry, AsyncAnthropicFoundry
except ImportError as e:
    raise ImportError("`anthropic` not installed. Please install it with `pip install anthropic`") from e


@dataclass
class Claude(AnthropicClaude):
    """
    Azure AI Foundry Claude model.

    For more information, see: https://docs.anthropic.com/en/docs/partner-models/azure-ai
    """

    id: str = "claude-sonnet-4-5"
    name: str = "AzureFoundryClaude"
    provider: str = "AzureFoundry"

    # Client parameters
    resource: str | None = None
    base_url: str | None = None
    azure_ad_token_provider: Callable[[], str] | None = None
    max_retries: int | None = None

    client: AnthropicFoundry | None = None  # type: ignore
    async_client: AsyncAnthropicFoundry | None = None  # type: ignore

    def __post_init__(self):
        """Validate model configuration after initialization"""
        if self.thinking:
            self._validate_thinking_support()
        self.supports_native_structured_outputs = False
        self.supports_json_schema_outputs = False

    def _get_client_params(self) -> Dict[str, Any]:
        client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("ANTHROPIC_FOUNDRY_API_KEY")
        if self.api_key:
            client_params["api_key"] = self.api_key

        resource = self.resource or getenv("ANTHROPIC_FOUNDRY_RESOURCE")
        if resource:
            client_params["resource"] = resource

        base_url = self.base_url or getenv("ANTHROPIC_FOUNDRY_BASE_URL")
        if base_url:
            client_params["base_url"] = base_url

        if self.azure_ad_token_provider:
            client_params["azure_ad_token_provider"] = self.azure_ad_token_provider

        if not (self.api_key or self.azure_ad_token_provider):
            log_warning(
                "Azure credentials not found. Set ANTHROPIC_FOUNDRY_API_KEY or provide an azure_ad_token_provider."
            )

        if self.timeout is not None:
            client_params["timeout"] = self.timeout
        if self.max_retries is not None:
            client_params["max_retries"] = self.max_retries
        if self.default_headers is not None:
            client_params["default_headers"] = self.default_headers
        if self.client_params is not None:
            client_params.update(self.client_params)

        return client_params

    def get_client(self):
        """Returns an instance of the AnthropicFoundry client."""
        if self.client and not self.client.is_closed():
            return self.client

        _client_params = self._get_client_params()
        if self.http_client:
            if isinstance(self.http_client, httpx.Client):
                _client_params["http_client"] = self.http_client
            else:
                log_warning("http_client is not an instance of httpx.Client. Using default global httpx.Client.")
                _client_params["http_client"] = get_default_sync_client()
        else:
            _client_params["http_client"] = get_default_sync_client()
        self.client = AnthropicFoundry(**_client_params)
        return self.client

    def get_async_client(self):
        """Returns an instance of the AsyncAnthropicFoundry client."""
        if self.async_client and not self.async_client.is_closed():
            return self.async_client

        _client_params = self._get_client_params()
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
        self.async_client = AsyncAnthropicFoundry(**_client_params)
        return self.async_client

    def get_request_params(
        self,
        response_format: Union[Dict, Type[BaseModel]] | None = None,
        tools: list[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """Generate keyword arguments for API requests."""
        if self.thinking:
            self._validate_thinking_support()

        _request_params: Dict[str, Any] = {}
        if self.max_tokens:
            _request_params["max_tokens"] = self.max_tokens
        if self.thinking:
            _request_params["thinking"] = self.thinking
        if self.output_config:
            _request_params["output_config"] = self.output_config
        if self.temperature:
            _request_params["temperature"] = self.temperature
        if self.stop_sequences:
            _request_params["stop_sequences"] = self.stop_sequences
        if self.top_p:
            _request_params["top_p"] = self.top_p
        if self.top_k:
            _request_params["top_k"] = self.top_k
        if self.timeout:
            _request_params["timeout"] = self.timeout

        betas_list = list(self.betas) if self.betas else []
        if betas_list:
            _request_params["betas"] = betas_list

        if self.request_params:
            _request_params.update(self.request_params)

        if _request_params:
            log_debug(f"Calling {self.provider} with request parameters: {_request_params}", log_level=2)
        return _request_params

    def _prepare_request_kwargs(
        self,
        system_message: str,
        tools: list[Dict[str, Any]] | None = None,
        response_format: Union[Dict, Type[BaseModel]] | None = None,
        messages: list[Message] | None = None,
    ) -> Dict[str, Any]:
        """Prepare the request keyword arguments for the API call."""
        request_kwargs = self.get_request_params(response_format=response_format, tools=tools).copy()
        system = self._build_system(system_message)
        if system:
            request_kwargs["system"] = system

        if tools:
            request_kwargs["tools"] = format_tools_for_model(tools)

        self._apply_cache_tools(request_kwargs)

        if request_kwargs:
            log_debug(f"Calling {self.provider} with request parameters: {request_kwargs}", log_level=2)
        return request_kwargs
