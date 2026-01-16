"""Tests for reader state management."""

from unittest.mock import MagicMock, patch

import pytest

from agno.knowledge.reader.web_search_reader import WebSearchReader
from agno.knowledge.reader.website_reader import WebsiteReader


@pytest.fixture
def mock_http_response():
    """Mock HTTP response for website crawling."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"<html><body>Test content</body></html>"
    mock_response.raise_for_status = MagicMock()
    return mock_response


def test_web_search_reader_visited_urls_cleared_between_reads():
    """_visited_urls is cleared at start of each read() call."""
    reader = WebSearchReader()

    reader._visited_urls.add("https://example.com")
    reader._visited_urls.add("https://test.com")
    assert len(reader._visited_urls) == 2

    with patch.object(reader, "_perform_web_search", return_value=[]):
        reader.read("test query")

    assert len(reader._visited_urls) == 0


def test_web_search_reader_urls_not_skipped_on_second_read():
    """URLs from first read don't affect second read."""
    reader = WebSearchReader()

    reader._visited_urls.add("https://example.com")

    with patch.object(reader, "_perform_web_search", return_value=[]):
        reader.read("second query")

    assert "https://example.com" not in reader._visited_urls


def test_website_reader_sync_crawl_resets_visited(mock_http_response):
    """Sync crawl() resets _visited set."""
    reader = WebsiteReader(max_depth=1, max_links=1)

    reader._visited.add("https://old-site.com")
    reader._visited.add("https://old-site.com/page1")
    assert len(reader._visited) == 2

    with patch("httpx.get", return_value=mock_http_response):
        reader.crawl("https://new-site.com")

    assert "https://old-site.com" not in reader._visited
    assert "https://old-site.com/page1" not in reader._visited


def test_website_reader_sync_crawl_resets_urls_to_crawl(mock_http_response):
    """Sync crawl() resets _urls_to_crawl list."""
    reader = WebsiteReader(max_depth=1, max_links=1)

    reader._urls_to_crawl = [("https://leftover.com", 1), ("https://leftover2.com", 2)]

    with patch("httpx.get", return_value=mock_http_response):
        reader.crawl("https://new-site.com")

    remaining_urls = [url for url, _ in reader._urls_to_crawl]
    assert "https://leftover.com" not in remaining_urls
    assert "https://leftover2.com" not in remaining_urls


def test_website_reader_sync_and_async_have_same_reset_behavior():
    """Sync crawl() has same reset logic as async_crawl()."""
    import inspect

    reader = WebsiteReader()

    sync_source = inspect.getsource(reader.crawl)
    async_source = inspect.getsource(reader.async_crawl)

    assert "self._visited = set()" in sync_source
    assert "self._visited = set()" in async_source
    assert "self._urls_to_crawl = [" in sync_source
    assert "self._urls_to_crawl = [" in async_source
