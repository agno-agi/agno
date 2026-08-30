"""Unit tests for the page-fetcher seam below the URL readers.

HttpxPageFetcher is exercised through httpx.MockTransport (no network); the
ParallelPageFetcher retry/breaker/fallback plumbing is exercised with stub
backends and fallbacks so every provider behavior is scripted.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from typing import List, Optional
from unittest.mock import patch

import httpx
import pytest

from agno.knowledge.reader.page_fetcher import (
    FetchedPage,
    HttpxPageFetcher,
    ParallelPageFetcher,
    RateLimited,
    RateLimitPolicy,
    rate_limit_from_text,
)

HTML_PAGE = """
<html>
  <head><title>Test Page</title></head>
  <body>
    <nav>Navigation links here</nav>
    <main>Main content paragraph.</main>
    <footer>Footer text here</footer>
  </body>
</html>
"""

PLAIN_TEXT = "just plain text, no markup"

RSS_BODY = '<?xml version="1.0"?><rss><channel><title>Feed</title></channel></rss>'


def _site_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/page":
        return httpx.Response(200, content=HTML_PAGE.encode(), headers={"content-type": "text/html; charset=utf-8"})
    if path == "/plain":
        return httpx.Response(200, content=PLAIN_TEXT.encode(), headers={"content-type": "text/plain"})
    if path == "/rss":
        return httpx.Response(200, content=RSS_BODY.encode(), headers={"content-type": "application/rss+xml"})
    if path == "/missing":
        return httpx.Response(404, content=b"gone")
    if path == "/redirect":
        return httpx.Response(302, headers={"location": "https://evil.com/page"})
    return httpx.Response(200, content=b"<html><body>other</body></html>", headers={"content-type": "text/html"})


def _install_transport(monkeypatch, handler):
    """Route the fetcher's own httpx clients through a MockTransport; returns the request log."""
    requests: List[httpx.Request] = []

    def tracking_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    transport = httpx.MockTransport(tracking_handler)
    real_client, real_async_client = httpx.Client, httpx.AsyncClient

    def client(**kwargs):
        kwargs["transport"] = transport
        return real_client(**kwargs)

    def async_client(**kwargs):
        kwargs["transport"] = transport
        return real_async_client(**kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr(httpx, "AsyncClient", async_client)
    return requests


# --- HttpxPageFetcher ---


def test_html_page_extracts_main_content(monkeypatch):
    _install_transport(monkeypatch, _site_handler)
    page = HttpxPageFetcher().fetch_many(["https://example.com/page"])[0]

    assert page.ok
    assert page.error is None
    assert "Main content paragraph." in page.content
    assert "Navigation links" not in page.content
    assert "Footer text" not in page.content
    assert page.title == "Test Page"
    assert page.extractor == "httpx"
    assert page.attempts == [{"extractor": "httpx", "outcome": "ok"}]


def test_plain_text_passes_through_raw(monkeypatch):
    _install_transport(monkeypatch, _site_handler)
    page = HttpxPageFetcher().fetch_many(["https://example.com/plain"])[0]

    assert page.ok
    assert page.content == PLAIN_TEXT
    assert page.title is None
    assert page.attempts == [{"extractor": "httpx", "outcome": "ok"}]


def test_non_html_content_type_is_an_error(monkeypatch):
    _install_transport(monkeypatch, _site_handler)
    page = HttpxPageFetcher().fetch_many(["https://example.com/rss"])[0]

    assert not page.ok
    assert page.content is None
    assert page.error.startswith("not-html")
    assert "application/rss+xml" in page.error
    assert page.attempts == [{"extractor": "httpx", "outcome": page.error}]


def test_http_404_is_an_error(monkeypatch):
    _install_transport(monkeypatch, _site_handler)
    page = HttpxPageFetcher().fetch_many(["https://example.com/missing"])[0]

    assert not page.ok
    assert page.error == "HTTP 404"
    assert page.attempts == [{"extractor": "httpx", "outcome": "HTTP 404"}]


def test_off_host_url_refused_without_a_request(monkeypatch):
    requests = _install_transport(monkeypatch, _site_handler)
    pages = HttpxPageFetcher().fetch_many(
        ["https://example.com/page", "https://other.com/page"], allowed_hosts=["example.com"]
    )

    assert pages[0].ok
    assert pages[1].error == "off-host"
    assert pages[1].content is None
    # Refused before any request went out: nothing was tried, so no attempt is recorded.
    assert pages[1].attempts == []
    assert [request.url.host for request in requests] == ["example.com"]


def test_redirect_to_off_host_is_guarded(monkeypatch):
    requests = _install_transport(monkeypatch, _site_handler)
    page = HttpxPageFetcher().fetch_many(["https://example.com/redirect"], allowed_hosts=["example.com"])[0]

    assert not page.ok
    assert "Host not in allowed_hosts: evil.com" in page.error
    assert page.attempts == [{"extractor": "httpx", "outcome": page.error}]
    # The redirect guard fired before the request to evil.com was sent.
    assert [request.url.host for request in requests] == ["example.com"]


@pytest.mark.asyncio
async def test_async_concurrency_wires_semaphore(monkeypatch):
    _install_transport(monkeypatch, _site_handler)
    recorded: List[int] = []
    real_semaphore = asyncio.Semaphore

    class RecordingSemaphore(real_semaphore):
        def __init__(self, value: int = 1):
            recorded.append(value)
            super().__init__(value)

    monkeypatch.setattr(asyncio, "Semaphore", RecordingSemaphore)
    fetcher = HttpxPageFetcher(concurrency=2)
    pages = await fetcher.afetch_many(["https://example.com/page"])

    assert pages[0].ok
    assert recorded == [2]


@pytest.mark.asyncio
async def test_sync_and_async_return_same_shapes(monkeypatch):
    _install_transport(monkeypatch, _site_handler)
    urls = [
        "https://example.com/page",
        "https://example.com/plain",
        "https://example.com/rss",
        "https://example.com/missing",
        "https://example.com/redirect",
        "https://other.com/page",
    ]
    fetcher = HttpxPageFetcher()
    sync_pages = fetcher.fetch_many(urls, allowed_hosts=["example.com"])
    async_pages = await fetcher.afetch_many(urls, allowed_hosts=["example.com"])

    assert len(sync_pages) == len(async_pages) == len(urls)
    for sync_page, async_page, url in zip(sync_pages, async_pages, urls):
        assert sync_page.url == async_page.url == url
        assert sync_page.content == async_page.content
        assert sync_page.error == async_page.error
        assert sync_page.title == async_page.title
        assert sync_page.extractor == async_page.extractor == "httpx"


# --- ParallelPageFetcher stubs ---


def _ok_pages(urls: List[str]) -> List[FetchedPage]:
    return [FetchedPage(url=url, content=f"primary:{url}", extractor="parallel") for url in urls]


class StubBackend:
    """Scripted backend: each call serves the next script entry (exception -> raised,
    callable -> its pages); the last entry repeats forever."""

    extractor_id = "parallel"

    def __init__(self, script, fetch_batch_limit: int = 20):
        self.script = list(script)
        self.fetch_batch_limit = fetch_batch_limit
        self.calls: List[List[str]] = []

    def _serve(self, urls: List[str]) -> List[FetchedPage]:
        self.calls.append(list(urls))
        entry = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(entry, Exception):
            raise entry
        return entry(urls)

    def fetch_many(self, urls: List[str], *, max_chars: int = 50_000) -> List[FetchedPage]:
        return self._serve(urls)

    async def afetch_many(self, urls: List[str], *, max_chars: int = 50_000) -> List[FetchedPage]:
        return self._serve(urls)


class StubFallback:
    """Recording fallback fetcher that always succeeds."""

    extractor_id = "stub"

    def __init__(self):
        self.sync_calls: List[tuple] = []
        self.async_calls: List[tuple] = []

    def _pages(self, urls: List[str]) -> List[FetchedPage]:
        return [
            FetchedPage(
                url=url,
                content=f"fallback:{url}",
                extractor=self.extractor_id,
                attempts=[{"extractor": self.extractor_id, "outcome": "ok"}],
            )
            for url in urls
        ]

    def fetch_many(self, urls: List[str], *, allowed_hosts: Optional[List[str]] = None) -> List[FetchedPage]:
        self.sync_calls.append((list(urls), allowed_hosts))
        return self._pages(urls)

    async def afetch_many(self, urls: List[str], *, allowed_hosts: Optional[List[str]] = None) -> List[FetchedPage]:
        self.async_calls.append((list(urls), allowed_hosts))
        return self._pages(urls)


# --- ParallelPageFetcher backend resolution ---


def test_backend_resolves_to_none_without_key_or_packages(monkeypatch):
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    monkeypatch.setattr("agno.knowledge.reader.page_fetcher.find_spec", lambda name: None)
    fallback = StubFallback()
    fetcher = ParallelPageFetcher(fallback=fallback)

    assert fetcher.backend is None
    # With no backend, the fetcher reports the fallback's identity and batches degenerate to 1.
    assert fetcher.extractor_id == "stub"
    assert fetcher.batch_size == 1


@pytest.mark.asyncio
async def test_no_backend_delegates_async_to_fallback(monkeypatch):
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    monkeypatch.setattr("agno.knowledge.reader.page_fetcher.find_spec", lambda name: None)
    fallback = StubFallback()
    fetcher = ParallelPageFetcher(fallback=fallback)

    pages = await fetcher.afetch_many(["https://a.com/x"], allowed_hosts=["a.com"])

    assert fallback.async_calls == [(["https://a.com/x"], ["a.com"])]
    assert pages[0].content == "fallback:https://a.com/x"


def test_no_backend_delegates_sync_to_fallback(monkeypatch):
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    monkeypatch.setattr("agno.knowledge.reader.page_fetcher.find_spec", lambda name: None)
    fallback = StubFallback()
    fetcher = ParallelPageFetcher(fallback=fallback)

    pages = fetcher.fetch_many(["https://a.com/x"])

    assert fallback.sync_calls == [(["https://a.com/x"], None)]
    assert pages[0].content == "fallback:https://a.com/x"


def test_explicit_backend_reports_backend_extractor_and_batch_limit():
    backend = StubBackend([_ok_pages], fetch_batch_limit=3)
    fetcher = ParallelPageFetcher(backend=backend, fallback=StubFallback(), batch_size=10)

    assert fetcher.backend is backend
    assert fetcher.extractor_id == "parallel"
    assert fetcher.batch_size == 3


# --- ParallelPageFetcher retry / breaker / fallback ---


@pytest.mark.asyncio
async def test_rate_limited_once_then_success_sleeps_retry_after():
    backend = StubBackend([RateLimited("429", retry_after=0.01), _ok_pages])
    fetcher = ParallelPageFetcher(backend=backend, fallback=StubFallback())

    with patch("asyncio.sleep") as mock_sleep:
        pages = await fetcher.afetch_many(["https://a.com/1"])

    mock_sleep.assert_awaited_once_with(0.01)
    assert len(backend.calls) == 2
    assert pages[0].content == "primary:https://a.com/1"
    assert pages[0].attempts == [
        {"extractor": "parallel", "outcome": "rate-limited"},
        {"extractor": "parallel", "outcome": "ok"},
    ]


@pytest.mark.asyncio
async def test_retries_exhausted_batch_falls_to_fallback():
    policy = RateLimitPolicy(max_retries=1, breaker_after=10)
    backend = StubBackend([RateLimited("429", retry_after=0.0)])
    fallback = StubFallback()
    fetcher = ParallelPageFetcher(backend=backend, fallback=fallback, policy=policy)
    urls = ["https://a.com/1", "https://a.com/2"]

    with patch("asyncio.sleep") as mock_sleep:
        pages = await fetcher.afetch_many(urls)

    assert len(backend.calls) == 2  # initial attempt + 1 retry
    assert mock_sleep.await_count == 1
    assert fallback.async_calls == [(urls, None)]
    assert [page.url for page in pages] == urls
    for page in pages:
        assert page.content == f"fallback:{page.url}"
        assert page.attempts == [
            {"extractor": "parallel", "outcome": "rate-limited"},
            {"extractor": "parallel", "outcome": "rate-limited"},
            {"extractor": "stub", "outcome": "ok"},
        ]


def test_breaker_trips_and_skips_backend_for_remaining_batches(caplog):
    policy = RateLimitPolicy(max_retries=0, breaker_after=2)
    backend = StubBackend([RateLimited("429")], fetch_batch_limit=1)
    fallback = StubFallback()
    fetcher = ParallelPageFetcher(backend=backend, fallback=fallback, policy=policy)
    urls = ["https://a.com/1", "https://a.com/2", "https://a.com/3"]

    # The agno logger does not propagate to root, so attach caplog's handler directly.
    agno_logger = logging.getLogger("agno")
    agno_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger="agno"):
            pages = fetcher.fetch_many(urls)
    finally:
        agno_logger.removeHandler(caplog.handler)

    # Two rate-limited batches trip the breaker; the third never reaches the backend.
    assert backend.calls == [["https://a.com/1"], ["https://a.com/2"]]
    assert [page.content for page in pages] == [f"fallback:{url}" for url in urls]
    rate_limited_logs = [record for record in caplog.records if "rate-limited" in record.getMessage()]
    assert len(rate_limited_logs) == 1


