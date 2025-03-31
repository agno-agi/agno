from unittest.mock import AsyncMock, Mock, patch

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

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await reader.async_delay(1, 2)
        mock_sleep.assert_called_once()
        # Check that the sleep duration is between 1 and 2
        sleep_duration = mock_sleep.call_args[0][0]
        assert 1 <= sleep_duration <= 2


@pytest.mark.asyncio
async def test_async_crawl_basic(mock_html_content):
    reader = WebsiteReader(max_depth=1, max_links=1)

    # Create mock for AsyncClient context manager
    mock_client = AsyncMock()
    mock_response = AsyncMock()
    mock_response.content = mock_html_content.encode()
    mock_client.get.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        with patch.object(mock_client, "__aenter__", return_value=mock_client):
            with patch.object(mock_client, "__aexit__", return_value=None):
                result = await reader.async_crawl("https://example.com")

                assert len(result) == 1
                assert "https://example.com" in result
                assert "This is the main content" in result["https://example.com"]
                mock_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_async_read_basic(mock_html_content):
    reader = WebsiteReader(max_depth=1, max_links=1)

    # Create mocks with proper AsyncMock behavior
    async_client_mock = Mock()
    context_manager = AsyncMock()
    async_client_mock.return_value = context_manager

    # Setup response
    mock_response = AsyncMock()
    mock_response.content = mock_html_content.encode()
    context_manager.get.return_value = mock_response

    with patch("httpx.AsyncClient", async_client_mock):
        documents = await reader.async_read("https://example.com")

        assert len(documents) == 1
        assert documents[0].name == "https://example.com"
        assert documents[0].meta_data["url"] == "https://example.com"
        assert "This is the main content" in documents[0].content


@pytest.mark.asyncio
async def test_async_read_with_chunking(mock_html_content):
    reader = WebsiteReader(max_depth=1, max_links=1)
    reader.chunk = True

    # Mock the chunk_document method
    reader.chunk_document = lambda doc: [
        doc,  # Return the original doc for simplicity
        Mock(name=f"{doc.name}_chunk", id=f"{doc.id}_chunk", content="Chunked content", meta_data=doc.meta_data),
    ]

    # Create mocks with proper AsyncMock behavior
    async_client_mock = Mock()
    context_manager = AsyncMock()
    async_client_mock.return_value = context_manager

    # Setup response
    mock_response = AsyncMock()
    mock_response.content = mock_html_content.encode()
    context_manager.get.return_value = mock_response

    with patch("httpx.AsyncClient", async_client_mock):
        documents = await reader.async_read("https://example.com")

        assert len(documents) == 2
        assert documents[0].name == "https://example.com"
        assert documents[1].name == "https://example.com_chunk"


@pytest.mark.asyncio
async def test_async_read_error_handling():
    reader = WebsiteReader(max_depth=1, max_links=1)

    # Create mocks with error behavior
    async_client_mock = Mock()
    context_manager = AsyncMock()
    async_client_mock.return_value = context_manager

    # Make the get method raise an exception
    context_manager.get.side_effect = Exception("Network error")

    with patch("httpx.AsyncClient", async_client_mock):
        documents = await reader.async_read("https://example.com")

        # Should return empty list on error
        assert len(documents) == 0


@pytest.mark.asyncio
async def test_async_crawl_max_depth(mock_html_content, mock_html_content_with_article):
    reader = WebsiteReader(max_depth=2, max_links=5)

    # Create mock for AsyncClient
    mock_client = AsyncMock()

    # Define different responses for different URLs
    async def mock_get(url, **kwargs):
        response = AsyncMock()
        if url == "https://example.com":
            response.content = mock_html_content.encode()
        elif url == "https://example.com/page1":
            response.content = mock_html_content_with_article.encode()
        else:
            response.content = "<html></html>".encode()
        return response

    mock_client.get = mock_get

    with patch("httpx.AsyncClient", return_value=mock_client):
        with patch.object(mock_client, "__aenter__", return_value=mock_client):
            with patch.object(mock_client, "__aexit__", return_value=None):
                with patch("agno.document.reader.website_reader.WebsiteReader.async_delay", new_callable=AsyncMock):
                    result = await reader.async_crawl("https://example.com")

                    # Should have both URLs
                    assert "https://example.com" in result
                    assert len(result) <= 5
