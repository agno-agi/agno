"""Unit tests for JinaReaderTools class."""

import json
from unittest.mock import Mock, patch

import pytest
import httpx

from agno.tools.jina import JinaReaderTools, JinaReaderToolsConfig


@pytest.fixture
def jina_tools_basic():
    """Create a basic JinaReaderTools instance with only read_url enabled."""
    return JinaReaderTools(
        api_key="test_api_key",
        read_url=True,
        search_query=False,
        timeout=30,
        max_content_length=5000
    )


@pytest.fixture
def jina_tools_search():
    """Create a JinaReaderTools instance with only search_query enabled."""
    return JinaReaderTools(
        api_key="test_api_key",
        read_url=False,
        search_query=True,
        timeout=30,
        max_content_length=5000
    )


@pytest.fixture
def jina_tools_full():
    """Create a JinaReaderTools instance with both features enabled."""
    return JinaReaderTools(
        api_key="test_api_key",
        read_url=True,
        search_query=True,
        timeout=30,
        max_content_length=5000
    )


@pytest.fixture
def jina_tools_no_api_key():
    """Create a JinaReaderTools instance without API key."""
    return JinaReaderTools(
        api_key=None,
        read_url=True,
        search_query=True,
        timeout=30,
        max_content_length=5000
    )


def test_jina_reader_tools_config():
    """Test JinaReaderToolsConfig initialization."""
    config = JinaReaderToolsConfig(
        api_key="test_key",
        max_content_length=8000,
        timeout=60
    )
    
    assert config.api_key == "test_key"
    assert config.max_content_length == 8000
    assert config.timeout == 60
    assert str(config.base_url) == "https://r.jina.ai/"
    assert str(config.search_url) == "https://s.jina.ai/"


def test_initialization_with_read_url_only():
    """Test initialization with only read_url enabled."""
    tools = JinaReaderTools(read_url=True, search_query=False)
    
    function_names = [func.name for func in tools.functions.values()]
    assert "read_url" in function_names
    assert "search_query" not in function_names


def test_initialization_with_search_query_only():
    """Test initialization with only search_query enabled."""
    tools = JinaReaderTools(read_url=False, search_query=True)
    
    function_names = [func.name for func in tools.functions.values()]
    assert "read_url" not in function_names
    assert "search_query" in function_names


def test_initialization_with_both_features():
    """Test initialization with both features enabled."""
    tools = JinaReaderTools(read_url=True, search_query=True)
    
    function_names = [func.name for func in tools.functions.values()]
    assert "read_url" in function_names
    assert "search_query" in function_names


def test_initialization_with_custom_config():
    """Test initialization with custom configuration."""
    tools = JinaReaderTools(
        api_key="custom_key",
        base_url="https://custom.jina.ai/",
        search_url="https://custom-search.jina.ai/",
        max_content_length=15000,
        timeout=45
    )
    
    assert tools.config.api_key == "custom_key"
    assert str(tools.config.base_url) == "https://custom.jina.ai/"
    assert str(tools.config.search_url) == "https://custom-search.jina.ai/"
    assert tools.config.max_content_length == 15000
    assert tools.config.timeout == 45


def test_get_reader_headers_with_api_key(jina_tools_basic):
    """Test _get_reader_headers method with API key."""
    headers = jina_tools_basic._get_reader_headers()
    
    expected_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Engine": "direct",
        "X-Timeout": "30",
        "X-With-Links-Summary": "true",
        "X-Return-Format": "markdown",
        "Authorization": "Bearer test_api_key"
    }
    
    assert headers == expected_headers


def test_get_reader_headers_without_api_key(jina_tools_no_api_key):
    """Test _get_reader_headers method without API key."""
    headers = jina_tools_no_api_key._get_reader_headers()
    
    expected_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Engine": "direct",
        "X-Timeout": "30",
        "X-With-Links-Summary": "true",
        "X-Return-Format": "markdown"
    }
    
    assert headers == expected_headers
    assert "Authorization" not in headers


def test_get_search_headers_with_api_key(jina_tools_search):
    """Test _get_search_headers method with API key."""
    headers = jina_tools_search._get_search_headers()
    
    expected_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Engine": "direct",
        "X-Timeout": "30",
        "Authorization": "Bearer test_api_key"
    }
    
    assert headers == expected_headers