@pytest.mark.asyncio
async def test_per_page_fallback_keeps_ok_pages_and_merges_attempts():
    def serve(urls: List[str]) -> List[FetchedPage]:
        return [
            FetchedPage(url=urls[0], content=f"primary:{urls[0]}", extractor="parallel"),
            FetchedPage(url=urls[1], error="provider-error", extractor="parallel"),
        ]

    backend = StubBackend([serve])
    fallback = StubFallback()
    fetcher = ParallelPageFetcher(backend=backend, fallback=fallback)
    urls = ["https://a.com/ok", "https://a.com/bad"]

    pages = await fetcher.afetch_many(urls)

    assert [page.url for page in pages] == urls
    assert pages[0].content == "primary:https://a.com/ok"
    assert pages[0].extractor == "parallel"
    assert pages[0].attempts == [{"extractor": "parallel", "outcome": "ok"}]
    assert pages[1].content == "fallback:https://a.com/bad"
    assert pages[1].extractor == "stub"
    assert pages[1].attempts == [
        {"extractor": "parallel", "outcome": "provider-error"},
        {"extractor": "stub", "outcome": "ok"},
    ]
    # Only the failed page was refetched.
    assert fallback.async_calls == [(["https://a.com/bad"], None)]


def test_duplicate_urls_fetched_once_result_matches_input_order():
    backend = StubBackend([_ok_pages])
    fetcher = ParallelPageFetcher(backend=backend, fallback=StubFallback())
    urls = ["https://a.com/1", "https://a.com/2", "https://a.com/1"]

    pages = fetcher.fetch_many(urls)

    assert backend.calls == [["https://a.com/1", "https://a.com/2"]]
    assert [page.url for page in pages] == urls
    assert pages[0].content == pages[2].content == "primary:https://a.com/1"


