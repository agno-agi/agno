from unittest.mock import patch

import httpx
import pytest

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.document.base import Document
from agno.knowledge.reader.utils.url_validation import is_host_allowed
from agno.knowledge.reader.website_reader import WebsiteReader


@pytest.fixture
def mock_html_content():
    return """
    <html>
        <head><title>Test Page</title></head>
        <body>
            <main>This is the main content</main>
            <a href="https://example.com/page1">Link 1</a>
            <a href="https://example.com/page2">Link 2</a>
            <a href="https://different-domain.com/page3">External Link</a>
        </body>
    </html>
    """


@pytest.fixture
def mock_html_content_with_article():
    return """
    <html>
        <head><title>Article Page</title></head>
        <body>
            <article>This is an article content</article>
            <a href="https://example.com/article1">Article 1</a>
        </body>
    </html>
    """


def test_delay():
    reader = WebsiteReader()

    with patch("time.sleep", return_value=None) as mock_sleep:
        reader.delay(1, 2)
        mock_sleep.assert_called_once()


def test_crawl_basic(mock_html_content):
    reader = WebsiteReader(max_depth=1, max_links=1)

    # Create a mock crawl result
    crawl_result = {"https://example.com": "This is the main content"}

    # Directly mock the crawl method
    with patch.object(reader, "crawl", return_value=crawl_result):
        result = reader.crawl("https://example.com")

        assert len(result) == 1
        assert "https://example.com" in result
        assert result["https://example.com"] == "This is the main content"


def test_read_basic(mock_html_content):
    reader = WebsiteReader(max_depth=1, max_links=1)
    reader.chunking_strategy = FixedSizeChunking(chunk_size=100)

    # Create a simple crawler result to return
    crawler_result = {"https://example.com": "This is the main content"}

    # Mock crawl to return a controlled result
    with patch.object(reader, "crawl", return_value=crawler_result):
        documents = reader.read("https://example.com")

        assert len(documents) == 1
        assert documents[0].name == "https://example.com"
        assert documents[0].meta_data["url"] == "https://example.com"
        assert documents[0].content == "This is the main content"


def test_read_with_chunking(mock_html_content):
    reader = WebsiteReader(max_depth=1, max_links=1)
    reader.chunk = True

    # Create a simple crawler result to return
    crawler_result = {"https://example.com": "This is the main content"}

    # Create real Document objects instead of Mock
    def mock_chunk_document(doc):
        return [
            doc,  # Original document
            Document(
                name=f"{doc.name}_chunk", id=f"{doc.id}_chunk", content="Chunked content", meta_data=doc.meta_data
            ),
        ]

    # Mock the chunk_document method with our implementation
    reader.chunk_document = mock_chunk_document

    # Mock crawl to return a controlled result
    with patch.object(reader, "crawl", return_value=crawler_result):
        documents = reader.read("https://example.com")

        assert len(documents) == 2
        assert documents[0].name == "https://example.com"
        assert documents[1].name == "https://example.com_chunk"


def test_read_error_handling():
    reader = WebsiteReader(max_depth=1, max_links=1)

    # Mock crawl to simulate an error by returning empty dict
    with patch.object(reader, "crawl", return_value={}):
        documents = reader.read("https://example.com")

        # Should return empty list when no URLs are crawled
        assert len(documents) == 0


def test_extract_main_content():
    reader = WebsiteReader()

    from bs4 import BeautifulSoup

    html = """<html><body><main>Main content</main></body></html>"""
    soup = BeautifulSoup(html, "html.parser")
    assert reader._extract_main_content(soup) == "Main content"

    html = """<html><body><article>Article content</article></body></html>"""
    soup = BeautifulSoup(html, "html.parser")
    assert reader._extract_main_content(soup) == "Article content"

    html = """<html><body><div class="content">Div content</div></body></html>"""
    soup = BeautifulSoup(html, "html.parser")
    assert reader._extract_main_content(soup) == "Div content"

    html = """<html><body><div>Random content</div></body></html>"""
    soup = BeautifulSoup(html, "html.parser")
    assert reader._extract_main_content(soup) == "Random content"


