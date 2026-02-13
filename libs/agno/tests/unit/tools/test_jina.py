from unittest.mock import MagicMock, patch

import httpx
import pytest

from agno.tools.jina import JinaReaderTools, JinaReaderToolsConfig


@pytest.fixture()
def jina_tools():
    return JinaReaderTools(api_key="test_api_key")


@pytest.fixture
def sample_read_url_response():
    """Sample response for read_url function"""
    return {
        "code": 200,
        "status": 20000,
        "data": {
            "title": "Example Domain",
            "description": "",
            "url": "https://example.com/",
            "content": "This domain is for use in illustrative examples in documents. You may use this domain in literature without prior coordination or asking for permission.\n\n[More information...](https://www.iana.org/domains/example)",
            "publishedTime": "Mon, 13 Jan 2025 20:11:20 GMT",
            "metadata": {"viewport": "width=device-width, initial-scale=1"},
            "external": {},
            "warning": "This is a cached snapshot of the original page, consider retry with caching opt-out.",
            "usage": {"tokens": 42},
        },
        "meta": {"usage": {"tokens": 42}},
    }


@pytest.fixture
def sample_search_query_response():
    """Sample response for search_query function"""
    return {
        "code": 200,
        "status": 20000,
        "data": [
            {
                "title": "Berita Terkini Nasional - Politik - CNN Indonesia",
                "url": "https://www.cnnindonesia.com/nasional/politik",
                "description": "Istana Pastikan Undang SBY, Megawati dan Jokowi di HUT ke-80 RI · PDIP Akan Gelar Kongres di Bali Awal Agustus? · Erika Carlina Laporkan DJ Panda soal Dugaan",
                "content": "",
                "usage": {"tokens": 1000},
            }
        ],
        "meta": {"usage": {"tokens": 10000}},
    }


def test_config_default_values():
    """Test that config has correct default values"""
    config = JinaReaderToolsConfig()
    assert config.api_key is None
    assert str(config.base_url) == "https://r.jina.ai/"
    assert str(config.search_url) == "https://s.jina.ai/"
    assert config.max_content_length == 10000
    assert config.timeout is None
    assert config.search_query_content is False


def test_config_custom_values():
    """Test config with custom values"""
    config = JinaReaderToolsConfig(
        api_key="test_key",
        base_url="https://custom.r.jina.ai/",
        search_url="https://custom.s.jina.ai/",
        max_content_length=5000,
        timeout=30,
    )
    assert config.api_key == "test_key"
    assert str(config.base_url) == "https://custom.r.jina.ai/"
    assert str(config.search_url) == "https://custom.s.jina.ai/"
    assert config.max_content_length == 5000
    assert config.timeout == 30


def test_init_with_api_key():
    tools = JinaReaderTools(api_key="test_key")
    assert tools.config.api_key == "test_key"


def test_init_with_env_var(monkeypatch):
    """Test initialization with environment variable"""
    monkeypatch.setenv("JINA_API_KEY", "env_test_key")
    # Pass api_key=None to bypass the import-time default and test the runtime getenv fallback
    tools = JinaReaderTools(api_key=None)
    assert tools.config.api_key == "env_test_key"


def test_init_without_api_key(monkeypatch):
    """Test initialization without API key (should work)"""
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    tools = JinaReaderTools(api_key=None)
    assert tools.config.api_key is None


def test_init_with_custom_config():
    """Test initialization with custom configuration"""
    tools = JinaReaderTools(
        api_key="test_key",
        base_url="https://custom.r.jina.ai/",
        search_url="https://custom.s.jina.ai/",
        max_content_length=5000,
        timeout=30,
    )
    assert tools.config.api_key == "test_key"
    assert str(tools.config.base_url) == "https://custom.r.jina.ai/"
    assert str(tools.config.search_url) == "https://custom.s.jina.ai/"
    assert tools.config.max_content_length == 5000
    assert tools.config.timeout == 30


def test_init_tools_selection_read_only():
    """Test initialization with only read_url tool"""
    tools = JinaReaderTools(api_key="test_key", enable_read_url=True, enable_search_query=False)
    assert len(tools.tools) == 1
    assert tools.tools[0].__name__ == "read_url"


def test_init_tools_selection_search_only():
    """Test initialization with only search_query tool"""
    tools = JinaReaderTools(api_key="test_key", enable_read_url=False, enable_search_query=True)
    assert len(tools.tools) == 1
    assert tools.tools[0].__name__ == "search_query"


