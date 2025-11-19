from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

import httpx

from agno.models.anthropic import Claude as AnthropicClaude
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import log_warning

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

    client: Optional[AnthropicVertex] = None  # type: ignore
    async_client: Optional[AsyncAnthropicVertex] = None  # type: ignore

    # Client parameters
    region: Optional[str] = None
    project_id: Optional[str] = None
    base_url: Optional[str] = None

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
