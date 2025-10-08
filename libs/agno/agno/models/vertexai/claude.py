from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.models.anthropic import Claude as AnthropicClaude

try:
    from anthropic import AnthropicVertex as AnthropicClient
    from anthropic import (
        AsyncAnthropicVertex as AsyncAnthropicClient,
    )
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

    # Anthropic clients
    client: Optional[AnthropicClient] = None
    async_client: Optional[AsyncAnthropicClient] = None

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

    def get_client(self) -> AnthropicClient:
        """
        Returns an instance of the Anthropic client.
        """
        if self.client and not self.client.is_closed():
            return self.client

        _client_params = self._get_client_params()
        self.client = AnthropicClient(**_client_params)
        return self.client

    def get_async_client(self) -> AsyncAnthropicClient:
        """
        Returns an instance of the async Anthropic client.
        """
        if self.async_client:
            return self.async_client

        _client_params = self._get_client_params()
        self.async_client = AsyncAnthropicClient(**_client_params)
        return self.async_client
