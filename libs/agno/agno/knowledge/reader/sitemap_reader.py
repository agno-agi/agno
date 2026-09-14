"""Reader that loads a website page by page from its sitemap.

Discovery follows the sitemap protocol: the URL itself when it is a sitemap, the ``Sitemap:``
lines in robots.txt, then the conventional locations. Pages are fetched through a
``PageFetcher`` (Parallel's extraction API when available, the built-in httpx fetcher
otherwise) and returned as one whole-page ``Document`` per page, so the insert path lands one
content row per page with its source URL kept.

The reader holds no per-read state — the factory hands every caller one shared instance and
reads run concurrently.
"""

import gzip
from typing import Generator, List, Optional, Tuple
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.reader.page_fetcher import FetchedPage, PageFetcher, ParallelPageFetcher
from agno.knowledge.reader.utils.url_validation import (
    is_host_allowed,
    make_async_redirect_guard,
    make_redirect_guard,
    validate_allowed_hosts,
)
from agno.knowledge.reader.utils.urls import canonical_page_name, canonical_page_url
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug

_SITEMAP_PATH_HINTS = ("sitemap", ".xml")
_GZIP_MAGIC = b"\x1f\x8b"

# The discovery generator yields URLs to fetch and receives their bodies (or None on
# failure); it returns (page_urls, sitemap_url, incomplete). One implementation, driven
# by both the sync and async transports. ``incomplete`` is True when a child sitemap of
# an index could not be fetched or parsed — its pages are silently absent, so a caller
# reconciling against a previous read must not treat them as removed.
_DiscoveryGen = Generator[str, Optional[bytes], Tuple[List[str], Optional[str], bool]]


def _default_allowed_hosts(host: str) -> List[str]:
    """The host plus its www twin — host matching is exact, and sites mix the two freely."""
    host = host.lower()
    bare = host[4:] if host.startswith("www.") else host
    return sorted({host, bare, f"www.{bare}"})


