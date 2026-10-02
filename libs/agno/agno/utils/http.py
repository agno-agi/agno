import asyncio
import logging
import threading
from time import sleep
from typing import Any, Optional

import httpx2

from agno.utils.log import log_warning

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 2  # Exponential backoff: 1, 2, 4, 8...

# Global httpx2 clients for resource efficiency
# These are shared across all models to reuse connection pools and avoid resource leaks.
# Consumers can override these at application startup using set_default_sync_client()
# and set_default_async_client() to customize limits, timeouts, proxies, etc.
_global_sync_client: Optional[httpx2.Client] = None
_global_async_client: Optional[httpx2.AsyncClient] = None

# Locks for thread-safe lazy initialization
_sync_client_lock = threading.Lock()
_async_client_lock = threading.Lock()


def get_default_sync_client() -> httpx2.Client:
    """Get or create the global synchronous httpx2 client.

    Thread-safe lazy initialization using double-checked locking.

    Note: HTTP/2 is disabled for the sync client because HTTP/2's stream
    multiplexing is not thread-safe when sharing a client across threads
    (e.g., when using ThreadPoolExecutor). HTTP/1.1 uses connection pooling
    where each connection handles one request at a time, which is thread-safe.

    Returns:
        A singleton httpx2.Client instance with default limits.
    """
    global _global_sync_client

    if _global_sync_client is not None and not _global_sync_client.is_closed:
        return _global_sync_client

    with _sync_client_lock:
        if _global_sync_client is None or _global_sync_client.is_closed:
            _global_sync_client = httpx2.Client(
                limits=httpx2.Limits(max_connections=1000, max_keepalive_connections=200),
                timeout=httpx2.Timeout(60.0),
                http2=False,  # Disabled for thread safety in multi-threaded contexts
                follow_redirects=True,
            )
    return _global_sync_client


def get_default_async_client() -> httpx2.AsyncClient:
    """Get or create the global asynchronous httpx2 client.

    Thread-safe lazy initialization using double-checked locking.

    Note: HTTP/2 is enabled for the async client because asyncio runs in a
    single-threaded event loop where HTTP/2 stream multiplexing is safe.

    Returns:
        A singleton httpx2.AsyncClient instance with default limits.
    """
    global _global_async_client

    if _global_async_client is not None and not _global_async_client.is_closed:
        return _global_async_client

    with _async_client_lock:
        if _global_async_client is None or _global_async_client.is_closed:
            _global_async_client = httpx2.AsyncClient(
                limits=httpx2.Limits(max_connections=1000, max_keepalive_connections=200),
                timeout=httpx2.Timeout(60.0),
                http2=True,  # Safe in async context (single-threaded event loop)
                follow_redirects=True,
            )
    return _global_async_client


def close_sync_client() -> None:
    """Closes the global sync httpx2 client.

    Thread-safe. Should be called during application shutdown.
    """
    global _global_sync_client
    with _sync_client_lock:
        if _global_sync_client is not None and not _global_sync_client.is_closed:
            _global_sync_client.close()
            _global_sync_client = None


async def aclose_default_clients() -> None:
    """Asynchronously close the global httpx2 clients.

    Thread-safe. Should be called during application shutdown in async contexts.
    """
    global _global_sync_client, _global_async_client

    with _sync_client_lock:
        if _global_sync_client is not None and not _global_sync_client.is_closed:
            _global_sync_client.close()
            _global_sync_client = None

    with _async_client_lock:
        if _global_async_client is not None and not _global_async_client.is_closed:
            await _global_async_client.aclose()
            _global_async_client = None


def set_default_sync_client(client: httpx2.Client) -> None:
    """Set the global synchronous httpx2 client.

    Thread-safe. Call before creating any model instances for best results,
    though this can be called at any time.

    Allows consumers to override the default httpx2 client with custom configuration
    (e.g., custom limits, timeouts, proxies, SSL verification, etc.).
    This is useful at application startup to customize how all models connect.

    Warning: If using this client in multi-threaded contexts (e.g., ThreadPoolExecutor),
    consider disabling HTTP/2 (http2=False) to avoid thread-safety issues with
    HTTP/2 stream multiplexing.

    Example:
        >>> import httpx2
        >>> from agno.utils.http import set_default_sync_client
        >>> custom_client = httpx2.Client(
        ...     limits=httpx2.Limits(max_connections=500),
        ...     timeout=httpx2.Timeout(30.0),
        ...     http2=False,  # Recommended for multi-threaded use
        ...     verify=False  # for dev environments
        ... )
        >>> set_default_sync_client(custom_client)
        >>> # All models will now use this custom client

    Args:
        client: An httpx2.Client instance to use as the global sync client.
    """
    global _global_sync_client
    with _sync_client_lock:
        _global_sync_client = client


