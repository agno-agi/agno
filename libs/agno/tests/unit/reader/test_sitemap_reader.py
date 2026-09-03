"""Unit tests for SitemapReader: URL canonicalization, sitemap discovery, document
construction, reader statelessness, and factory wiring.

All HTTP goes through httpx.MockTransport — no network. Both the reader's discovery
clients and HttpxPageFetcher's clients are patched to route through the same transport.
"""

import asyncio
import gzip
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

from agno.knowledge.document.base import Document
from agno.knowledge.reader.page_fetcher import HttpxPageFetcher
from agno.knowledge.reader.sitemap_reader import SitemapReader
from agno.knowledge.reader.utils.urls import (
    MAX_PAGE_NAME_LENGTH,
    canonical_page_name,
    canonical_page_url,
    is_sitemap_url,
)
from agno.knowledge.types import ContentType

_ORIG_CLIENT = httpx.Client
_ORIG_ASYNC_CLIENT = httpx.AsyncClient

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
IMAGE_NS = "http://www.google.com/schemas/sitemap-image/1.1"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def urlset_xml(*locs: str) -> str:
    entries = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="{SITEMAP_NS}">{entries}</urlset>'


def sitemapindex_xml(*locs: str) -> str:
    entries = "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc in locs)
    return f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="{SITEMAP_NS}">{entries}</sitemapindex>'


def html_page(title: str, body: str) -> str:
    return f"<html><head><title>{title}</title></head><body><main>{body}</main></body></html>"


@contextmanager
def mock_site(routes):
    """Serve ``routes`` ({"scheme://host/path": (body, content_type)}) via MockTransport.

    Patches the httpx client constructors used by both the sitemap reader and the page
    fetcher so every request in a read hits the mock. Yields the list of requested URLs
    (in request order). Unrouted URLs get a 404.
    """
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        key = f"{request.url.scheme}://{request.url.host}{request.url.path}"
        spec = routes.get(key)
        if spec is None:
            return httpx.Response(404, text="not found")
        body, content_type = spec
        if isinstance(body, bytes):
            return httpx.Response(200, content=body, headers={"content-type": content_type})
        return httpx.Response(200, text=body, headers={"content-type": content_type})

    transport = httpx.MockTransport(handler)

    def client_factory(**kwargs):
        kwargs.pop("proxy", None)
        return _ORIG_CLIENT(transport=transport, **kwargs)

    def async_client_factory(**kwargs):
        kwargs.pop("proxy", None)
        return _ORIG_ASYNC_CLIENT(transport=transport, **kwargs)

    with (
        patch("agno.knowledge.reader.sitemap_reader.httpx.Client", client_factory),
        patch("agno.knowledge.reader.sitemap_reader.httpx.AsyncClient", async_client_factory),
        patch("agno.knowledge.reader.page_fetcher.httpx.Client", client_factory),
        patch("agno.knowledge.reader.page_fetcher.httpx.AsyncClient", async_client_factory),
    ):
        yield requested


def make_reader(**kwargs) -> SitemapReader:
    kwargs.setdefault("page_fetcher", HttpxPageFetcher())
    return SitemapReader(**kwargs)


# ----------------------------------------------------------------------
# canonical_page_name / canonical_page_url / is_sitemap_url
# ----------------------------------------------------------------------


def test_canonical_page_name_trailing_slash_equivalence():
    assert canonical_page_name("https://example.com/docs/") == canonical_page_name("https://example.com/docs")
    assert canonical_page_name("https://example.com/docs") == "example.com/docs"


def test_canonical_page_name_index_html_stripped():
    assert canonical_page_name("https://example.com/docs/index.html") == "example.com/docs"
    assert canonical_page_name("https://example.com/docs/index.htm") == "example.com/docs"
    assert canonical_page_name("https://example.com/index.html") == "example.com"


def test_canonical_page_name_query_kept():
    assert canonical_page_name("https://example.com/p?v=1") == "example.com/p?v=1"
    assert canonical_page_name("https://example.com/p?v=1") != canonical_page_name("https://example.com/p?v=2")


def test_canonical_page_name_fragment_dropped():
    assert canonical_page_name("https://example.com/p#section-2") == "example.com/p"


