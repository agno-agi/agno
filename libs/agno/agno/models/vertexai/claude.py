from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

import httpx
from pydantic import BaseModel

from agno.models.anthropic import Claude as AnthropicClaude
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import log_debug, log_warning
from agno.utils.models.claude import format_tools_for_model

try:
    from anthropic import AnthropicVertex, AsyncAnthropicVertex
except ImportError as e:
    raise ImportError("`anthropic` not installed. Please install it with `pip install anthropic`") from e


@dataclass
class Claude(AnthropicClaude):
    """
    A class representing Anthropic Claude model.

    For more information, see: https://docs.anthropic.com/en/api/messages
    """

    id: str = "claude-sonnet-4@20250514"
    name: str = "Claude"
    provider: str = "VertexAI"

    # Client parameters
    region: Optional[str] = None
    project_id: Optional[str] = None
    base_url: Optional[str] = None

    client: Optional[AnthropicVertex] = None  # type: ignore
    async_client: Optional[AsyncAnthropicVertex] = None  # type: ignore

    def __post_init__(self):
        """Validate model configuration after initialization"""
        # Validate thinking support immediately at model creation
        if self.thinking:
            self._validate_thinking_support()
        # Overwrite output schema support for VertexAI Claude
        self.supports_native_structured_outputs = False
        self.supports_json_schema_outputs = False

    def _get_client_params(self) -> Dict[str, Any]:
        client_params: Dict[str, Any] = {}

        # Add API key to client parameters
        client_params["region"] = self.region or getenv("CLOUD_ML_REGION")
        client_params["project_id"] = self.project_id or getenv("ANTHROPIC_VERTEX_PROJECT_ID")
        client_params["base_url"] = self.base_url or getenv("ANTHROPIC_VERTEX_BASE_URL")
        if self.timeout is not None:
            client_params["timeout"] = self.timeout

        # Add additional client parameters
        if self.client_params is not None:
            client_params.update(self.client_params)
        if self.default_headers is not None:
            client_params["default_headers"] = self.default_headers
        return client_params

    def get_client(self):
        """
        Returns an instance of the Anthropic client.
        """
        if self.client and not self.client.is_closed():
            return self.client

        _client_params = self._get_client_params()
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
        self.client = AnthropicVertex(**_client_params)
        return self.client

    def get_async_client(self):
        """
        Returns an instance of the async Anthropic client.
        """
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
                # Use global async client when user http_client is invalid
                _client_params["http_client"] = get_default_async_client()
        else:
            # Use global async client when no custom http_client is provided
            _client_params["http_client"] = get_default_async_client()
        self.async_client = AsyncAnthropicVertex(**_client_params)
        return self.async_client

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Generate keyword arguments for API requests.

        Returns:
            Dict[str, Any]: The keyword arguments for API requests.
        """
        # Validate thinking support if thinking is enabled
        if self.thinking:
            self._validate_thinking_support()

        _request_params: Dict[str, Any] = {}
        if self.max_tokens:
            _request_params["max_tokens"] = self.max_tokens
        if self.thinking:
            _request_params["thinking"] = self.thinking
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

        # Build betas list - include existing betas and add new one if needed
        betas_list = list(self.betas) if self.betas else []

        # Include betas if any are present
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
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> Dict[str, Any]:
        """
        Prepare the request keyword arguments for the API call.

        Args:
            system_message (str): The concatenated system messages.
            tools: Optional list of tools
            response_format: Optional response format (Pydantic model or dict)

        Returns:
            Dict[str, Any]: The request keyword arguments.
        """
        # Pass response_format and tools to get_request_params for beta header handling
        request_kwargs = self.get_request_params(response_format=response_format, tools=tools).copy()
        if system_message:
            if self.cache_system_prompt:
                cache_control = (
                    {"type": "ephemeral", "ttl": "1h"}
                    if self.extended_cache_time is not None and self.extended_cache_time is True
                    else {"type": "ephemeral"}
                )
                request_kwargs["system"] = [{"text": system_message, "type": "text", "cache_control": cache_control}]
            else:
                request_kwargs["system"] = [{"text": system_message, "type": "text"}]

        # Format tools (this will handle strict mode)
        if tools:
            request_kwargs["tools"] = format_tools_for_model(tools)

        if request_kwargs:
            log_debug(f"Calling {self.provider} with request parameters: {request_kwargs}", log_level=2)
        return request_kwargs
