"""A cache that lives for exactly one request.

One authorized request asks the policy store the same questions several times: the
route gate decides, then the per-resource gate decides again, and a list endpoint
additionally resolves the accessible and the denied id sets. Each of those recomputes
the caller's role closure and policy rows from scratch -- 2x on a resource GET, 4x on
a listing, every one of them identical and microseconds apart.

This memoizes those reads for the duration of a single request and throws the cache
away with it. That is deliberately NOT the in-process cache
:class:`~agno.os.authz.native_engine.NativePolicyEngine` refuses to keep: the point of
that refusal is that a revocation on one replica must be visible to every other replica
on their next request, and a per-request cache preserves that exactly -- it cannot
outlive the request that created it, so the next request everywhere reads fresh. Any
mutation through the store also clears it, so a role change made inside a request is
visible to the rest of that same request.

Scoped with a ``ContextVar`` rather than passed through the provider seam, so third-party
:class:`~agno.os.authz.provider.AuthorizationProvider` implementations neither see it nor
need to cooperate. Context is copied into threadpool workers, so it survives the
``run_in_threadpool`` hop FastAPI makes for sync dependencies.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Dict, Iterator, Optional, TypeVar

_CACHE: ContextVar[Optional[Dict[Any, Any]]] = ContextVar("agno_authz_request_cache", default=None)

T = TypeVar("T")


@contextmanager
def request_scope() -> Iterator[None]:
    """Give the enclosed block its own authorization cache.

    Nested use is a no-op: the outermost scope owns the cache, so a sub-application
    (the mounted MCP app) cannot reset the cache of the request that dispatched to it.
    """
    if _CACHE.get() is not None:
        yield  # already inside a scope; keep the existing cache
        return
    token = _CACHE.set({})
    try:
        yield
    finally:
        _CACHE.reset(token)


def memoize(key: Any, compute: Callable[[], T]) -> T:
    """Return ``compute()``, reusing this request's answer for ``key`` if there is one.

    Outside a request scope this is a plain call -- no caching, no behaviour change,
    which is what direct/administrative use of the store gets.
    """
    cache = _CACHE.get()
    if cache is None:
        return compute()
    if key not in cache:
        cache[key] = compute()
    return cache[key]


def invalidate() -> None:
    """Drop everything memoized so far in this request.

    Called on every policy mutation: a request that changes roles and then asks a
    question must see its own write.
    """
    cache = _CACHE.get()
    if cache is not None:
        cache.clear()