def test_canonical_page_name_percent_decoded():
    assert canonical_page_name("https://example.com/caf%C3%A9") == "example.com/café"


def test_canonical_page_name_root_is_host():
    assert canonical_page_name("https://example.com/") == "example.com"
    assert canonical_page_name("https://Example.COM") == "example.com"


def test_canonical_page_name_truncated_with_hash_suffix():
    import hashlib

    long_url = "https://example.com/" + "a" * 300
    full_name = "example.com/" + "a" * 300
    name = canonical_page_name(long_url)
    assert MAX_PAGE_NAME_LENGTH == 255
    assert len(name) == MAX_PAGE_NAME_LENGTH
    digest = hashlib.sha256(full_name.encode()).hexdigest()[:8]
    assert name == f"{full_name[: MAX_PAGE_NAME_LENGTH - 9]}-{digest}"


def test_canonical_page_url_rules():
    # Lowercased scheme and host; path case preserved
    assert canonical_page_url("HTTPS://Example.COM/Path") == "https://example.com/Path"
    # Fragment dropped
    assert canonical_page_url("https://example.com/a#frag") == "https://example.com/a"
    # Trailing slash stripped
    assert canonical_page_url("https://example.com/a/") == "https://example.com/a"
    # index.html stripped
    assert canonical_page_url("https://example.com/docs/index.html") == "https://example.com/docs"
    # Query kept
    assert canonical_page_url("https://example.com/p?v=1") == "https://example.com/p?v=1"


def test_is_sitemap_url():
    assert is_sitemap_url("https://x.com/sitemap.xml") is True
    assert is_sitemap_url("https://x.com/sitemap-0.xml") is True
    assert is_sitemap_url("https://x.com/sitemap_index.xml.gz") is True
    assert is_sitemap_url("https://x.com/page.xml") is False
    assert is_sitemap_url("https://x.com/sitemap/page") is False


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------


def test_url_is_sitemap_robots_consulted_first():
    routes = {
        "https://example.com/robots.txt": ("Sitemap: https://example.com/other.xml\n", "text/plain"),
        "https://example.com/sitemap.xml": (urlset_xml("https://example.com/a"), "application/xml"),
        "https://example.com/other.xml": (urlset_xml("https://example.com/b"), "application/xml"),
        "https://example.com/a": (html_page("Page A", "Main content A"), "text/html"),
        "https://example.com/b": (html_page("Page B", "Main content B"), "text/html"),
    }
    reader = make_reader()
    with mock_site(routes) as requested:
        documents = reader.read("https://example.com/sitemap.xml")

    # robots.txt is fetched first, but the URL itself is the first candidate and wins
    assert requested[0] == "https://example.com/robots.txt"
    assert requested[1] == "https://example.com/sitemap.xml"
    assert not any("other.xml" in url for url in requested)
    assert not any(url.endswith("/b") for url in requested)
    assert len(documents) == 1
    assert documents[0].meta_data["url"] == "https://example.com/a"
    assert documents[0].meta_data["source"] == "sitemap"


def test_robots_only_discovery():
    # No /sitemap.xml anywhere; robots.txt names a custom location
    routes = {
        "https://example.com/robots.txt": (
            "User-agent: *\nSitemap: https://example.com/custom/sitemap.xml\n",
            "text/plain",
        ),
        "https://example.com/custom/sitemap.xml": (urlset_xml("https://example.com/p1"), "application/xml"),
        "https://example.com/p1": (html_page("P1", "Content one"), "text/html"),
    }
    reader = make_reader()
    with mock_site(routes) as requested:
        documents = reader.read("https://example.com")

    # The robots-declared sitemap comes before the conventional /sitemap.xml candidate
    assert "https://example.com/custom/sitemap.xml" in requested
    assert "https://example.com/sitemap.xml" not in requested
    assert len(documents) == 1
    assert documents[0].meta_data["url"] == "https://example.com/p1"
    assert documents[0].meta_data["source"] == "sitemap"


