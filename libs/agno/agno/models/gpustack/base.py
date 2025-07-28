"""Base classes for GPUStack provider implementation."""

from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

import httpx

from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.utils.log import log_error


@dataclass
class GPUStackBaseModel(Model):
    """Base class for GPUStack models.

    GPUStack provides native API endpoints for various AI model types.
    This base class handles common functionality like authentication,
    HTTP client management, and error handling.
    """

    name: str = "GPUStackModel"
    provider: str = "GPUStack"

    # GPUStack server configuration
    base_url: Optional[str] = None
    api_key: Optional[str] = None

    # HTTP client configuration
    timeout: Optional[float] = 120.0
    max_retries: Optional[int] = 3

    # Client instances
    _client: Optional[httpx.Client] = field(default=None, init=False, repr=False)
    _async_client: Optional[httpx.AsyncClient] = field(default=None, init=False, repr=False)

    def __post_init__(self):
        """Initialize GPUStack configuration."""
        super().__post_init__()

        # Load from environment if not provided
        if not self.base_url:
            self.base_url = getenv("GPUSTACK_SERVER_URL", "http://localhost:9009")

        # Ensure base URL doesn't end with /
        self.base_url = self.base_url.rstrip("/")

        if not self.api_key:
            self.api_key = getenv("GPUSTACK_API_KEY")
            if not self.api_key:
                log_error(
                    "GPUSTACK_API_KEY not set. Please set the GPUSTACK_API_KEY environment variable "
                    "or provide api_key parameter."
                )

    def _get_headers(self) -> Dict[str, str]:
        """Get common headers for API requests."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return headers

    def _get_client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                headers=self._get_headers(),
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._client

    def _get_async_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._get_headers(),
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._async_client

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Handle error responses from GPUStack API."""
        try:
            error_data = response.json()
            error_message = error_data.get("error", {}).get("message", response.text)
            error_type = error_data.get("error", {}).get("type", "unknown_error")
        except Exception:
            error_message = response.text
            error_type = "unknown_error"

        raise ModelProviderError(
            f"GPUStack API error ({response.status_code}): {error_message}",
            provider="gpustack",
            error_type=error_type,
            status_code=response.status_code,
        )

    def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> httpx.Response:
        """Make a synchronous HTTP request."""
        client = self._get_client()

        try:
            response = client.request(method=method, url=endpoint, json=json_data, files=files, **kwargs)

            if response.status_code >= 400:
                self._handle_error_response(response)

            return response

        except httpx.HTTPError as e:
            raise ModelProviderError(
                f"GPUStack HTTP error: {str(e)}",
                provider="gpustack",
                error_type="http_error",
            )

    async def _amake_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> httpx.Response:
        """Make an asynchronous HTTP request."""
        client = self._get_async_client()

        try:
            response = await client.request(method=method, url=endpoint, json=json_data, files=files, **kwargs)

            if response.status_code >= 400:
                self._handle_error_response(response)

            return response

        except httpx.HTTPError as e:
            raise ModelProviderError(
                f"GPUStack HTTP error: {str(e)}",
                provider="gpustack",
                error_type="http_error",
            )

    def __del__(self):
        """Cleanup HTTP clients."""
        if self._client:
            self._client.close()
        if self._async_client:
            # Note: async client should be closed in async context
            pass