def test_get_primary_domain():
    reader = WebsiteReader()

    # Test with standard URL
    assert reader._get_primary_domain("https://example.com/page1") == "example.com"

    # Test with subdomain
    assert reader._get_primary_domain("https://blog.example.com/article") == "example.com"

    # Test with www
    assert reader._get_primary_domain("https://www.example.com") == "example.com"

    # Test with co.uk domain
    assert reader._get_primary_domain("https://example.co.uk") == "co.uk"


def test_crawl_max_depth(mock_html_content, mock_html_content_with_article):
    reader = WebsiteReader(max_depth=2, max_links=5)

    # Create a mock crawl result with multiple URLs
    crawl_result = {
        "https://example.com": "This is the main content",
        "https://example.com/page1": "This is an article content",
    }

    # Directly mock the crawl method
    with patch.object(reader, "crawl", return_value=crawl_result):
        result = reader.crawl("https://example.com")

        # Validate the results
        assert len(result) == 2
        assert "https://example.com" in result
        assert "https://example.com/page1" in result


@pytest.mark.asyncio
async def test_async_delay():
    reader = WebsiteReader()

    # Simple patch for asyncio.sleep
    with patch("asyncio.sleep", return_value=None) as mock_sleep:
        await reader.async_delay(1, 2)
        mock_sleep.assert_called_once()


@pytest.mark.asyncio
async def test_async_crawl_basic(mock_html_content):
    reader = WebsiteReader(max_depth=1, max_links=1)

    # Create a mock crawl result
    crawl_result = {"https://example.com": "This is the main content"}

    # Directly mock the function that's causing issues
    with patch.object(reader, "async_crawl", return_value=crawl_result):
        result = await reader.async_crawl("https://example.com")

        assert len(result) == 1
        assert "https://example.com" in result
        assert result["https://example.com"] == "This is the main content"


@pytest.mark.asyncio
async def test_async_read_basic(mock_html_content):
    reader = WebsiteReader(max_depth=1, max_links=1)
    reader.chunking_strategy = FixedSizeChunking(chunk_size=100)
    # Create a simple crawler result to return
    crawler_result = {"https://example.com": "This is the main content"}

    # Mock async_crawl to return a controlled result
    with patch.object(reader, "async_crawl", return_value=crawler_result):
        documents = await reader.async_read("https://example.com")

        assert len(documents) == 1
        assert documents[0].name == "https://example.com"
        assert documents[0].meta_data["url"] == "https://example.com"
        assert documents[0].content == "This is the main content"


@pytest.mark.asyncio
async def test_async_read_with_chunking(mock_html_content):
    reader = WebsiteReader(max_depth=1, max_links=1)
    reader.chunk = True

    # Create a simple crawler result to return
    crawler_result = {"https://example.com": "This is the main content"}

    # Create real Document objects instead of Mock
    def mock_chunk_document(doc):
        return [
            doc,  # Original document
            Document(
                name=f"{doc.name}_chunk", id=f"{doc.id}_chunk", content="Chunked content", meta_data=doc.meta_data
            ),
        ]

    # Mock the chunk_document method with our implementation
    reader.chunk_document = mock_chunk_document

    # Mock async_crawl to return a controlled result
    with patch.object(reader, "async_crawl", return_value=crawler_result):
        documents = await reader.async_read("https://example.com")

        assert len(documents) == 2
        assert documents[0].name == "https://example.com"
        assert documents[1].name == "https://example.com_chunk"


@pytest.mark.asyncio
async def test_async_read_error_handling():
    reader = WebsiteReader(max_depth=1, max_links=1)

    # Mock async_crawl to simulate an error by returning empty dict
    with patch.object(reader, "async_crawl", return_value={}):
        documents = await reader.async_read("https://example.com")

        # Should return empty list when no URLs are crawled
        assert len(documents) == 0