def test_init_tools_selection_both():
    """Test initialization with both tools"""
    tools = JinaReaderTools(api_key="test_key", enable_read_url=True, enable_search_query=True)
    assert len(tools.tools) == 2
    tool_names = [tool.__name__ for tool in tools.tools]
    assert "read_url" in tool_names
    assert "search_query" in tool_names


def test_init_tools_selection_none():
    """Test initialization with no tools"""
    tools = JinaReaderTools(api_key="test_key", enable_read_url=False, enable_search_query=False)
    assert len(tools.tools) == 0


@patch("agno.tools.jina.httpx.get")
def test_read_url_successful(mock_httpx_get, sample_read_url_response):
    """Test successful URL reading"""
    # Setup mock response
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = sample_read_url_response
    mock_httpx_get.return_value = mock_response

    tools = JinaReaderTools(api_key="test_key")
    result = tools.read_url("https://example.com")

    # Verify the call
    expected_url = f"{tools.config.base_url}https://example.com"
    mock_httpx_get.assert_called_once_with(expected_url, headers=tools._get_headers())

    # Verify result contains the response data
    assert str(sample_read_url_response) in result


@patch("agno.tools.jina.httpx.get")
@patch("agno.tools.jina.logger")
def test_read_url_http_error(mock_logger, mock_httpx_get):
    """Test read_url with HTTP error"""
    mock_httpx_get.side_effect = httpx.HTTPStatusError("HTTP Error", request=MagicMock(), response=MagicMock())

    tools = JinaReaderTools(api_key="test_key")
    result = tools.read_url("https://example.com")

    assert "Error reading URL" in result
    assert "HTTP Error" in result
    mock_logger.error.assert_called_once()


@patch("agno.tools.jina.httpx.get")
@patch("agno.tools.jina.logger")
def test_read_url_connection_error(mock_logger, mock_httpx_get):
    """Test read_url with connection error"""
    mock_httpx_get.side_effect = httpx.ConnectError("Connection failed")

    tools = JinaReaderTools(api_key="test_key")
    result = tools.read_url("https://example.com")

    assert "Error reading URL" in result
    assert "Connection failed" in result
    mock_logger.error.assert_called_once()


@patch("agno.tools.jina.httpx.get")
def test_read_url_with_truncation(mock_httpx_get):
    """Test read_url with content truncation"""
    # Create a large response that should be truncated
    large_content = {"data": "x" * 15000}  # Larger than default max_content_length
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = large_content
    mock_httpx_get.return_value = mock_response

    tools = JinaReaderTools(api_key="test_key", max_content_length=1000)
    result = tools.read_url("https://example.com")

    assert len(result) <= 1000 + len("... (content truncated)")
    assert "... (content truncated)" in result


@patch("agno.tools.jina.httpx.post")
def test_search_query_successful(mock_httpx_post, sample_search_query_response):
    """Test successful search query"""
    # Setup mock response
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = sample_search_query_response
    mock_httpx_post.return_value = mock_response

    tools = JinaReaderTools(api_key="test_key", enable_search_query=True)
    result = tools.search_query("test query")

    # Verify the call
    expected_headers = tools._get_headers()
    if not tools.config.search_query_content:
        expected_headers["X-Respond-With"] = "no-content"  # to avoid returning full content in search results

    expected_body = {"q": "test query"}
    mock_httpx_post.assert_called_once_with(str(tools.config.search_url), headers=expected_headers, json=expected_body)

    # Verify result contains the response data
    assert str(sample_search_query_response) in result


@patch("agno.tools.jina.httpx.post")
@patch("agno.tools.jina.logger")
def test_search_query_http_error(mock_logger, mock_httpx_post):
    """Test search_query with HTTP error"""
    mock_httpx_post.side_effect = httpx.HTTPStatusError("HTTP Error", request=MagicMock(), response=MagicMock())

    tools = JinaReaderTools(api_key="test_key", enable_search_query=True)
    result = tools.search_query("test query")

    assert "Error performing search" in result
    assert "HTTP Error" in result
    mock_logger.error.assert_called_once()


@patch("agno.tools.jina.httpx.post")
def test_search_query_with_truncation(mock_httpx_post):
    """Test search_query with content truncation"""
    # Create a large response that should be truncated
    large_response = {"data": [{"content": "x" * 15000}]}
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = large_response
    mock_httpx_post.return_value = mock_response

    tools = JinaReaderTools(api_key="test_key", enable_search_query=True, max_content_length=1000)
    result = tools.search_query("test query")

    assert len(result) <= 1000 + len("... (content truncated)")
    assert "... (content truncated)" in result
