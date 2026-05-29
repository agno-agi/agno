from unittest.mock import MagicMock, patch

import pytest

from agno.knowledge.reader.web_search_reader import WebSearchReader
from agno.knowledge.reader.website_reader import WebsiteReader

# --- FastEmbedEmbedder caching tests ---


def test_fastembed_embedder_caches_client():
    import numpy as np

    mock_text_embedding_class = MagicMock()
    mock_client_instance = MagicMock()
    mock_client_instance.embed.return_value = [np.array([0.1, 0.2, 0.3])]
    mock_text_embedding_class.return_value = mock_client_instance

    with patch.dict("sys.modules", {"fastembed": MagicMock(TextEmbedding=mock_text_embedding_class)}):
        with patch("agno.knowledge.embedder.fastembed.TextEmbedding", mock_text_embedding_class):
            from agno.knowledge.embedder.fastembed import FastEmbedEmbedder

            embedder = FastEmbedEmbedder()

            embedder.get_embedding("text 1")
            embedder.get_embedding("text 2")
            embedder.get_embedding("text 3")

            # Client constructor should only be called once (lazy on first use)
            assert mock_text_embedding_class.call_count == 1
            assert mock_client_instance.embed.call_count == 3


def test_fastembed_embedder_accepts_injected_client():
    import numpy as np

    mock_client = MagicMock()
    mock_client.embed.return_value = [np.array([0.1, 0.2, 0.3])]

    mock_text_embedding_class = MagicMock()

    with patch.dict("sys.modules", {"fastembed": MagicMock(TextEmbedding=mock_text_embedding_class)}):
        with patch("agno.knowledge.embedder.fastembed.TextEmbedding", mock_text_embedding_class):
            from agno.knowledge.embedder.fastembed import FastEmbedEmbedder

            embedder = FastEmbedEmbedder(fastembed_client=mock_client)

            assert embedder.fastembed_client is mock_client

            result = embedder.get_embedding("test")
            mock_client.embed.assert_called_once_with("test")
            assert result == [0.1, 0.2, 0.3]


# --- WebSearchReader state tests ---


def test_web_search_reader_visited_urls_cleared_between_reads():
    reader = WebSearchReader()

    reader._visited_urls.add("https://example.com")
    reader._visited_urls.add("https://test.com")
    assert len(reader._visited_urls) == 2

    with patch.object(reader, "_perform_web_search", return_value=[]):
        reader.read("test query")

    assert len(reader._visited_urls) == 0


def test_web_search_reader_urls_not_skipped_on_second_read():
    reader = WebSearchReader()

    reader._visited_urls.add("https://example.com")

    with patch.object(reader, "_perform_web_search", return_value=[]):
        reader.read("second query")

    assert "https://example.com" not in reader._visited_urls


@pytest.mark.asyncio
async def test_web_search_reader_async_read_clears_state():
    reader = WebSearchReader()

    reader._visited_urls.add("https://example.com")
    reader._visited_urls.add("https://test.com")
    assert len(reader._visited_urls) == 2

    with patch.object(reader, "_perform_web_search", return_value=[]):
        await reader.async_read("test query")

    assert len(reader._visited_urls) == 0


# --- WebsiteReader state tests ---


@pytest.fixture
def mock_http_response():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"<html><body>Test content</body></html>"
    mock_response.raise_for_status = MagicMock()
    return mock_response


def test_website_reader_sync_crawl_resets_visited(mock_http_response):
    reader = WebsiteReader(max_depth=1, max_links=1)

    reader._visited.add("https://old-site.com")
    reader._visited.add("https://old-site.com/page1")
    assert len(reader._visited) == 2

    with patch("httpx.get", return_value=mock_http_response):
        reader.crawl("https://new-site.com")

    assert "https://old-site.com" not in reader._visited
    assert "https://old-site.com/page1" not in reader._visited


def test_website_reader_sync_crawl_resets_urls_to_crawl(mock_http_response):
    reader = WebsiteReader(max_depth=1, max_links=1)

    reader._urls_to_crawl = [("https://leftover.com", 1), ("https://leftover2.com", 2)]

    with patch("httpx.get", return_value=mock_http_response):
        reader.crawl("https://new-site.com")

    remaining_urls = [url for url, _ in reader._urls_to_crawl]
    assert "https://leftover.com" not in remaining_urls
    assert "https://leftover2.com" not in remaining_urls


def test_website_reader_sync_and_async_have_same_reset_behavior():
    import inspect

    reader = WebsiteReader()

    sync_source = inspect.getsource(reader.crawl)
    async_source = inspect.getsource(reader.async_crawl)

    assert "self._visited = set()" in sync_source
    assert "self._visited = set()" in async_source
    assert "self._urls_to_crawl = [" in sync_source
    assert "self._urls_to_crawl = [" in async_source
