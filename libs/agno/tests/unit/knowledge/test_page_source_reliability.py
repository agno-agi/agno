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
    monkeypatch.setattr(PageSource, "retry_base_seconds", 0)
    source = PageSource("https://docs.example.com/llms.txt", None, WorkBudget(5))
    if exhausted:
        with pytest.raises(SyncFailed):
            source.fetch(source.url, 10)
        assert len(seen) == PageSource.fetch_attempts
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


def _source_with(monkeypatch, handle, budget=None):
    """A PageSource whose transport is `handle` and whose retry waits are recorded, not slept."""
    import random

    import dns.resolver

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", lambda *a, **kw: ["93.184.216.34"])
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(random, "uniform", lambda low, high: high)  # no jitter: exact schedule
    source = PageSource("https://docs.example.com/llms.txt", None, budget or WorkBudget(60))
    waits: list[float] = []
    monkeypatch.setattr(source.budget.cancelled, "wait", lambda seconds: waits.append(round(seconds, 3)) or False)
    return source, waits


def test_burst_of_connection_resets_backs_off_and_recovers(monkeypatch):
    seen = []

    def handle(request):
        seen.append(request)
        if len(seen) < 5:
            raise httpx.ConnectError("[Errno 104] Connection reset by peer")
        return httpx.Response(200, content=b"hello")

    source, waits = _source_with(monkeypatch, handle)
    assert source.fetch(source.url, 10) == "hello"
    assert len(seen) == 5 and waits == [0.5, 1.0, 2.0, 4.0]


@pytest.mark.parametrize(
    "failure",
    [
        lambda request: httpx.Response(502),
        lambda request: (_ for _ in ()).throw(httpx.RemoteProtocolError("Server disconnected")),
        lambda request: (_ for _ in ()).throw(httpx.WriteError("broken pipe")),
    ],
)
def test_server_errors_and_dropped_connections_are_retried(monkeypatch, failure):
    seen = []

    def handle(request):
        seen.append(request)
        return failure(request) if len(seen) == 1 else httpx.Response(200, content=b"ok")

    source, waits = _source_with(monkeypatch, handle)
    assert source.fetch(source.url, 10) == "ok" and waits == [0.5]


@pytest.mark.parametrize("header,expected", [("3", 3.0), ("99", 10.0)])
def test_retry_after_is_honored_and_bounded(monkeypatch, header, expected):
    seen = []

    def handle(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(429, headers={"retry-after": header})
        return httpx.Response(200, content=b"ok")

    source, waits = _source_with(monkeypatch, handle)
    assert source.fetch(source.url, 10) == "ok" and waits == [expected]


def test_retry_never_sleeps_past_the_fetch_deadline(monkeypatch):
    def handle(request):
        return httpx.Response(503, headers={"retry-after": "8"})

    source, waits = _source_with(monkeypatch, handle, budget=WorkBudget(5))
    with pytest.raises(SyncFailed) as failed:
        source.fetch(source.url, 10)
    assert waits == [] and isinstance(failed.value.__cause__, httpx.HTTPStatusError)


def test_retry_after_parsing():
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    from agno.knowledge.page._source import _retry_after_seconds

    soon = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30), usegmt=True)
    assert _retry_after_seconds("5") == 5.0
    assert 25 <= (_retry_after_seconds(soon) or 0) <= 30
    assert _retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0
    assert _retry_after_seconds("soon") is None and _retry_after_seconds(None) is None


def test_each_attempt_has_its_own_timeout_so_a_stalled_handshake_is_retried(monkeypatch):
    """A handshake that hangs must time out per attempt, not consume the 30 s fetch deadline."""
    timeouts = []
    seen = []

    def handle(request):
        seen.append(request)
        if len(seen) == 1:
            raise httpx.ConnectTimeout("_ssl.c:1064: The handshake operation timed out")
        return httpx.Response(200, content=b"ok")

    source, waits = _source_with(monkeypatch, handle)
    wrapped = httpx.Client

    def recording_client(**kwargs):
        timeouts.append(kwargs["timeout"])
        return wrapped(**kwargs)

    monkeypatch.setattr(httpx, "Client", recording_client)
    assert source.fetch(source.url, 10) == "ok"
    assert len(seen) == 2 and waits == [0.5]
    assert all(t.connect == 5.0 and t.read == 10.0 for t in timeouts)


def test_attempt_timeout_never_exceeds_the_remaining_deadline(monkeypatch):
    timeouts = []

    def handle(request):
        return httpx.Response(200, content=b"ok")

    source, _ = _source_with(monkeypatch, handle, budget=WorkBudget(3))
    wrapped = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: timeouts.append(kw["timeout"]) or wrapped(**kw))
    assert source.fetch(source.url, 10) == "ok"
    assert timeouts[0].read <= 3 and timeouts[0].connect <= 3