def test_off_host_urls_never_reach_backend():
    backend = StubBackend([_ok_pages])
    fetcher = ParallelPageFetcher(backend=backend, fallback=StubFallback())
    urls = ["https://a.com/1", "https://evil.com/1"]

    pages = fetcher.fetch_many(urls, allowed_hosts=["a.com"])

    assert backend.calls == [["https://a.com/1"]]
    assert pages[0].content == "primary:https://a.com/1"
    assert pages[1].error == "off-host"


# --- RateLimitPolicy delay behavior ---


def test_exponential_backoff_when_not_honoring_retry_after():
    policy = RateLimitPolicy(max_retries=3, honor_retry_after=False, base_delay=1.0, max_delay=2.0, breaker_after=99)
    backend = StubBackend([RateLimited("429", retry_after=50.0)])
    fallback = StubFallback()
    fetcher = ParallelPageFetcher(backend=backend, fallback=fallback, policy=policy)

    with patch("time.sleep") as mock_sleep:
        pages = fetcher.fetch_many(["https://a.com/1"])

    # retry_after is ignored: base_delay * 2**attempt, capped at max_delay.
    assert [call.args[0] for call in mock_sleep.call_args_list] == [1.0, 2.0, 2.0]
    assert pages[0].content == "fallback:https://a.com/1"


