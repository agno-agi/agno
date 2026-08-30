"""Page fetching for URL readers.

One seam below the readers: a ``PageFetcher`` turns a list of page URLs into whole-page text,
recording per page which extractor produced it and what was tried. ``HttpxPageFetcher`` is the
built-in fetcher that always works; ``ParallelPageFetcher`` uses Parallel's extraction API when
a key or the ``mcp`` package is available and falls back to the built-in fetcher per page.

Fetchers hold no per-read state — readers are shared objects and reads run concurrently — so
every ``fetch_many``/``afetch_many`` call keeps its bookkeeping in locals.
"""

import asyncio
import time
from dataclasses import dataclass, field
from importlib.util import find_spec
from os import getenv
from typing import TYPE_CHECKING, Dict, List, Optional, Protocol, Set, runtime_checkable

import httpx

from agno.knowledge.reader.utils.url_validation import (
    is_host_allowed,
    make_async_redirect_guard,
    make_redirect_guard,
)
from agno.utils.log import log_debug, log_info

try:
    from bs4 import BeautifulSoup  # noqa: F401
except ImportError:
    raise ImportError("The `bs4` package is not installed. Please install it via `pip install beautifulsoup4`.")

if TYPE_CHECKING:
    from agno.context.backend import ContextBackend


_TEXT_CONTENT_TYPES = ("text/plain", "text/markdown")
_DEFAULT_MAX_CHARS = 50_000


@dataclass
class FetchedPage:
    """One page's fetch result: the whole page as text, unchunked, with provenance."""

    url: str
    content: Optional[str] = None
    title: Optional[str] = None
    extractor: str = "httpx"
    error: Optional[str] = None
    attempts: List[Dict[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.content)


class RateLimited(Exception):
    """A provider said to slow down. ``retry_after`` is seconds when the provider named one."""

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class RateLimitPolicy:
    """How a provider-backed fetcher behaves when the provider rate-limits.

    A rate-limited request sleeps (``retry_after`` when the provider sent one, else exponential
    from ``base_delay`` capped at ``max_delay``) and retries up to ``max_retries`` times before
    that batch falls through to the fallback fetcher. After ``breaker_after`` consecutive
    rate-limited requests the provider is skipped for the remainder of the read.
    """

    max_retries: int = 3
    honor_retry_after: bool = True
    base_delay: float = 1.0
    max_delay: float = 30.0
    breaker_after: int = 5


@runtime_checkable
class PageFetcher(Protocol):
    """Turns page URLs into ``FetchedPage`` results, in input order, never raising per page."""

    def fetch_many(self, urls: List[str], *, allowed_hosts: Optional[List[str]] = None) -> List[FetchedPage]: ...

    async def afetch_many(self, urls: List[str], *, allowed_hosts: Optional[List[str]] = None) -> List[FetchedPage]: ...


def extract_page_text(html: str) -> str:
    """Main-content text from an HTML page: chrome removed, block structure kept as newlines."""
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "nav", "header", "footer", "aside"]):
        element.decompose()
    main = soup.find("main") or soup.find("article") or soup.find(role="main") or soup.body or soup
    return main.get_text(separator="\n", strip=True)