def test_get_search_headers_without_api_key(jina_tools_no_api_key):
    """Test _get_search_headers method without API key."""
    headers = jina_tools_no_api_key._get_search_headers()
    
    expected_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Engine": "direct",
        "X-Timeout": "30"
    }
    
    assert headers == expected_headers
    assert "Authorization" not in headers


def test_truncate_content_within_limit(jina_tools_basic):
    """Test _truncate_content method with content within limit."""
    content = "This is a short content."
    result = jina_tools_basic._truncate_content(content)
    
    assert result == content


def test_truncate_content_exceeds_limit(jina_tools_basic):
    """Test _truncate_content method with content exceeding limit."""
    content = "x" * 6000  # Exceeds the 5000 limit
    result = jina_tools_basic._truncate_content(content)
    
    assert len(result) == 5000 + len("... (content truncated)")
    assert result.endswith("... (content truncated)")
    assert result.startswith("x" * 5000)


@patch("agno.tools.jina.httpx.Client")
def test_read_url_success(mock_client, jina_tools_basic):
    """Test successful URL reading."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "code": 200,
        "data": {
            "content": "This is the content from the URL."
        }
    }
    mock_response.raise_for_status.return_value = None
    
    mock_client_instance = Mock()
    mock_client_instance.post.return_value = mock_response
    mock_client.return_value.__enter__.return_value = mock_client_instance
    
    result = jina_tools_basic.read_url("https://example.com")
    
    assert result == "This is the content from the URL."
    mock_client_instance.post.assert_called_once_with(
        str(jina_tools_basic.config.base_url),
        headers=jina_tools_basic._get_reader_headers(),
        json={"url": "https://example.com"}
    )


@patch("agno.tools.jina.httpx.Client")
def test_read_url_api_error(mock_client, jina_tools_basic):
    """Test URL reading with API error response."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "code": 400,
        "message": "Invalid URL provided"
    }
    mock_response.raise_for_status.return_value = None
    
    mock_client_instance = Mock()
    mock_client_instance.post.return_value = mock_response
    mock_client.return_value.__enter__.return_value = mock_client_instance
    
    result = jina_tools_basic.read_url("https://invalid-url.com")
    
    assert result == "Error: Invalid URL provided"


@patch("agno.tools.jina.httpx.Client")
def test_read_url_http_error(mock_client, jina_tools_basic):
    """Test URL reading with HTTP error."""
    mock_client_instance = Mock()
    mock_client_instance.post.side_effect = httpx.HTTPStatusError(
        "Request failed",
        request=Mock(),
        response=Mock()
    )
    mock_client.return_value.__enter__.return_value = mock_client_instance
    
    result = jina_tools_basic.read_url("https://example.com")
    
    assert result.startswith("Error reading URL:")


@patch("agno.tools.jina.httpx.Client")
def test_read_url_generic_exception(mock_client, jina_tools_basic):
    """Test URL reading with generic exception."""
    mock_client_instance = Mock()
    mock_client_instance.post.side_effect = Exception("Network error")
    mock_client.return_value.__enter__.return_value = mock_client_instance
    
    with patch("agno.tools.jina.logger.error") as mock_logger:
        result = jina_tools_basic.read_url("https://example.com")
    
    assert result == "Error reading URL: Network error"
    mock_logger.assert_called_once_with("Error reading URL: Network error")


@patch("agno.tools.jina.httpx.Client")
def test_search_query_success(mock_client, jina_tools_search):
    """Test successful search query."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "code": 200,
        "data": [
            {
                "title": "Test Result 1",
                "url": "https://example1.com",
                "content": "Content for result 1" + "x" * 500
            },
            {
                "title": "Test Result 2",
                "url": "https://example2.com",
                "content": "Content for result 2"
            }
        ]
    }
    mock_response.raise_for_status.return_value = None
    
    mock_client_instance = Mock()
    mock_client_instance.post.return_value = mock_response
    mock_client.return_value.__enter__.return_value = mock_client_instance
    
    result = jina_tools_search.search_query("test query")
    
    assert "1. Test Result 1" in result
    assert "URL: https://example1.com" in result
    assert "2. Test Result 2" in result
    assert "URL: https://example2.com" in result
    # Content should be truncated to 500 characters
    assert "Content for result 1" + "x" * (500 - len("Content for result 1")) + "..." in result
    
    mock_client_instance.post.assert_called_once_with(
        str(jina_tools_search.config.search_url),
        headers=jina_tools_search._get_search_headers(),
        json={"q": "test query"}
    )


@patch("agno.tools.jina.httpx.Client")
def test_search_query_api_error(mock_client, jina_tools_search):
    """Test search query with API error response."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "code": 400,
        "message": "Invalid search query"
    }
    mock_response.raise_for_status.return_value = None
    
    mock_client_instance = Mock()
    mock_client_instance.post.return_value = mock_response
    mock_client.return_value.__enter__.return_value = mock_client_instance
    
    result = jina_tools_search.search_query("invalid query")
    
    assert result == "Error: Invalid search query"