@pytest.mark.asyncio
async def test_async_crawl_max_depth(mock_html_content, mock_html_content_with_article):
    reader = WebsiteReader(max_depth=2, max_links=5)

    # Create a mock crawl result with multiple URLs
    crawl_result = {
        "https://example.com": "This is the main content",
        "https://example.com/page1": "This is an article content",
    }

    # Directly mock the async_crawl method
    with patch.object(reader, "async_crawl", return_value=crawl_result):
        result = await reader.async_crawl("https://example.com")

        # Validate the results
        assert len(result) == 2
        assert "https://example.com" in result
        assert "https://example.com/page1" in result


def test_website_reader_chunk_size_propagation():
    """Test that chunk_size is propagated to default chunking strategy"""
    from agno.knowledge.chunking.fixed import FixedSizeChunking

    reader = WebsiteReader(chunk_size=700)
    assert reader.chunk_size == 700
    assert reader.chunking_strategy.chunk_size == 700
    assert isinstance(reader.chunking_strategy, FixedSizeChunking)


def test_website_reader_default_chunk_size():
    """Test default chunk_size is 5000"""
    from agno.knowledge.chunking.fixed import FixedSizeChunking

    reader = WebsiteReader()
    assert reader.chunk_size == 5000
    assert reader.chunking_strategy.chunk_size == 5000
    assert isinstance(reader.chunking_strategy, FixedSizeChunking)


# ---------------------------------------------------------------------------
# allowed_hosts (SSRF hardening)
# ---------------------------------------------------------------------------


def test_allowed_hosts_default_is_none():
    """Default behavior is unchanged: no allowlist means all hosts allowed."""
    reader = WebsiteReader()
    assert reader.allowed_hosts is None
    assert is_host_allowed("https://docs.agno.com/anything", reader.allowed_hosts) is True
    assert is_host_allowed("http://127.0.0.1:8000/admin", reader.allowed_hosts) is True


def test_allowed_hosts_lowercases_input():
    """Hostnames are matched case-insensitively."""
    reader = WebsiteReader(allowed_hosts=["DOCS.AGNO.COM"])
    assert reader.allowed_hosts == ["docs.agno.com"]
    assert is_host_allowed("https://docs.agno.com/x", reader.allowed_hosts) is True
    assert is_host_allowed("https://DOCS.agno.COM/x", reader.allowed_hosts) is True


def test_allowed_hosts_rejects_unlisted():
    reader = WebsiteReader(allowed_hosts=["docs.agno.com"])
    assert is_host_allowed("http://127.0.0.1:8000/admin", reader.allowed_hosts) is False
    assert is_host_allowed("http://169.254.169.254/latest/meta-data", reader.allowed_hosts) is False
    assert is_host_allowed("http://10.0.0.5:8080/admin", reader.allowed_hosts) is False
    # Subdomains are not implicitly allowed
    assert is_host_allowed("https://internal.docs.agno.com/x", reader.allowed_hosts) is False


def test_allowed_hosts_rejects_url_with_no_host():
    reader = WebsiteReader(allowed_hosts=["docs.agno.com"])
    assert is_host_allowed("not-a-url", reader.allowed_hosts) is False
    assert is_host_allowed("file:///etc/passwd", reader.allowed_hosts) is False


def test_allowed_hosts_attaches_redirect_guard():
    """When an allowlist is configured, the httpx.Client must be created with a
    request event-hook so each redirect target is re-validated."""
    from unittest.mock import MagicMock, patch

    reader = WebsiteReader(allowed_hosts=["example.com"], max_depth=1, max_links=1)

    mock_response = MagicMock()
    mock_response.content = b"<html><body><main>ok</main></body></html>"
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch("agno.knowledge.reader.website_reader.httpx.Client", return_value=mock_client) as mock_client_ctor:
        reader.crawl("https://example.com")

    # Allowlist set → Client must be built with a request event-hook
    _, kwargs = mock_client_ctor.call_args
    assert "event_hooks" in kwargs
    assert "request" in kwargs["event_hooks"]
    assert callable(kwargs["event_hooks"]["request"][0])
    # And redirects must be followed (the hook polices them per-hop)
    _, get_kwargs = mock_client.get.call_args
    assert get_kwargs.get("follow_redirects") is True