def extract_page_title(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        return soup.title.string.strip() or None
    return None


def _pdf_page_text(url: str, raw: bytes) -> FetchedPage:
    """Extract a PDF's text as one page. Needs the ``pdf`` extra; absence is a page
    error naming the install, never an exception through the read."""
    import io

    try:
        from agno.knowledge.reader.pdf_reader import PDFReader
    except ImportError:
        return FetchedPage(url=url, error="pdf support requires the `agno[pdf]` extra (pypdf)", extractor="httpx")
    try:
        documents = PDFReader(chunk=False).read(io.BytesIO(raw), name=url)
    except Exception as e:
        return FetchedPage(url=url, error=f"pdf: {type(e).__name__}: {e}"[:300], extractor="httpx")
    text = "\n\n".join(doc.content for doc in documents if doc.content)
    if not text:
        return FetchedPage(url=url, error="empty", extractor="httpx")
    return FetchedPage(url=url, content=text, extractor="httpx")


def _page_from_response(url: str, response: httpx.Response) -> FetchedPage:
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type == "application/pdf" or response.content[:5] == b"%PDF-":
        page = _pdf_page_text(url, response.content)
        if page.error:
            return page
    else:
        body = response.text
        if content_type in _TEXT_CONTENT_TYPES:
            page = FetchedPage(url=url, content=body, extractor="httpx")
        elif content_type == "text/html" or body.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
            page = FetchedPage(
                url=url, content=extract_page_text(body), title=extract_page_title(body), extractor="httpx"
            )
        else:
            return FetchedPage(url=url, error=f"not-html ({content_type or 'unknown content type'})", extractor="httpx")
    if not page.content:
        return FetchedPage(url=url, title=page.title, error="empty", extractor="httpx")
    return page


def _failure_reason(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return f"{type(exc).__name__}: {exc}"


class HttpxPageFetcher:
    """The fetcher that always works: httpx + BeautifulSoup, no key, no crawl delay.

    Fetching a list the caller already chose is not crawling, so there is no politeness sleep;
    ``concurrency`` bounds how many requests are in flight at once instead.
    """

    extractor_id = "httpx"

    def __init__(self, *, concurrency: int = 8, timeout: int = 30, proxy: Optional[str] = None):
        self.concurrency = concurrency
        self.timeout = timeout
        self.proxy = proxy

    def _fetch_one(self, client: httpx.Client, url: str, allowed_hosts: Optional[List[str]]) -> FetchedPage:
        if not is_host_allowed(url, allowed_hosts):
            return FetchedPage(url=url, error="off-host", extractor=self.extractor_id)
        try:
            response = client.get(url, follow_redirects=True)
            response.raise_for_status()
            page = _page_from_response(url, response)
        except Exception as e:
            page = FetchedPage(url=url, error=_failure_reason(e), extractor=self.extractor_id)
        page.attempts.append({"extractor": self.extractor_id, "outcome": page.error or "ok"})
        return page

    def fetch_many(self, urls: List[str], *, allowed_hosts: Optional[List[str]] = None) -> List[FetchedPage]:
        guard = make_redirect_guard(allowed_hosts)
        event_hooks = {"request": [guard]} if guard else None
        with httpx.Client(timeout=self.timeout, proxy=self.proxy, event_hooks=event_hooks) as client:  # type: ignore[arg-type]
            return [self._fetch_one(client, url, allowed_hosts) for url in urls]

    async def afetch_many(self, urls: List[str], *, allowed_hosts: Optional[List[str]] = None) -> List[FetchedPage]:
        guard = make_async_redirect_guard(allowed_hosts)
        event_hooks = {"request": [guard]} if guard else None
        semaphore = asyncio.Semaphore(self.concurrency)

        async with httpx.AsyncClient(timeout=self.timeout, proxy=self.proxy, event_hooks=event_hooks) as client:  # type: ignore[arg-type]

            async def fetch_one(url: str) -> FetchedPage:
                if not is_host_allowed(url, allowed_hosts):
                    return FetchedPage(url=url, error="off-host", extractor=self.extractor_id)
                async with semaphore:
                    try:
                        response = await client.get(url, follow_redirects=True)
                        response.raise_for_status()
                        page = _page_from_response(url, response)
                    except Exception as e:
                        page = FetchedPage(url=url, error=_failure_reason(e), extractor=self.extractor_id)
                page.attempts.append({"extractor": self.extractor_id, "outcome": page.error or "ok"})
                return page

            return list(await asyncio.gather(*[fetch_one(url) for url in urls]))


class ParallelPageFetcher:
    """Parallel's extraction API with the built-in fetcher as the per-page fallback.

    ``allowed_hosts`` is enforced on the submitted URL; the provider fetches on its own
    infrastructure and may follow a site's redirects, which this client cannot observe or
    veto (unlike the built-in fetcher, whose redirect guard blocks off-host hops). A page
    behind an off-host redirect comes back labeled with the submitted URL. Use
    ``HttpxPageFetcher`` when redirect-boundary enforcement matters more than extraction
    quality.

    The backend is resolved once, at construction, silently: the keyed SDK when
    ``PARALLEL_API_KEY`` (or ``api_key``) is set and ``parallel`` is importable, else the
    keyless MCP endpoint when ``mcp`` is importable, else this fetcher *is* the built-in
    fetcher. Provider rate limits are retried per ``RateLimitPolicy`` (a retrying task keeps
    its concurrency slot, which throttles the whole read while the provider is limiting);
    after ``breaker_after`` consecutive rate-limited requests the rest of the read goes to
    the fallback, reported once and recorded per page in ``attempts``.
    """

    def __init__(
        self,
        *,
        backend: Optional["ContextBackend"] = None,
        api_key: Optional[str] = None,
        concurrency: int = 8,
        batch_size: int = 10,
        max_chars: int = _DEFAULT_MAX_CHARS,
        policy: Optional[RateLimitPolicy] = None,
        fallback: Optional[PageFetcher] = None,
    ):
        self.concurrency = concurrency
        self.max_chars = max_chars
        self.policy = policy if policy is not None else RateLimitPolicy()
        self.fallback: PageFetcher = fallback if fallback is not None else HttpxPageFetcher(concurrency=concurrency)
        self.backend = backend if backend is not None else self._resolve_backend(api_key)
        limit = getattr(self.backend, "fetch_batch_limit", 1) if self.backend is not None else 1
        self.batch_size = max(1, min(batch_size, limit))

    @staticmethod
    def _resolve_backend(api_key: Optional[str]) -> Optional["ContextBackend"]:
        # Imported lazily: a knowledge import must not load the context package until a
        # provider-backed fetcher is actually constructed.
        key = api_key if api_key is not None else (getenv("PARALLEL_API_KEY", "") or None)
        if key and find_spec("parallel") is not None:
            from agno.context.web.parallel import ParallelBackend

            return ParallelBackend(api_key=key)
        if find_spec("mcp") is not None:
            from agno.context.web.parallel_mcp import ParallelMCPBackend

            return ParallelMCPBackend(api_key=key)
        return None

    @property
    def extractor_id(self) -> str:
        if self.backend is None:
            return getattr(self.fallback, "extractor_id", "httpx")
        return getattr(self.backend, "extractor_id", "parallel")

    # --- async ---

    async def afetch_many(self, urls: List[str], *, allowed_hosts: Optional[List[str]] = None) -> List[FetchedPage]:
        if self.backend is None:
            return await self.fallback.afetch_many(urls, allowed_hosts=allowed_hosts)

        results: Dict[str, FetchedPage] = {}
        fetchable: List[str] = []
        seen: Set[str] = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            if not is_host_allowed(url, allowed_hosts):
                results[url] = FetchedPage(url=url, error="off-host", extractor=self.extractor_id)
            else:
                fetchable.append(url)

        semaphore = asyncio.Semaphore(self.concurrency)
        # Per-call state on purpose — the fetcher instance is shared across concurrent reads.
        state = {"consecutive_rate_limits": 0, "tripped": False}

        async def fetch_batch(batch: List[str]) -> List[FetchedPage]:
            async with semaphore:
                attempts: List[Dict[str, str]] = []
                for attempt in range(self.policy.max_retries + 1):
                    if state["tripped"]:
                        break
                    try:
                        pages = await self.backend.afetch_many(batch, max_chars=self.max_chars)  # type: ignore[union-attr]
                        state["consecutive_rate_limits"] = 0
                        for page in pages:
                            page.attempts = attempts + [{"extractor": page.extractor, "outcome": page.error or "ok"}]
                        return pages
                    except RateLimited as e:
                        attempts.append({"extractor": self.extractor_id, "outcome": "rate-limited"})
                        state["consecutive_rate_limits"] += 1
                        if state["consecutive_rate_limits"] >= self.policy.breaker_after:
                            if not state["tripped"]:
                                state["tripped"] = True
                                log_info(
                                    f"{self.extractor_id} rate-limited "
                                    f"{state['consecutive_rate_limits']} times in a row; "
                                    "fetching the rest of this read with the built-in fetcher"
                                )
                            break
                        if attempt < self.policy.max_retries:
                            await asyncio.sleep(self._delay(e, attempt))
                    except Exception as e:
                        attempts.append({"extractor": self.extractor_id, "outcome": _failure_reason(e)})
                        log_debug(f"{self.extractor_id} fetch failed for batch of {len(batch)}: {e}")
                        break
            # Provider unavailable for this batch: the fallback owns these pages now.
            pages = await self.fallback.afetch_many(batch, allowed_hosts=allowed_hosts)
            for page in pages:
                page.attempts = attempts + page.attempts
            return pages

        batches = [fetchable[i : i + self.batch_size] for i in range(0, len(fetchable), self.batch_size)]
        fallback_extractor = getattr(self.fallback, "extractor_id", "httpx")
        for batch_pages in await asyncio.gather(*[fetch_batch(batch) for batch in batches]):
            # Pages the fallback already produced have nowhere further to fall
            retry_urls = [page.url for page in batch_pages if not page.ok and page.extractor != fallback_extractor]
            retry_pages: Dict[str, FetchedPage] = {}
            if retry_urls:
                # Pages the provider could not serve fall through to the fallback one level.
                for fallback_page in await self.fallback.afetch_many(retry_urls, allowed_hosts=allowed_hosts):
                    retry_pages[fallback_page.url] = fallback_page
            for page in batch_pages:
                replacement = retry_pages.get(page.url)
                if replacement is not None:
                    replacement.attempts = page.attempts + replacement.attempts
                    results[page.url] = replacement
                else:
                    results[page.url] = page

        return [results.get(url, FetchedPage(url=url, error="not fetched")) for url in urls]

    # --- sync ---

    def fetch_many(self, urls: List[str], *, allowed_hosts: Optional[List[str]] = None) -> List[FetchedPage]:
        if self.backend is None:
            return self.fallback.fetch_many(urls, allowed_hosts=allowed_hosts)

        results: Dict[str, FetchedPage] = {}
        fetchable: List[str] = []
        seen: Set[str] = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            if not is_host_allowed(url, allowed_hosts):
                results[url] = FetchedPage(url=url, error="off-host", extractor=self.extractor_id)
            else:
                fetchable.append(url)

        consecutive_rate_limits = 0
        tripped = False
        for start in range(0, len(fetchable), self.batch_size):
            batch = fetchable[start : start + self.batch_size]
            attempts: List[Dict[str, str]] = []
            batch_pages: Optional[List[FetchedPage]] = None
            if not tripped:
                for attempt in range(self.policy.max_retries + 1):
                    try:
                        batch_pages = self.backend.fetch_many(batch, max_chars=self.max_chars)
                        consecutive_rate_limits = 0
                        for page in batch_pages:
                            page.attempts = attempts + [{"extractor": page.extractor, "outcome": page.error or "ok"}]
                        break
                    except RateLimited as e:
                        attempts.append({"extractor": self.extractor_id, "outcome": "rate-limited"})
                        consecutive_rate_limits += 1
                        if consecutive_rate_limits >= self.policy.breaker_after:
                            tripped = True
                            log_info(
                                f"{self.extractor_id} rate-limited {consecutive_rate_limits} times in a row; "
                                "fetching the rest of this read with the built-in fetcher"
                            )
                            break
                        if attempt < self.policy.max_retries:
                            time.sleep(self._delay(e, attempt))
                    except Exception as e:
                        attempts.append({"extractor": self.extractor_id, "outcome": _failure_reason(e)})
                        log_debug(f"{self.extractor_id} fetch failed for batch of {len(batch)}: {e}")
                        break
            if batch_pages is None:
                batch_pages = self.fallback.fetch_many(batch, allowed_hosts=allowed_hosts)
                for page in batch_pages:
                    page.attempts = attempts + page.attempts

            fallback_extractor = getattr(self.fallback, "extractor_id", "httpx")
            # Pages the fallback already produced have nowhere further to fall
            retry_urls = [page.url for page in batch_pages if not page.ok and page.extractor != fallback_extractor]
            retry_pages: Dict[str, FetchedPage] = {}
            if retry_urls:
                for fallback_page in self.fallback.fetch_many(retry_urls, allowed_hosts=allowed_hosts):
                    retry_pages[fallback_page.url] = fallback_page
            for page in batch_pages:
                replacement = retry_pages.get(page.url)
                if replacement is not None:
                    replacement.attempts = page.attempts + replacement.attempts
                    results[page.url] = replacement
                else:
                    results[page.url] = page

        return [results.get(url, FetchedPage(url=url, error="not fetched")) for url in urls]

    def _delay(self, exc: RateLimited, attempt: int) -> float:
        if self.policy.honor_retry_after and exc.retry_after is not None:
            return min(max(exc.retry_after, 0.0), self.policy.max_delay)
        return min(self.policy.base_delay * (2**attempt), self.policy.max_delay)


def rate_limit_from_text(message: str) -> bool:
    """Whether a provider error message names a rate limit."""
    lowered = message.lower()
    return "rate limit" in lowered or "429" in lowered


__all__ = [
    "FetchedPage",
    "HttpxPageFetcher",
    "PageFetcher",
    "ParallelPageFetcher",
    "RateLimitPolicy",
    "RateLimited",
    "extract_page_text",
    "extract_page_title",
    "rate_limit_from_text",
]