@patch("agno.tools.jina.httpx.Client")
def test_search_query_http_error(mock_client, jina_tools_search):
    """Test search query with HTTP error."""
    mock_client_instance = Mock()
    mock_client_instance.post.side_effect = httpx.HTTPStatusError(
        "Request failed",
        request=Mock(),
        response=Mock()
    )
    mock_client.return_value.__enter__.return_value = mock_client_instance
    
    result = jina_tools_search.search_query("test query")
    
    assert result.startswith("Error performing search:")


@patch("agno.tools.jina.httpx.Client")
def test_search_query_generic_exception(mock_client, jina_tools_search):
    """Test search query with generic exception."""
    mock_client_instance = Mock()
    mock_client_instance.post.side_effect = Exception("Network error")
    mock_client.return_value.__enter__.return_value = mock_client_instance
    
    with patch("agno.tools.jina.logger.error") as mock_logger:
        result = jina_tools_search.search_query("test query")
    
    assert result == "Error performing search: Network error"
    mock_logger.assert_called_once_with("Error performing search: Network error")


@patch("agno.tools.jina.httpx.Client")
def test_search_query_limits_results(mock_client, jina_tools_search):
    """Test that search query limits results to 5."""
    # Create 7 mock results
    mock_results = []
    for i in range(7):
        mock_results.append({
            "title": f"Result {i+1}",
            "url": f"https://example{i+1}.com",
            "content": f"Content {i+1}"
        })
    
    mock_response = Mock()
    mock_response.json.return_value = {
        "code": 200,
        "data": mock_results
    }
    mock_response.raise_for_status.return_value = None
    
    mock_client_instance = Mock()
    mock_client_instance.post.return_value = mock_response
    mock_client.return_value.__enter__.return_value = mock_client_instance
    
    result = jina_tools_search.search_query("test query")
    
    # Should only have 5 results
    assert "1. Result 1" in result
    assert "5. Result 5" in result
    assert "6. Result 6" not in result
    assert "7. Result 7" not in result


def test_toolkit_name_and_registration(jina_tools_full):
    """Test that the toolkit is properly named and functions are registered."""
    assert jina_tools_full.name == "jina_reader_tools"
    
    function_names = [func.name for func in jina_tools_full.functions.values()]
    assert "read_url" in function_names
    assert "search_query" in function_names


@patch("agno.tools.jina.log_info")
def test_read_url_logging(mock_log_info, jina_tools_basic):
    """Test that read_url logs the URL being read."""
    with patch("agno.tools.jina.httpx.Client") as mock_client:
        mock_response = Mock()
        mock_response.json.return_value = {"code": 200, "data": {"content": "test"}}
        mock_response.raise_for_status.return_value = None
        
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_client.return_value.__enter__.return_value = mock_client_instance
        
        jina_tools_basic.read_url("https://example.com")
    
    mock_log_info.assert_called_once_with("Reading URL: https://example.com")


@patch("agno.tools.jina.log_info")
def test_search_query_logging(mock_log_info, jina_tools_search):
    """Test that search_query logs the search query."""
    with patch("agno.tools.jina.httpx.Client") as mock_client:
        mock_response = Mock()
        mock_response.json.return_value = {"code": 200, "data": []}
        mock_response.raise_for_status.return_value = None
        
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_client.return_value.__enter__.return_value = mock_client_instance
        
        jina_tools_search.search_query("test query")
    
    mock_log_info.assert_called_once_with("Performing search: test query")