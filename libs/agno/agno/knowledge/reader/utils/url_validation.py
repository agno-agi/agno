import ipaddress
import socket
from typing import Any, Callable, List, Optional
from urllib.parse import urlparse


def validate_allowed_hosts(allowed_hosts: Optional[List[str]]) -> Optional[List[str]]:
    """Validate an ``allowed_hosts`` argument and raise ``TypeError`` if a single string is passed."""
    if allowed_hosts is None:
        return None
    if isinstance(allowed_hosts, str):
        raise TypeError(
            "allowed_hosts must be a list of hostnames, not a single string. "
            f"Did you mean allowed_hosts=[{allowed_hosts!r}]?"
        )
    return [host.lower() for host in allowed_hosts]


_BLOCKED_IPV4 = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("0.0.0.0/8"),
]

_BLOCKED_IPV6 = [
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _resolves_to_private(hostname: str, port: int = 80) -> bool:
    """Return True if hostname resolves to a private/reserved IP (SSRF protection)."""
    try:
        infos = socket.getaddrinfo(hostname, port)
    except socket.gaierror:
        return True  # can't resolve → block
    for _family, _, _, _, sockaddr in infos:
        try:
            addr = ipaddress.ip_address(sockaddr[0])
            if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
                addr = addr.ipv4_mapped
            nets = _BLOCKED_IPV4 if isinstance(addr, ipaddress.IPv4Address) else _BLOCKED_IPV6
            if any(addr in net for net in nets):
                return True
        except ValueError:
            return True
    return False


def is_host_allowed(url: str, allowed_hosts: Optional[List[str]]) -> bool:
    """Return True if the URL's hostname is permitted.

    Always blocks private/reserved IP ranges to prevent SSRF regardless of
    the ``allowed_hosts`` setting. When ``allowed_hosts`` is additionally set,
    restricts to only those hostnames.

    Args:
        url: The URL to check.
        allowed_hosts: Allowlist of hostnames (case-insensitive exact match),
            or ``None`` to allow any *public* host.

    Returns:
        ``True`` if the URL's host is permitted and resolves to a public IP.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if _resolves_to_private(host, port):
        return False

    if allowed_hosts is None:
        return True

    host_lower = host.lower()
    return any(host_lower == entry.lower() for entry in allowed_hosts)


def make_redirect_guard(allowed_hosts: Optional[List[str]]) -> Callable[[Any], None]:
    """Build a *sync* httpx request event-hook that blocks unsafe redirects.

    Always blocks redirects to private/reserved IP ranges (SSRF prevention).
    When ``allowed_hosts`` is set, also restricts to those hostnames.

    Use this with ``httpx.Client(event_hooks={"request": [guard]})``.
    For ``httpx.AsyncClient`` use :func:`make_async_redirect_guard`.
    """
    def _guard(request: Any) -> None:
        if not is_host_allowed(str(request.url), allowed_hosts):
            import httpx

            raise httpx.RequestError(
                f"Redirect to disallowed host blocked: {request.url.host}", request=request
            )

    return _guard


def make_async_redirect_guard(allowed_hosts: Optional[List[str]]) -> Callable[[Any], Any]:
    """Async counterpart to :func:`make_redirect_guard` for use with ``httpx.AsyncClient``."""

    async def _guard(request: Any) -> None:
        if not is_host_allowed(str(request.url), allowed_hosts):
            import httpx

            raise httpx.RequestError(
                f"Redirect to disallowed host blocked: {request.url.host}", request=request
            )

    return _guard
