from unittest.mock import Mock, patch

import pytest

from agno.document.reader.website_reader import WebsiteReader


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

    # Setup mock response
    mock_response = Mock()
    mock_response.content = mock_html_content.encode()
    mock_response.raise_for_status = Mock(return_value=None)

    # Setup client mock
    mock_client = Mock()
    mock_client.__aenter__ = Mock(return_value=mock_client)
    mock_client.__aexit__ = Mock(return_value=None)
    mock_client.get = Mock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with patch("agno.document.reader.website_reader.WebsiteReader.async_delay", return_value=None):
            result = await reader.async_crawl("https://example.com")

            assert len(result) == 1
            assert "https://example.com" in result
            assert "This is the main content" in result["https://example.com"]


@pytest.mark.asyncio
async def test_async_read_basic(mock_html_content):
    reader = WebsiteReader(max_depth=1, max_links=1)

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

    # Mock the chunk_document method
    reader.chunk_document = lambda doc: [
        doc,  # Return the original doc for simplicity
        Mock(name=f"{doc.name}_chunk", id=f"{doc.id}_chunk", content="Chunked content", meta_data=doc.meta_data),
    ]

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

    # Setup responses for different URLs
    responses = {
        "https://example.com": Mock(content=mock_html_content.encode(), raise_for_status=Mock(return_value=None)),
        "https://example.com/page1": Mock(
            content=mock_html_content_with_article.encode(), raise_for_status=Mock(return_value=None)
        ),
    }

    # Setup client mock
    mock_client = Mock()
    mock_client.__aenter__ = Mock(return_value=mock_client)
    mock_client.__aexit__ = Mock(return_value=None)

    # Mock get to return different responses based on URL
    def mock_get(url, **kwargs):
        return responses.get(url, Mock(content="<html></html>".encode(), raise_for_status=Mock(return_value=None)))

    mock_client.get = mock_get

    with patch("httpx.AsyncClient", return_value=mock_client):
        with patch("agno.document.reader.website_reader.WebsiteReader.async_delay", return_value=None):
            result = await reader.async_crawl("https://example.com")

            # Should have content from crawled URLs
            assert "https://example.com" in result
            assert len(result) <= 5  # Respects max_links
