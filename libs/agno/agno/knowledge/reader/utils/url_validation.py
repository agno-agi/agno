from typing import List, Optional
from urllib.parse import urlparse


def is_host_allowed(url: str, allowed_hosts: Optional[List[str]]) -> bool:
    """Return True if the URL's hostname is permitted by the allowlist.

    When ``allowed_hosts`` is ``None``, all hosts are allowed (backwards-compatible
    default). When set, only URLs whose hostname matches an entry are allowed
    matching is case-insensitive and exact (no implicit subdomains).

    Args:
        url: The URL to check.
        allowed_hosts: Allowlist of lowercase hostnames, or ``None`` for permissive.

    Returns:
        ``True`` if the URL's host is permitted, ``False`` otherwise.
    """
    if allowed_hosts is None:
        return True
    host = urlparse(url).hostname
    if not host:
        return False
    return host.lower() in allowed_hosts