class SitemapReader(Reader):
    """Reads a website's sitemap and returns one whole-page document per page."""

    def __init__(
        self,
        max_pages: int = 50,
        allowed_hosts: Optional[List[str]] = None,
        follow_index: bool = True,
        page_fetcher: Optional[PageFetcher] = None,
        source_header: bool = False,
        timeout: int = 30,
        chunking_strategy: Optional[ChunkingStrategy] = None,
        **kwargs,
    ):
        if chunking_strategy is None:
            chunk_size = kwargs.get("chunk_size", 5000)
            chunking_strategy = FixedSizeChunking(chunk_size=chunk_size)
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)
        self.max_pages = max_pages
        self.allowed_hosts: Optional[List[str]] = validate_allowed_hosts(allowed_hosts)
        self.follow_index = follow_index
        self.page_fetcher: PageFetcher = page_fetcher if page_fetcher is not None else ParallelPageFetcher()
        self.source_header = source_header
        self.timeout = timeout

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        return [
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
            ChunkingStrategyType.MARKDOWN_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        # Declaring URL also tells the insert path not to pre-download the .xml for us.
        return [ContentType.URL]

    canonical_name = staticmethod(canonical_page_name)

    # ------------------------------------------------------------------
    # Discovery (sans-io: yields URLs, receives bodies)
    # ------------------------------------------------------------------

    def _hosts_for(self, url: str) -> List[str]:
        if self.allowed_hosts is not None:
            return self.allowed_hosts
        return _default_allowed_hosts(urlparse(url).hostname or "")

    @staticmethod
    def _decode_sitemap_bytes(raw: bytes) -> bytes:
        # .xml.gz served without Content-Encoding arrives still gzipped.
        if raw[:2] == _GZIP_MAGIC:
            try:
                return gzip.decompress(raw)
            except OSError:
                return raw
        return raw

    @staticmethod
    def _parse_sitemap(raw: bytes) -> Optional[Tuple[bool, List[str]]]:
        """``(is_index, locs)`` for a sitemap document, or None when it is not one.

        Only ``<loc>`` entries that are direct children of ``<url>``/``<sitemap>`` elements
        count — ``image:loc``/``video:loc`` live one level deeper and are not pages.
        """
        try:
            root = ElementTree.fromstring(SitemapReader._decode_sitemap_bytes(raw))
        except ElementTree.ParseError:
            return None
        tag = root.tag.rsplit("}", 1)[-1]
        if tag not in ("urlset", "sitemapindex"):
            return None
        locs: List[str] = []
        for entry in root:
            if entry.tag.rsplit("}", 1)[-1] not in ("url", "sitemap"):
                continue
            for child in entry:
                if child.tag.rsplit("}", 1)[-1] == "loc" and child.text and child.text.strip():
                    locs.append(child.text.strip())
                    break
        return tag == "sitemapindex", locs

    def _sitemap_candidates(self, url: str, robots_sitemaps: List[str]) -> List[str]:
        """Where a sitemap may live for ``url``, in discovery order, the URL itself first."""
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        candidates: List[str] = []
        last_segment = parsed.path.rsplit("/", 1)[-1].lower()
        if any(hint in last_segment for hint in _SITEMAP_PATH_HINTS):
            candidates.append(url)
        candidates.extend(robots_sitemaps)
        candidates.append(f"{root}/sitemap.xml")
        candidates.append(f"{root}/sitemap_index.xml")
        directory = parsed.path.rsplit("/", 1)[0]
        if directory:
            candidates.append(f"{root}{directory}/sitemap.xml")
        seen: set = set()
        ordered = []
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                ordered.append(candidate)
        return ordered

    @staticmethod
    def _robots_sitemap_lines(robots_txt: str) -> List[str]:
        lines = []
        for line in robots_txt.splitlines():
            key, _, value = line.partition(":")
            if key.strip().lower() == "sitemap" and value.strip():
                lines.append(value.strip())
        return lines

    def _discover(self, url: str, allowed_hosts: List[str]) -> _DiscoveryGen:
        """Find the sitemap for ``url`` and collect its page URLs.

        Yields each URL it needs fetched and receives the body (None on failure). Returns
        ``(page_urls, sitemap_url, incomplete)`` — pages in document order, deduplicated
        on canonical form, host-filtered, bounded by ``max_pages``; ``sitemap_url`` is
        None when no sitemap was found and the read falls back to the single page at
        ``url``; ``incomplete`` is True when an index child could not be fetched/parsed.
        """
        parsed_url = urlparse(url)
        robots_body = yield f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"
        robots_sitemaps = self._robots_sitemap_lines(robots_body.decode(errors="replace")) if robots_body else []

        for candidate in self._sitemap_candidates(url, robots_sitemaps):
            if not is_host_allowed(candidate, allowed_hosts):
                log_debug(f"Sitemap candidate on another host, skipping: {candidate}")
                continue
            raw = yield candidate
            parsed = self._parse_sitemap(raw) if raw is not None else None
            if parsed is None:
                continue

            is_index, locs = parsed
            pending: List[str] = list(locs) if is_index and self.follow_index else []
            page_locs: List[str] = [] if is_index else list(locs)
            incomplete = False
            visited = {canonical_page_url(candidate)}
            while pending and len(page_locs) < self.max_pages:
                child = pending.pop(0)
                child_key = canonical_page_url(child)
                if child_key in visited:
                    continue
                visited.add(child_key)
                if not is_host_allowed(child, allowed_hosts):
                    log_debug(f"Child sitemap on another host, skipping: {child}")
                    continue
                child_raw = yield child
                child_parsed = self._parse_sitemap(child_raw) if child_raw is not None else None
                if child_parsed is None:
                    # This shard's pages are absent from the read, not from the site
                    incomplete = True
                    continue
                child_is_index, child_locs = child_parsed
                if child_is_index:
                    pending.extend(child_locs)
                else:
                    page_locs.extend(child_locs)

            if pending:
                # Shards were never opened because the cap was reached first
                incomplete = True
            pages: List[str] = []
            seen: set = set()
            for index, loc in enumerate(page_locs):
                key = canonical_page_url(loc)
                if key in seen:
                    continue
                seen.add(key)
                if not is_host_allowed(loc, allowed_hosts):
                    log_debug(f"Sitemap entry on another host, skipping: {loc}")
                    continue
                pages.append(loc)
                if len(pages) >= self.max_pages:
                    if index + 1 < len(page_locs):
                        # The cap truncated the read: pages beyond it still exist on the
                        # site, so a reconciling caller must not treat them as removed
                        incomplete = True
                    break
            return pages, candidate, incomplete

        # No sitemap could be fetched and parsed anywhere. For a site that never had one
        # this is the normal single-page mode; for a site that did, it is an outage. The
        # two are indistinguishable here, so the read is marked incomplete either way —
        # the insert path then keeps previously loaded pages instead of pruning them.
        return [url], None, True

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def _build_documents(
        self, pages: List[FetchedPage], source_kind: str, discovery_incomplete: bool = False
    ) -> List[Document]:
        documents: List[Document] = []
        for page in pages:
            url_key = canonical_page_url(page.url)
            name = canonical_page_name(page.url)
            title = page.title or name
            meta: dict = {
                "url": url_key,
                "title": title,
                "host": urlparse(page.url).hostname or "",
                "extractor": page.extractor,
                "source": source_kind,
            }
            if page.attempts:
                meta["attempts"] = page.attempts
            if discovery_incomplete:
                # Read by the insert path (and stripped there): pages missing from this
                # read may still exist on the site.
                meta["discovery_incomplete"] = True
            if not page.ok:
                meta["error"] = page.error or "empty"
                documents.append(Document(name=name, id=url_key, meta_data=meta, content=""))
                continue
            content = page.content or ""
            if self.source_header:
                # Prepended before chunking, so it lands in the first chunk only.
                content = f"# {title}\nSource: {url_key}\n\n{content}"
            document = Document(name=name, id=url_key, meta_data=meta, content=content)
            if self.chunk:
                documents.extend(self.chunk_document(document))
            else:
                documents.append(document)
        return documents

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read(self, url: str, name: Optional[str] = None) -> List[Document]:
        allowed_hosts = self._hosts_for(url)
        guard = make_redirect_guard(allowed_hosts)
        event_hooks = {"request": [guard]} if guard else None

        discovery = self._discover(url, allowed_hosts)
        with httpx.Client(timeout=self.timeout, event_hooks=event_hooks) as client:  # type: ignore[arg-type]
            try:
                request_url = next(discovery)
                while True:
                    body: Optional[bytes]
                    try:
                        response = client.get(request_url, follow_redirects=True)
                        response.raise_for_status()
                        body = response.content
                    except Exception:
                        body = None
                    request_url = discovery.send(body)
            except StopIteration as stop:
                page_urls, sitemap_url, incomplete = stop.value

        source_kind = "sitemap" if sitemap_url else "page"
        fetched = self.page_fetcher.fetch_many(page_urls, allowed_hosts=allowed_hosts)
        return self._build_documents(fetched, source_kind, discovery_incomplete=incomplete)

    async def async_read(self, url: str, name: Optional[str] = None) -> List[Document]:
        allowed_hosts = self._hosts_for(url)
        guard = make_async_redirect_guard(allowed_hosts)
        event_hooks = {"request": [guard]} if guard else None

        discovery = self._discover(url, allowed_hosts)
        async with httpx.AsyncClient(timeout=self.timeout, event_hooks=event_hooks) as client:  # type: ignore[arg-type]
            try:
                request_url = next(discovery)
                while True:
                    body: Optional[bytes]
                    try:
                        response = await client.get(request_url, follow_redirects=True)
                        response.raise_for_status()
                        body = response.content
                    except Exception:
                        body = None
                    request_url = discovery.send(body)
            except StopIteration as stop:
                page_urls, sitemap_url, incomplete = stop.value

        source_kind = "sitemap" if sitemap_url else "page"
        fetched = await self.page_fetcher.afetch_many(page_urls, allowed_hosts=allowed_hosts)
        return self._build_documents(fetched, source_kind, discovery_incomplete=incomplete)
