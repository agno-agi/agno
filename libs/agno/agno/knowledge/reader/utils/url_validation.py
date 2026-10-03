from typing import Any, Callable, List, Optional
from urllib.parse import urlparse


def _normalize_host(host: str) -> str:
    """Reduce a hostname to the form the allowlist compares on.

    Two spellings of the same host must normalize to one string, or an exact-match
    allowlist admits one and rejects the other. Case is one such spelling; the
    trailing dot is the other. ``docs.example.com.`` names the root label
    explicitly, which DNS resolves identically to ``docs.example.com`` -- but
    ``urlparse`` keeps the dot, so the two are not ``==``.
    """
    return host.rstrip(".").lower()


def validate_allowed_hosts(allowed_hosts: Optional[List[str]]) -> Optional[List[str]]:
    """Validate an ``allowed_hosts`` argument and raise ``TypeError`` if a single string is passed."""
    if allowed_hosts is None:
        return None
    if isinstance(allowed_hosts, str):
        raise TypeError(
            "allowed_hosts must be a list of hostnames, not a single string. "
            f"Did you mean allowed_hosts=[{allowed_hosts!r}]?"
        )
    return [_normalize_host(host) for host in allowed_hosts]


def is_host_allowed(url: str, allowed_hosts: Optional[List[str]]) -> bool:
    """Return True if the URL's hostname is permitted by the allowlist.

    When ``allowed_hosts`` is ``None``, all hosts are allowed.
    When set, only URLs whose hostname matches an entry are allowed
    matching is case-insensitive and exact (no implicit subdomains).

    Both sides are normalized with :func:`_normalize_host` so that the two DNS
    spellings of one host cannot disagree: without it a URL written
    ``https://docs.example.com./x`` was refused by an allowlist naming
    ``docs.example.com``, and -- the direction that matters for a guard -- an
    allowlist entry copied from a zone file as ``docs.example.com.`` admitted
    only the dotted spelling. The dot survives an httpx redirect hop, so the
    same asymmetry reached :func:`make_redirect_guard`.

    Args:
        url: The URL to check.
        allowed_hosts: Allowlist of hostnames (matched case-insensitively),
            or ``None`` for permissive.

    Returns:
        ``True`` if the URL's host is permitted, ``False`` otherwise.
    """
    if allowed_hosts is None:
        return True
    host = urlparse(url).hostname
    if not host:
        return False
    # ``.`` alone is a hostname of only root labels, which names no host.
    host_normalized = _normalize_host(host)
    if not host_normalized:
        return False
    return any(host_normalized == _normalize_host(entry) for entry in allowed_hosts)


def make_redirect_guard(allowed_hosts: Optional[List[str]]) -> Optional[Callable[[Any], None]]:
    """Build a *sync* httpx request event-hook that refuses redirects to disallowed hosts.

    Use this with ``httpx.Client``. For ``httpx.AsyncClient`` use
    :func:`make_async_redirect_guard` — httpx enforces that AsyncClient hooks be
    coroutines, so the two cannot share a single implementation.

    httpx invokes the ``request`` event hook for every outbound request including
    those issued by 3xx redirect-following. Pair this with ``follow_redirects=True``
    so legitimate same-host redirects work, while cross-host redirects to addresses
    outside the allowlist raise an error before the request is sent.

    Returns ``None`` when ``allowed_hosts`` is ``None`` so callers can omit the hook
    entirely in the permissive default case.
    """
    if allowed_hosts is None:
        return None

    def _guard(request: Any) -> None:
        if not is_host_allowed(str(request.url), allowed_hosts):
            import httpx

            raise httpx.RequestError(f"Host not in allowed_hosts: {request.url.host}", request=request)

    return _guard


def make_async_redirect_guard(allowed_hosts: Optional[List[str]]) -> Optional[Callable[[Any], Any]]:
    """Async counterpart to :func:`make_redirect_guard` for use with ``httpx.AsyncClient``.

    httpx awaits AsyncClient event hooks, so they must be ``async def`` callables —
    the sync version blows up with "object NoneType can't be used in 'await' expression"
    when handed to an AsyncClient.
    """
    if allowed_hosts is None:
        return None

    async def _guard(request: Any) -> None:
        if not is_host_allowed(str(request.url), allowed_hosts):
            import httpx

            raise httpx.RequestError(f"Host not in allowed_hosts: {request.url.host}", request=request)

    return _guard