def test_sitemap_index_pages_in_document_order():
    routes = {
        "https://example.com/sitemap.xml": (
            sitemapindex_xml("https://example.com/sm1.xml", "https://example.com/sm2.xml"),
            "application/xml",
        ),
        "https://example.com/sm1.xml": (
            urlset_xml("https://example.com/p1", "https://example.com/p2"),
            "application/xml",
        ),
        "https://example.com/sm2.xml": (urlset_xml("https://example.com/p3"), "application/xml"),
        "https://example.com/p1": (html_page("P1", "One"), "text/html"),
        "https://example.com/p2": (html_page("P2", "Two"), "text/html"),
        "https://example.com/p3": (html_page("P3", "Three"), "text/html"),
    }
    reader = make_reader()
    with mock_site(routes):
        documents = reader.read("https://example.com/sitemap.xml")

    assert [doc.meta_data["url"] for doc in documents] == [
        "https://example.com/p1",
        "https://example.com/p2",
        "https://example.com/p3",
    ]
    assert all(doc.meta_data["source"] == "sitemap" for doc in documents)


def test_gzipped_sitemap_parsed():
    # No-namespace urlset, gzipped body served without Content-Encoding
    plain_xml = '<?xml version="1.0"?><urlset><url><loc>https://example.com/p1</loc></url></urlset>'
    routes = {
        "https://example.com/sitemap.xml.gz": (gzip.compress(plain_xml.encode()), "application/gzip"),
        "https://example.com/p1": (html_page("P1", "Unzipped fine"), "text/html"),
    }
    reader = make_reader()
    with mock_site(routes):
        documents = reader.read("https://example.com/sitemap.xml.gz")

    assert len(documents) == 1
    assert documents[0].meta_data["url"] == "https://example.com/p1"
    assert documents[0].meta_data["source"] == "sitemap"


def test_nested_index_cycle_terminates():
    routes = {
        "https://example.com/sitemap.xml": (sitemapindex_xml("https://example.com/idx2.xml"), "application/xml"),
        # The child index points back at its parent (cycle) plus a real urlset
        "https://example.com/idx2.xml": (
            sitemapindex_xml("https://example.com/sitemap.xml", "https://example.com/pages.xml"),
            "application/xml",
        ),
        "https://example.com/pages.xml": (urlset_xml("https://example.com/p1"), "application/xml"),
        "https://example.com/p1": (html_page("P1", "Reached through the cycle"), "text/html"),
    }
    reader = make_reader()
    with mock_site(routes) as requested:
        documents = reader.read("https://example.com/sitemap.xml")

    assert len(documents) == 1
    assert documents[0].meta_data["url"] == "https://example.com/p1"
    # The parent sitemap was fetched exactly once — the back-reference was not refetched
    assert requested.count("https://example.com/sitemap.xml") == 1


def test_image_loc_not_collected_as_page():
    xml = (
        f'<?xml version="1.0"?><urlset xmlns="{SITEMAP_NS}" xmlns:image="{IMAGE_NS}">'
        "<url><loc>https://example.com/p1</loc>"
        "<image:image><image:loc>https://example.com/img.jpg</image:loc></image:image>"
        "</url></urlset>"
    )
    routes = {
        "https://example.com/sitemap.xml": (xml, "application/xml"),
        "https://example.com/p1": (html_page("P1", "Page with image"), "text/html"),
    }
    reader = make_reader()
    with mock_site(routes) as requested:
        documents = reader.read("https://example.com/sitemap.xml")

    assert [doc.meta_data["url"] for doc in documents] == ["https://example.com/p1"]
    assert not any("img.jpg" in url for url in requested)


def test_max_pages_cap_across_children_preserves_order():
    routes = {
        "https://example.com/sitemap.xml": (
            sitemapindex_xml("https://example.com/sm1.xml", "https://example.com/sm2.xml"),
            "application/xml",
        ),
        "https://example.com/sm1.xml": (
            urlset_xml("https://example.com/a", "https://example.com/b"),
            "application/xml",
        ),
        "https://example.com/sm2.xml": (
            urlset_xml("https://example.com/c", "https://example.com/d"),
            "application/xml",
        ),
        "https://example.com/a": (html_page("A", "Alpha"), "text/html"),
        "https://example.com/b": (html_page("B", "Beta"), "text/html"),
        "https://example.com/c": (html_page("C", "Gamma"), "text/html"),
        "https://example.com/d": (html_page("D", "Delta"), "text/html"),
    }
    reader = make_reader(max_pages=3)
    with mock_site(routes) as requested:
        documents = reader.read("https://example.com/sitemap.xml")

    assert [doc.meta_data["url"] for doc in documents] == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]
    assert not any(url.endswith("/d") for url in requested)


