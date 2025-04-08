from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

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

    with patch("httpx.get", return_value=mock_response):
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

    with patch("httpx.get", return_value=mock_response):
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


def test_read_url_with_retry(mock_response):
    """Test URL reading with retry mechanism"""
    url = "https://example.com"

    with patch("httpx.get", side_effect=[httpx.RequestError("Connection error"), mock_response]):
        reader = URLReader()
        reader.chunk = False
        documents = reader.read(url)

        assert len(documents) == 1
        assert documents[0].content == "Hello, World!"


def test_read_url_max_retries():
    """Test URL reading with max retries exceeded"""
    url = "https://example.com"

    with patch("httpx.get", side_effect=httpx.RequestError("Connection error")):
        reader = URLReader()
        with pytest.raises(httpx.RequestError):
            reader.read(url)


def test_read_url_http_error(mock_response):
    """Test URL reading with HTTP error"""
    url = "https://example.com"
    mock_response.status_code = 404
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404 Not Found", request=Mock(), response=mock_response
    )

    with patch("httpx.get", return_value=mock_response):
        reader = URLReader()
        with pytest.raises(httpx.HTTPStatusError):
            reader.read(url)


def test_chunking(mock_response):
    """Test document chunking functionality"""
    url = "https://example.com"
    mock_response.text = "Hello, world! " * 1000

    with patch("httpx.get", return_value=mock_response):
        reader = URLReader()
        reader.chunk = True
        reader.chunk_size = 100
        documents = reader.read(url)

        assert len(documents) > 1
        assert all("url" in doc.meta_data for doc in documents)
        assert all(doc.meta_data["url"] == url for doc in documents)


@pytest.mark.asyncio
async def test_async_read_url_success():
    """Test successful async URL reading"""
    url = "https://example.com"

    mock_response = Mock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.text = "Hello, World!"

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value.get.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        reader = URLReader()
        reader.chunk = False  # Disable chunking for this test
        documents = await reader.async_read(url)

        assert len(documents) == 1
        assert documents[0].name == "example.com"
        assert documents[0].content == "Hello, World!"
        assert documents[0].meta_data["url"] == url


@pytest.mark.asyncio
async def test_async_read_url_with_retry():
    """Test async URL reading with retry mechanism"""
    url = "https://example.com"

    mock_response = Mock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.text = "Hello, World!"

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value.get.side_effect = [httpx.RequestError("Connection error"), mock_response]

    with patch("httpx.AsyncClient", return_value=mock_client):
        reader = URLReader()
        reader.chunk = False  # Disable chunking for this test
        documents = await reader.async_read(url)

        assert len(documents) == 1
        assert documents[0].content == "Hello, World!"


@pytest.mark.asyncio
async def test_async_read_url_max_retries():
    """Test async URL reading with max retries exceeded"""
    url = "https://example.com"

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value.get.side_effect = httpx.RequestError("Connection error")

    with patch("httpx.AsyncClient", return_value=mock_client):
        reader = URLReader()
        with pytest.raises(httpx.RequestError):
            await reader.async_read(url)


@pytest.mark.asyncio
async def test_async_read_url_http_error():
    """Test async URL reading with HTTP error"""
    url = "https://example.com"

    mock_response = Mock(spec=httpx.Response)
    mock_response.status_code = 404
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404 Not Found", request=Mock(), response=mock_response
    )

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value.get.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        reader = URLReader()
        with pytest.raises(httpx.HTTPStatusError):
            await reader.async_read(url)


@pytest.mark.asyncio
async def test_async_chunking():
    """Test async document chunking functionality"""
    url = "https://example.com"

    mock_response = Mock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.text = "Hello, world! " * 1000

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value.get.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        reader = URLReader()
        reader.chunk = True
        reader.chunk_size = 100
        documents = await reader.async_read(url)

        assert len(documents) > 1
        assert all("url" in doc.meta_data for doc in documents)
        assert all(doc.meta_data["url"] == url for doc in documents)