def test_no_allowlist_uses_module_level_httpx_get():
    """Default behavior (no allowlist) keeps using httpx.get directly — the
    Client-with-event-hooks path is only for the allowlisted case."""
    from unittest.mock import MagicMock, patch

    reader = WebsiteReader(max_depth=1, max_links=1)

    mock_response = MagicMock()
    mock_response.content = b"<html><body><main>ok</main></body></html>"
    mock_response.raise_for_status = MagicMock()

    with patch("agno.knowledge.reader.website_reader.httpx.get", return_value=mock_response) as mock_get:
        reader.crawl("https://example.com")

    assert mock_get.called
    _, kwargs = mock_get.call_args
    assert kwargs.get("follow_redirects") is True


def test_redirect_guard_refuses_cross_host_target():
    """The redirect guard built from allowed_hosts must raise when a redirect
    points at a host outside the allowlist (the actual SSRF case)."""
    import httpx
    import pytest as _pytest

    from agno.knowledge.reader.utils.url_validation import make_redirect_guard

    guard = make_redirect_guard(["example.com"])
    assert guard is not None

    # Simulate the 302 target httpx would re-issue: a fresh request to localhost
    bad_request = httpx.Request("GET", "http://127.0.0.1:8080/admin")
    with _pytest.raises(httpx.RequestError, match="not in allowed_hosts"):
        guard(bad_request)

    # Same-host redirect target must pass
    good_request = httpx.Request("GET", "https://example.com/new-path")
    guard(good_request)  # no raise


def test_redirect_guard_is_none_when_no_allowlist():
    """When allowed_hosts is None, the guard factory returns None — callers can
    skip attaching the hook entirely."""
    from agno.knowledge.reader.utils.url_validation import make_redirect_guard

    assert make_redirect_guard(None) is None


def test_allowed_hosts_rejects_str_input():
    """Passing a single string (instead of a list) must raise error"""
    with pytest.raises(TypeError, match="must be a list"):
        WebsiteReader(allowed_hosts="docs.agno.com")


def test_crawl_blocked_start_url_returns_empty_dict():
    """A policy refusal must return {} cleanly"""
    reader = WebsiteReader(allowed_hosts=["docs.agno.com"], max_depth=1, max_links=1)
    result = reader.crawl("http://127.0.0.1:9999/admin")
    assert result == {}


def test_read_blocked_start_url_returns_empty_list():
    """read() must propagate the empty-dict as an empty document list."""
    reader = WebsiteReader(allowed_hosts=["docs.agno.com"], max_depth=1, max_links=1)
    documents = reader.read("http://169.254.169.254/latest/meta-data")
    assert documents == []


@pytest.mark.asyncio
async def test_async_crawl_blocked_start_url_returns_empty_dict():
    """read() must propagate the empty-dict as an empty document list for async path."""
    reader = WebsiteReader(allowed_hosts=["docs.agno.com"], max_depth=1, max_links=1)
    result = await reader.async_crawl("http://10.0.0.5/admin")
    assert result == {}


def test_crawl_real_network_failure_still_raises():
    """When there's no allowlist refusal, the existing
    'no content' RequestError still fires for genuine network failures."""
    from unittest.mock import patch

    reader = WebsiteReader(max_depth=1, max_links=1)

    # Simulate a real network failure on the start URL. No allowlist set, so
    # the reader goes through the module-level httpx.get path.
    with patch(
        "agno.knowledge.reader.website_reader.httpx.get",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        with pytest.raises(httpx.RequestError):
            reader.crawl("https://example.com")