def test_no_sitemap_falls_back_to_single_page():
    routes = {
        "https://example.com/about": (html_page("About", "Just this page"), "text/html"),
    }
    reader = make_reader()
    with mock_site(routes) as requested:
        documents = reader.read("https://example.com/about")

    # Only the URL itself is read as a page
    page_requests = [url for url in requested if url == "https://example.com/about"]
    assert page_requests == ["https://example.com/about"]
    assert len(documents) == 1
    assert documents[0].meta_data["url"] == "https://example.com/about"
    assert documents[0].meta_data["source"] == "page"


def test_cross_host_loc_skipped():
    routes = {
        "https://example.com/sitemap.xml": (
            urlset_xml("https://example.com/a", "https://evil.com/x"),
            "application/xml",
        ),
        "https://example.com/a": (html_page("A", "Same host"), "text/html"),
        "https://evil.com/x": (html_page("X", "Other host"), "text/html"),
    }
    reader = make_reader()
    with mock_site(routes) as requested:
        documents = reader.read("https://example.com/sitemap.xml")

    assert [doc.meta_data["url"] for doc in documents] == ["https://example.com/a"]
    assert not any("evil.com" in url for url in requested)


def test_cross_host_robots_sitemap_skipped():
    routes = {
        "https://example.com/robots.txt": ("Sitemap: https://other.com/sitemap.xml\n", "text/plain"),
        "https://example.com/sitemap.xml": (urlset_xml("https://example.com/a"), "application/xml"),
        "https://other.com/sitemap.xml": (urlset_xml("https://other.com/x"), "application/xml"),
        "https://example.com/a": (html_page("A", "Own host wins"), "text/html"),
    }
    reader = make_reader()
    with mock_site(routes) as requested:
        documents = reader.read("https://example.com")

    assert not any("other.com" in url for url in requested)
    assert [doc.meta_data["url"] for doc in documents] == ["https://example.com/a"]


def test_duplicate_locs_deduplicated_first_kept():
    routes = {
        "https://example.com/sitemap.xml": (
            urlset_xml("https://example.com/a", "https://example.com/a/"),
            "application/xml",
        ),
        "https://example.com/a": (html_page("A", "Deduplicated"), "text/html"),
    }
    reader = make_reader()
    with mock_site(routes) as requested:
        documents = reader.read("https://example.com/sitemap.xml")

    assert len(documents) == 1
    assert documents[0].meta_data["url"] == "https://example.com/a"
    # The first form (no trailing slash) was fetched, exactly once; the twin never was
    assert requested.count("https://example.com/a") == 1
    assert "https://example.com/a/" not in requested


# ----------------------------------------------------------------------
# Documents
# ----------------------------------------------------------------------


def test_document_metadata_fields():
    routes = {
        "https://example.com/sitemap.xml": (urlset_xml("https://example.com/a/"), "application/xml"),
        "https://example.com/a/": (html_page("Page A Title", "Body of A"), "text/html"),
    }
    reader = make_reader()
    with mock_site(routes):
        documents = reader.read("https://example.com/sitemap.xml")

    assert len(documents) == 1
    doc = documents[0]
    assert isinstance(doc, Document)
    assert doc.name == "example.com/a"
    assert doc.meta_data["url"] == "https://example.com/a"  # canonical: trailing slash stripped
    assert doc.meta_data["title"] == "Page A Title"
    assert doc.meta_data["host"] == "example.com"
    assert doc.meta_data["extractor"] == "httpx"
    assert doc.meta_data["source"] == "sitemap"
    assert doc.meta_data["attempts"] == [{"extractor": "httpx", "outcome": "ok"}]
    assert doc.content == "Body of A"