def test_honored_retry_after_is_capped_at_max_delay():
    policy = RateLimitPolicy(max_retries=1, max_delay=2.0, breaker_after=99)
    backend = StubBackend([RateLimited("429", retry_after=50.0)])
    fetcher = ParallelPageFetcher(backend=backend, fallback=StubFallback(), policy=policy)

    with patch("time.sleep") as mock_sleep:
        fetcher.fetch_many(["https://a.com/1"])

    assert [call.args[0] for call in mock_sleep.call_args_list] == [2.0]


# --- import hygiene ---


def test_page_fetcher_import_does_not_load_agent_or_context():
    code = (
        "import sys\n"
        "import agno.knowledge.reader.page_fetcher\n"
        "assert 'agno.agent' not in sys.modules, 'agno.agent loaded'\n"
        "assert 'agno.context' not in sys.modules, 'agno.context loaded'\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_context_web_import_does_not_load_agent():
    code = "import sys\nimport agno.context.web\nassert 'agno.agent' not in sys.modules, 'agno.agent loaded'\n"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# --- rate_limit_from_text ---


def test_rate_limit_from_text():
    assert rate_limit_from_text("HTTP 429 Too Many Requests")
    assert rate_limit_from_text("Rate Limit hit")
    assert not rate_limit_from_text("ok")
