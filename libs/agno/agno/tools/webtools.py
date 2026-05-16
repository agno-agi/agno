import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from agno.tools import Toolkit
from agno.utils.log import logger


_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("0.0.0.0/8"),
]

_BLOCKED_IPV6_NETWORKS = [
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_safe_url(url: str) -> tuple[bool, str]:
    """Return (is_safe, reason). Blocks private/reserved IP ranges."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, f"scheme '{parsed.scheme}' not allowed"
        if not parsed.hostname:
            return False, "missing hostname"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(parsed.hostname, port)
    except socket.gaierror:
        return False, f"cannot resolve '{parsed.hostname}'"
    except Exception as exc:
        return False, str(exc)

    for _family, _, _, _, sockaddr in infos:
        try:
            addr = ipaddress.ip_address(sockaddr[0])
            if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
                addr = addr.ipv4_mapped
            nets = _BLOCKED_NETWORKS if isinstance(addr, ipaddress.IPv4Address) else _BLOCKED_IPV6_NETWORKS
            if any(addr in net for net in nets):
                return False, f"resolves to private/reserved IP {addr}"
        except ValueError:
            return False, f"invalid address '{sockaddr[0]}'"

    return True, ""


class WebTools(Toolkit):
    """
    A toolkit for working with web-related tools.
    """

    def __init__(
        self,
        retries: int = 3,
        enable_expand_url: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.retries = retries

        tools = []
        if all or enable_expand_url:
            tools.append(self.expand_url)

        super().__init__(name="web_tools", tools=tools, **kwargs)

    def expand_url(self, url: str) -> str:
        """
        Expands a shortened URL to its final destination using HTTP HEAD requests with retries.
        Only public URLs are followed; requests to private/internal addresses are blocked.

        :param url: The URL to expand.

        :return: The final destination URL if successful; otherwise, returns the original URL.
        """
        safe, reason = _is_safe_url(url)
        if not safe:
            logger.warning(f"expand_url: blocked {url!r}: {reason}")
            return url

        timeout = 5
        current_url = url
        for attempt in range(1, self.retries + 1):
            try:
                response = httpx.head(current_url, follow_redirects=False, timeout=timeout)
                if response.is_redirect:
                    location = response.headers.get("location", "")
                    if not location:
                        return current_url
                    safe, reason = _is_safe_url(location)
                    if not safe:
                        logger.warning(f"expand_url: redirect to {location!r} blocked: {reason}")
                        return current_url
                    current_url = location
                    continue
                logger.info(f"expand_url: {url} expanded to {current_url} on attempt {attempt}")
                return current_url
            except Exception:
                logger.exception(f"Error expanding URL {current_url} on attempt {attempt}")

        return url