def test_failed_page_yields_error_document():
    routes = {
        "https://example.com/sitemap.xml": (
            urlset_xml("https://example.com/good", "https://example.com/missing"),
            "application/xml",
        ),
        "https://example.com/good": (html_page("Good", "Fetched fine"), "text/html"),
        # /missing has no route -> 404
    }
    reader = make_reader()
    with mock_site(routes):
        documents = reader.read("https://example.com/sitemap.xml")

    assert len(documents) == 2
    good, failed = documents
    assert good.meta_data["url"] == "https://example.com/good"
    assert "error" not in good.meta_data
    assert failed.meta_data["url"] == "https://example.com/missing"
    assert failed.content == ""
    assert failed.meta_data["error"] == "HTTP 404"
    assert failed.meta_data["source"] == "sitemap"
    # Failed pages are not chunked
    assert "chunk" not in failed.meta_data


def test_page_chunked_exactly_once():
    body = " ".join(f"word{i}" for i in range(120))  # single-spaced, ~800 chars
    routes = {
        "https://example.com/sitemap.xml": (urlset_xml("https://example.com/long"), "application/xml"),
        "https://example.com/long": (html_page("Long", body), "text/html"),
    }
    reader = make_reader(chunk_size=200)
    with mock_site(routes):
        documents = reader.read("https://example.com/sitemap.xml")

    assert len(documents) >= 2
    assert all(len(doc.content) <= 200 for doc in documents)
    # Chunk numbers run 1..n once — a re-chunked read would restart the numbering
    assert [doc.meta_data["chunk"] for doc in documents] == list(range(1, len(documents) + 1))
    # Every chunk carries the same canonical page url
    assert {doc.meta_data["url"] for doc in documents} == {"https://example.com/long"}
    # Nothing lost or duplicated across chunks
    assert "".join(doc.content for doc in documents) == body


def test_source_header_default_off():
    routes = {
        "https://example.com/sitemap.xml": (urlset_xml("https://example.com/a"), "application/xml"),
        "https://example.com/a": (html_page("Page A", "Hello content"), "text/html"),
    }
    reader = make_reader()
    assert reader.source_header is False
    with mock_site(routes):
        documents = reader.read("https://example.com/sitemap.xml")

    assert len(documents) == 1
    assert not documents[0].content.startswith("# ")
    assert "Source:" not in documents[0].content


def test_source_header_unchunked_format():
    routes = {
        "https://example.com/sitemap.xml": (urlset_xml("https://example.com/a"), "application/xml"),
        "https://example.com/a": (html_page("Page A", "Hello content"), "text/html"),
    }
    reader = make_reader(source_header=True, chunk=False)
    with mock_site(routes):
        documents = reader.read("https://example.com/sitemap.xml")

    assert len(documents) == 1
    assert documents[0].content.startswith("# Page A\nSource: https://example.com/a\n\n")
    assert documents[0].content.endswith("Hello content")


def test_source_header_lands_in_first_chunk_only():
    body = " ".join(f"word{i}" for i in range(120))
    routes = {
        "https://example.com/sitemap.xml": (urlset_xml("https://example.com/a"), "application/xml"),
        "https://example.com/a": (html_page("Page A", body), "text/html"),
    }
    reader = make_reader(source_header=True, chunk_size=200)
    with mock_site(routes):
        documents = reader.read("https://example.com/sitemap.xml")

    assert len(documents) >= 2
    # FixedSizeChunking collapses whitespace, so the header's newlines become spaces
    assert documents[0].content.startswith("# Page A Source: https://example.com/a ")
    for later in documents[1:]:
        assert "# Page A" not in later.content
        assert "Source:" not in later.content


