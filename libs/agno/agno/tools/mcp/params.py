from dataclasses import dataclass
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
    """Parameters for Streamable HTTP client connection.

    ``timeout`` and ``sse_read_timeout`` are expressed in seconds. The MCP SDK
    v2 ``streamable_http_client`` no longer accepts these as keyword arguments;
    agno maps them onto an ``httpx2.Timeout`` on the ``http_client`` it builds
    for the connection. ``timeout`` covers connect/write/pool operations while
    ``sse_read_timeout`` bounds the long-lived stream read.
    """

    url: str
    headers: Optional[Dict[str, Any]] = None
    timeout: Optional[float] = 30
    sse_read_timeout: Optional[float] = 60 * 5
    terminate_on_close: Optional[bool] = None
