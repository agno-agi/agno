from unittest.mock import Mock, patch

import httpx
import pytest

from agno.document.chunking.fixed import FixedSizeChunking
from agno.document.reader.url_reader import URLReader


@pytest.fixture
def mock_response():
    """Fixture for mocked HTTP response"""
    response = Mock(spec=httpx.Response)
    response.status_code = 200
    response.text = "Hello, World!"
    response.content = b"Hello, World!"
    return response


def test_read_url_success(mock_response):
    """Test successful URL reading"""
    url = "https://example.com"

    with patch("agno.document.reader.url_reader.fetch_with_retry", return_value=mock_response):
        reader = URLReader()
        reader.chunk = False
        documents = reader.read(url)

        assert len(documents) == 1
        assert documents[0].name == "example.com"
        assert documents[0].content == "Hello, World!"
        assert documents[0].meta_data["url"] == url


def test_read_url_with_path(mock_response):
    """Test URL reading with path components"""
    url = "https://example.com/blog/post-1"

    with patch("agno.document.reader.url_reader.fetch_with_retry", return_value=mock_response):
        reader = URLReader()
        reader.chunk = False
        documents = reader.read(url)

        assert len(documents) == 1
        assert documents[0].name == "blog_post-1"
        assert documents[0].meta_data["url"] == url


def test_read_empty_url():
    """Test reading with empty URL"""
    reader = URLReader()
    with pytest.raises(ValueError, match="No url provided"):
        reader.read("")


def test_read_url_with_proxy(mock_response):
    """Test URL reading with proxy"""
    url = "https://example.com"
    proxy = "http://proxy.example.com:8080"

    with patch("agno.document.reader.url_reader.fetch_with_retry", return_value=mock_response) as mock_fetch:
        reader = URLReader(proxy=proxy)
        reader.chunk = False
        documents = reader.read(url)

        # Verify the proxy was passed to fetch_with_retry
        mock_fetch.assert_called_once_with(url, proxy=proxy)
        assert len(documents) == 1
        assert documents[0].content == "Hello, World!"


def test_read_url_request_error():
    """Test URL reading when fetch_with_retry raises RequestError"""
    url = "https://example.com"

    with patch("agno.document.reader.url_reader.fetch_with_retry", side_effect=httpx.RequestError("Connection failed")):
        reader = URLReader()
        with pytest.raises(httpx.RequestError):
            reader.read(url)


def test_read_url_http_error():
    """Test URL reading when fetch_with_retry raises HTTPStatusError"""
    url = "https://example.com"

    with patch(
        "agno.document.reader.url_reader.fetch_with_retry",
        side_effect=httpx.HTTPStatusError("404 Not Found", request=Mock(), response=Mock()),
    ):
        reader = URLReader()
        with pytest.raises(httpx.HTTPStatusError):
            reader.read(url)


def test_chunking(mock_response):
    """Test document chunking functionality"""
    url = "https://example.com"
    mock_response.text = "Hello, world! " * 1000

    with patch("agno.document.reader.url_reader.fetch_with_retry", return_value=mock_response):
        reader = URLReader()
        reader.chunk = True
        reader.chunking_strategy = FixedSizeChunking(chunk_size=100)
        documents = reader.read(url)

        assert len(documents) > 1
        assert all("url" in doc.meta_data for doc in documents)
        assert all(doc.meta_data["url"] == url for doc in documents)


@pytest.mark.asyncio
async def test_async_read_url_success(mock_response):
    """Test successful async URL reading"""
    url = "https://example.com"

    with patch("agno.document.reader.url_reader.async_fetch_with_retry", return_value=mock_response):
        reader = URLReader()
        reader.chunk = False  # Disable chunking for this test
        documents = await reader.async_read(url)

        assert len(documents) == 1
        assert documents[0].name == "example.com"
        assert documents[0].content == "Hello, World!"
        assert documents[0].meta_data["url"] == url


@pytest.mark.asyncio
async def test_async_read_empty_url():
    """Test async reading with empty URL"""
    reader = URLReader()
    with pytest.raises(ValueError, match="No url provided"):
        await reader.async_read("")


@pytest.mark.asyncio
async def test_async_read_url_with_proxy(mock_response):
    """Test async URL reading with proxy"""
    url = "https://example.com"
    proxy = "http://proxy.example.com:8080"

    with patch("agno.document.reader.url_reader.async_fetch_with_retry", return_value=mock_response) as mock_fetch:
        reader = URLReader(proxy=proxy)
        reader.chunk = False
        documents = await reader.async_read(url)

        # Verify the client was passed to async_fetch_with_retry
        mock_fetch.assert_called_once()
        call_args = mock_fetch.call_args
        assert call_args[0][0] == url  # First positional arg is url
        assert "client" in call_args[1]  # client should be in kwargs

        assert len(documents) == 1
        assert documents[0].content == "Hello, World!"


@pytest.mark.asyncio
async def test_async_read_url_request_error():
    """Test async URL reading when async_fetch_with_retry raises RequestError"""
    url = "https://example.com"

    with patch(
        "agno.document.reader.url_reader.async_fetch_with_retry", side_effect=httpx.RequestError("Connection failed")
    ):
        reader = URLReader()
        with pytest.raises(httpx.RequestError):
            await reader.async_read(url)


@pytest.mark.asyncio
async def test_async_read_url_http_error():
    """Test async URL reading when async_fetch_with_retry raises HTTPStatusError"""
    url = "https://example.com"

    with patch(
        "agno.document.reader.url_reader.async_fetch_with_retry",
        side_effect=httpx.HTTPStatusError("404 Not Found", request=Mock(), response=Mock()),
    ):
        reader = URLReader()
        with pytest.raises(httpx.HTTPStatusError):
            await reader.async_read(url)


@pytest.mark.asyncio
async def test_async_chunking(mock_response):
    """Test async document chunking functionality"""
    url = "https://example.com"
    mock_response.text = "Hello, world! " * 1000

    with patch("agno.document.reader.url_reader.async_fetch_with_retry", return_value=mock_response):
        reader = URLReader()
        reader.chunk = True
        reader.chunking_strategy = FixedSizeChunking(chunk_size=100)
        documents = await reader.async_read(url)

        assert len(documents) > 1
        assert all("url" in doc.meta_data for doc in documents)
        assert all(doc.meta_data["url"] == url for doc in documents)