# ----------------------------------------------------------------------
# Statelessness
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_async_reads_do_not_interleave():
    routes = {
        "https://site-a.com/sitemap.xml": (
            urlset_xml("https://site-a.com/a1", "https://site-a.com/a2"),
            "application/xml",
        ),
        "https://site-a.com/a1": (html_page("A1", "Alpha one"), "text/html"),
        "https://site-a.com/a2": (html_page("A2", "Alpha two"), "text/html"),
        "https://site-b.com/sitemap.xml": (
            urlset_xml("https://site-b.com/b1", "https://site-b.com/b2"),
            "application/xml",
        ),
        "https://site-b.com/b1": (html_page("B1", "Beta one"), "text/html"),
        "https://site-b.com/b2": (html_page("B2", "Beta two"), "text/html"),
    }
    reader = make_reader()
    with mock_site(routes):
        docs_a, docs_b = await asyncio.gather(
            reader.async_read("https://site-a.com/sitemap.xml"),
            reader.async_read("https://site-b.com/sitemap.xml"),
        )

    assert [doc.meta_data["url"] for doc in docs_a] == ["https://site-a.com/a1", "https://site-a.com/a2"]
    assert all(doc.meta_data["host"] == "site-a.com" for doc in docs_a)
    assert [doc.content for doc in docs_a] == ["Alpha one", "Alpha two"]

    assert [doc.meta_data["url"] for doc in docs_b] == ["https://site-b.com/b1", "https://site-b.com/b2"]
    assert all(doc.meta_data["host"] == "site-b.com" for doc in docs_b)
    assert [doc.content for doc in docs_b] == ["Beta one", "Beta two"]


# ----------------------------------------------------------------------
# Content types and factory
# ----------------------------------------------------------------------


def test_get_supported_content_types():
    assert SitemapReader.get_supported_content_types() == [ContentType.URL]


def test_reader_factory_sitemap(monkeypatch):
    from agno.knowledge.reader.reader_factory import ReaderFactory

    # Keep backend resolution deterministic and keyless for the default ParallelPageFetcher
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    ReaderFactory.clear_cache()
    try:
        assert "sitemap" in ReaderFactory.get_all_reader_keys()
        reader = ReaderFactory.create_reader("sitemap")
        assert isinstance(reader, SitemapReader)
        url_reader = ReaderFactory.get_reader_for_url("https://x.com/sitemap.xml")
        assert isinstance(url_reader, SitemapReader)
    finally:
        ReaderFactory.clear_cache()


# ----------------------------------------------------------------------
# Incomplete discovery (a lost shard must not read as removed content)
# ----------------------------------------------------------------------


def test_failed_index_child_marks_documents_discovery_incomplete():
    routes = {
        "https://example.com/sitemap.xml": (
            sitemapindex_xml("https://example.com/sitemap-a.xml", "https://example.com/sitemap-b.xml"),
            "application/xml",
        ),
        "https://example.com/sitemap-a.xml": (urlset_xml("https://example.com/page-a"), "application/xml"),
        # sitemap-b.xml is unrouted -> 404: an entire shard is missing from this read
        "https://example.com/page-a": (html_page("A", "Alpha content"), "text/html"),
    }
    with mock_site(routes):
        documents = make_reader().read("https://example.com/sitemap.xml")

    assert documents, "the reachable shard's pages are still read"
    assert all(doc.meta_data.get("discovery_incomplete") is True for doc in documents), (
        "every document must carry the incomplete-discovery flag so the insert path suppresses pruning"
    )


def test_complete_discovery_carries_no_incomplete_flag():
    routes = {
        "https://example.com/sitemap.xml": (urlset_xml("https://example.com/page-a"), "application/xml"),
        "https://example.com/page-a": (html_page("A", "Alpha content"), "text/html"),
    }
    with mock_site(routes):
        documents = make_reader().read("https://example.com/sitemap.xml")

    assert documents
    assert all("discovery_incomplete" not in doc.meta_data for doc in documents)


def test_cap_truncated_read_marks_discovery_incomplete():
    locs = [f"https://example.com/p{i}" for i in range(6)]
    routes = {"https://example.com/sitemap.xml": (urlset_xml(*locs), "application/xml")}
    for loc in locs:
        routes[loc.replace("https://example.com", "https://example.com")] = (html_page("P", "page body"), "text/html")
    with mock_site(routes):
        capped = make_reader(max_pages=3).read("https://example.com/sitemap.xml")
        full = make_reader(max_pages=10).read("https://example.com/sitemap.xml")

    assert len(capped) == 3
    assert all(doc.meta_data.get("discovery_incomplete") is True for doc in capped), (
        "pages beyond the cap still exist on the site; a reconciling caller must not prune them"
    )
    assert len(full) == 6
    assert all("discovery_incomplete" not in doc.meta_data for doc in full)
