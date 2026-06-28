from dataclasses import dataclass, fields
from datetime import timedelta
from typing import Any, Dict, Optional


@dataclass
class SSEClientParams:
    """Parameters for SSE client connection."""

    url: str
    headers: Optional[Dict[str, Any]] = None
    timeout: Optional[float] = 5
    sse_read_timeout: Optional[float] = 60 * 5


@dataclass
class StreamableHTTPClientParams:
    """Parameters for Streamable HTTP client connection."""

    url: str
    headers: Optional[Dict[str, Any]] = None
    timeout: Optional[timedelta] = timedelta(seconds=30)
    sse_read_timeout: Optional[timedelta] = timedelta(seconds=60 * 5)
    terminate_on_close: Optional[bool] = None
    http_client: Optional[Any] = None


def streamable_http_client_kwargs(
    server_params: Optional[StreamableHTTPClientParams] = None,
    *,
    url: Optional[str] = None,
    http_client: Any = None,
) -> dict[str, Any]:
    """Build kwargs for ``streamablehttp_client`` without copying values."""
    kwargs: dict[str, Any] = {}

    if server_params is not None:
        for field in fields(StreamableHTTPClientParams):
            value = getattr(server_params, field.name)
            if field.name == "http_client" and value is None:
                continue
            kwargs[field.name] = value
    elif url is not None:
        kwargs["url"] = url

    if http_client is not None and "http_client" not in kwargs:
        kwargs["http_client"] = http_client

    return kwargs
