import asyncio
import logging
from time import sleep
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 2  # Exponential backoff: 1, 2, 4, 8...

# Global httpx clients for resource efficiency
# These are shared across all models to reuse connection pools and avoid resource leaks.
# Consumers can override these at application startup using set_default_sync_client()
# and set_default_async_client() to customize limits, timeouts, proxies, etc.
_global_sync_client: Optional[httpx.Client] = None
_global_async_client: Optional[httpx.AsyncClient] = None


def get_default_sync_client() -> httpx.Client:
    """Get or create the global synchronous httpx client.

    Returns:
        A singleton httpx.Client instance with default limits.
    """
    global _global_sync_client
    if _global_sync_client is None or _global_sync_client.is_closed:
        _global_sync_client = httpx.Client(
            limits=httpx.Limits(max_connections=1000, max_keepalive_connections=200), http2=True, follow_redirects=True
        )
    return _global_sync_client


def get_default_async_client() -> httpx.AsyncClient:
    """Get or create the global asynchronous httpx client.

    Returns:
        A singleton httpx.AsyncClient instance with default limits.
    """
    global _global_async_client
    if _global_async_client is None or _global_async_client.is_closed:
        _global_async_client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=1000, max_keepalive_connections=200), http2=True, follow_redirects=True
        )
    return _global_async_client


def close_sync_client() -> None:
    """Closes the global sync httpx client.

    Should be called during application shutdown.
    """
    global _global_sync_client
    if _global_sync_client is not None and not _global_sync_client.is_closed:
        _global_sync_client.close()


async def aclose_default_clients() -> None:
    """Asynchronously close the global httpx clients.

    Should be called during application shutdown in async contexts.
    """
    global _global_sync_client, _global_async_client
    if _global_sync_client is not None and not _global_sync_client.is_closed:
        _global_sync_client.close()
    if _global_async_client is not None and not _global_async_client.is_closed:
        await _global_async_client.aclose()


def set_default_sync_client(client: httpx.Client) -> None:
    """Set the global synchronous httpx client.

    IMPORTANT: Call before creating any model instances. Models cache clients on first use.

    Allows consumers to override the default httpx client with custom configuration
    (e.g., custom limits, timeouts, proxies, SSL verification, etc.).
    This is useful at application startup to customize how all models connect.

    Example:
        >>> import httpx
        >>> from agno.utils.http import set_default_sync_client
        >>> custom_client = httpx.Client(
        ...     limits=httpx.Limits(max_connections=500),
        ...     timeout=httpx.Timeout(30.0),
        ...     verify=False  # for dev environments
        ... )
        >>> set_default_sync_client(custom_client)
        >>> # All models will now use this custom client

    Args:
        client: An httpx.Client instance to use as the global sync client.
    """
    global _global_sync_client
    _global_sync_client = client


def set_default_async_client(client: httpx.AsyncClient) -> None:
    """Set the global asynchronous httpx client.

    IMPORTANT: Call before creating any model instances. Models cache clients on first use.

    Allows consumers to override the default async httpx client with custom configuration
    (e.g., custom limits, timeouts, proxies, SSL verification, etc.).
    This is useful at application startup to customize how all models connect.

    Example:
        >>> import httpx
        >>> from agno.utils.http import set_default_async_client
        >>> custom_client = httpx.AsyncClient(
        ...     limits=httpx.Limits(max_connections=500),
        ...     timeout=httpx.Timeout(30.0),
        ...     verify=False  # for dev environments
        ... )
        >>> set_default_async_client(custom_client)
        >>> # All models will now use this custom client

    Args:
        client: An httpx.AsyncClient instance to use as the global async client.
    """
    global _global_async_client
    _global_async_client = client


def fetch_with_retry(
    url: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_factor: int = DEFAULT_BACKOFF_FACTOR,
    proxy: Optional[str] = None,
) -> httpx.Response:
    """Synchronous HTTP GET with retry logic."""

    for attempt in range(max_retries):
        try:
            response = httpx.get(url, proxy=proxy) if proxy else httpx.get(url)
            response.raise_for_status()
            return response
        except httpx.RequestError as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to fetch {url} after {max_retries} attempts: {e}")
                raise
            wait_time = backoff_factor**attempt
            logger.warning("Connection error.")
            sleep(wait_time)
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error for {url}: {e.response.status_code} - {e.response.text}")
            raise

    raise httpx.RequestError(f"Failed to fetch {url} after {max_retries} attempts")


async def async_fetch_with_retry(
    url: str,
    client: Optional[httpx.AsyncClient] = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_factor: int = DEFAULT_BACKOFF_FACTOR,
    proxy: Optional[str] = None,
) -> httpx.Response:
    """Asynchronous HTTP GET with retry logic."""

    async def _fetch():
        if client is None:
            client_args = {"proxy": proxy} if proxy else {}
            async with httpx.AsyncClient(**client_args) as local_client:  # type: ignore
                return await local_client.get(url)
        else:
            return await client.get(url)

    for attempt in range(max_retries):
        try:
            response = await _fetch()
            response.raise_for_status()
            return response
        except httpx.RequestError as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to fetch {url} after {max_retries} attempts: {e}")
                raise
            wait_time = backoff_factor**attempt
            logger.warning("Connection error.")
            await asyncio.sleep(wait_time)
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error for {url}: {e.response.status_code} - {e.response.text}")
            raise

    raise httpx.RequestError(f"Failed to fetch {url} after {max_retries} attempts")