def set_default_async_client(client: httpx2.AsyncClient) -> None:
    """Set the global asynchronous httpx2 client.

    Thread-safe. Call before creating any model instances for best results,
    though this can be called at any time.

    Allows consumers to override the default async httpx2 client with custom configuration
    (e.g., custom limits, timeouts, proxies, SSL verification, etc.).
    This is useful at application startup to customize how all models connect.

    Example:
        >>> import httpx2
        >>> from agno.utils.http import set_default_async_client
        >>> custom_client = httpx2.AsyncClient(
        ...     limits=httpx2.Limits(max_connections=500),
        ...     timeout=httpx2.Timeout(30.0),
        ...     verify=False  # for dev environments
        ... )
        >>> set_default_async_client(custom_client)
        >>> # All models will now use this custom client

    Args:
        client: An httpx2.AsyncClient instance to use as the global async client.
    """
    global _global_async_client
    with _async_client_lock:
        _global_async_client = client


def fetch_with_retry(
    url: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_factor: int = DEFAULT_BACKOFF_FACTOR,
    proxy: Optional[str] = None,
    timeout: Optional[int] = None,
    follow_redirects: Optional[bool] = None,
) -> httpx2.Response:
    """Synchronous HTTP GET with retry logic."""

    for attempt in range(max_retries):
        try:
            kwargs: dict = {"proxy": proxy}
            if timeout is not None:
                kwargs["timeout"] = timeout
            if follow_redirects is not None:
                kwargs["follow_redirects"] = follow_redirects
            response = httpx2.get(url, **kwargs)
            response.raise_for_status()
            return response
        except httpx2.RequestError as e:
            if attempt == max_retries - 1:
                logger.exception(f"Failed to fetch {url} after {max_retries} attempts")
                raise
            wait_time = backoff_factor**attempt
            log_warning(f"Connection error: {str(e)}")
            sleep(wait_time)
        except httpx2.HTTPStatusError as e:
            logger.exception(f"HTTP error for {url}: {e.response.status_code} - {e.response.text}")
            raise

    raise httpx2.RequestError(f"Failed to fetch {url} after {max_retries} attempts")  # type: ignore[call-arg]


async def async_fetch_with_retry(
    url: str,
    client: Optional[httpx2.AsyncClient] = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_factor: int = DEFAULT_BACKOFF_FACTOR,
    proxy: Optional[str] = None,
    timeout: Optional[int] = None,
    follow_redirects: Optional[bool] = None,
) -> httpx2.Response:
    """Asynchronous HTTP GET with retry logic."""

    async def _fetch():
        kwargs: dict = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if follow_redirects is not None:
            kwargs["follow_redirects"] = follow_redirects

        if client is None:
            async with httpx2.AsyncClient(proxy=proxy) as local_client:
                return await local_client.get(url, **kwargs)
        else:
            return await client.get(url, **kwargs)

    for attempt in range(max_retries):
        try:
            response = await _fetch()
            response.raise_for_status()
            return response
        except httpx2.RequestError as e:
            if attempt == max_retries - 1:
                logger.exception(f"Failed to fetch {url} after {max_retries} attempts")
                raise
            wait_time = backoff_factor**attempt
            log_warning(f"Connection error: {str(e)}")
            await asyncio.sleep(wait_time)
        except httpx2.HTTPStatusError as e:
            logger.exception(f"HTTP error for {url}: {e.response.status_code} - {e.response.text}")
            raise

    raise httpx2.RequestError(f"Failed to fetch {url} after {max_retries} attempts")  # type: ignore[call-arg]


def sdk_http_client_type(default_sync: type, default_async: type, is_async: bool = False) -> type:
    """The HTTP client class an SDK accepts, read off its default client class's MRO.

    SDKs that moved their HTTP layer from httpx to httpx2 (anthropic 1.0, openai 3.0)
    raise TypeError at construction when handed the other flavour's client, so the
    accepted class is read off the SDK's own default-client re-export rather than
    assumed to be one flavour or the other.
    """
    default = default_async if is_async else default_sync
    wanted = "AsyncClient" if is_async else "Client"
    for base in default.__mro__[1:]:
        if base.__name__ == wanted:
            return base
    return httpx2.AsyncClient if is_async else httpx2.Client


def resolve_http_client(http_client: Optional[Any], expected: type, fallback: Optional[Any] = None) -> Optional[Any]:
    """Return the HTTP client to hand an SDK, or None to let it build its own.

    A client of the wrong flavour is dropped with a warning instead of being passed on,
    where it would raise TypeError at client construction and take every request with it.
    """
    if http_client is not None:
        if isinstance(http_client, expected):
            return http_client
        log_warning(
            f"http_client is not an instance of {expected.__module__}.{expected.__qualname__} "
            f"(the SDK's HTTP client). Ignoring and using the SDK default."
        )

    # The shared agno client is httpx2's, which an httpx-based SDK will not take.
    if fallback is not None and isinstance(fallback, expected):
        return fallback
    return None
