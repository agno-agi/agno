"""Pinned transport retries and canonical navigation destinations."""

from asyncio import CancelledError

import httpx
import pytest

from agno.knowledge.page import SyncFailed
from agno.knowledge.page._source import PageSource
from agno.utils.bounded import WorkBudget


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadError, httpx.ReadTimeout])
@pytest.mark.parametrize("exhausted", [False, True])
def test_retry_transport_with_pinned_dns(monkeypatch, failure, exhausted):
    import dns.resolver

    seen = []
    monkeypatch.setattr(dns.resolver.Resolver, "resolve", lambda *a, **kw: ["93.184.216.34"])
    original = httpx.Client

    def handle(request):
        seen.append(request)
        if len(seen) == 1 or exhausted:
            raise failure("transient")
        return httpx.Response(200, content=b"hello")

    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    source = PageSource("https://docs.example.com/llms.txt", None, WorkBudget(5))
    if exhausted:
        with pytest.raises(SyncFailed):
            source.fetch(source.url, 10)
        assert len(seen) == 3
    else:
        assert source.fetch(source.url, 10) == "hello"
        assert len(seen) == 2
    assert all(
        r.url.host == "93.184.216.34"
        and r.headers["host"] == "docs.example.com"
        and r.extensions["sni_hostname"] == "docs.example.com"
        for r in seen
    )


@pytest.mark.parametrize("mode", ["foreign", "oversize", "permanent", "cancel"])
def test_unsafe_or_cancelled_fetch_does_not_retry(monkeypatch, mode):
    import dns.resolver

    seen = []
    budget = WorkBudget(5)
    monkeypatch.setattr(dns.resolver.Resolver, "resolve", lambda *a, **kw: ["93.184.216.34"])
    original = httpx.Client

    def handle(request):
        seen.append(request)
        if mode == "foreign":
            return httpx.Response(302, headers={"location": "https://foreign.example.com/page"})
        if mode == "cancel":
            budget.cancelled.set()
            raise httpx.ConnectError("cancelled")
        return httpx.Response(404 if mode == "permanent" else 200, content=b"x" * 11)

    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    source = PageSource("https://docs.example.com/llms.txt", None, budget)
    with pytest.raises((SyncFailed, TimeoutError, CancelledError)):
        source.fetch(source.url, 10)
    assert len(seen) == 1


def test_duplicate_navigation_keeps_first_title(monkeypatch):
    index = "- [First](https://docs.example.com/a)\n- [Second](https://docs.example.com/a.md)\n- [Other](https://docs.example.com/b.md)"
    monkeypatch.setattr(PageSource, "fetch", lambda *a: index)
    source = PageSource("https://docs.example.com/llms.txt", None, WorkBudget(5))
    pages = source.discover()
    assert source.complete and set(pages) == {"/a.md", "/b.md"}
    assert pages["/a.md"].title == "First"
