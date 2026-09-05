"""Resolve a configured public base address without changing the bind address."""

from os import getenv
from typing import Optional
from urllib.parse import urlsplit, urlunsplit


def resolve_url(url: Optional[str]) -> Optional[str]:
    value = url if url is not None else (getenv("AGENTOS_URL") or None)
    if value is None:
        return None
    if not isinstance(value, str) or not value or any(ord(c) <= 32 for c in value) or "\\" in value:
        raise ValueError("AgentOS.url must be an absolute HTTP(S) base URL")
    parts = urlsplit(value)
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("AgentOS.url must be an absolute HTTP(S) base URL without credentials, query or fragment")
    try:
        parts.port
    except ValueError as exc:
        raise ValueError("AgentOS.url has an invalid port") from exc
    if any(segment in (".", "..") for segment in parts.path.split("/")):
        raise ValueError("AgentOS.url has an invalid path")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
