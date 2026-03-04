"""Unit tests for SeltzTools class."""

import json
from unittest.mock import Mock, patch

import pytest

pytest.importorskip("seltz")

from seltz.exceptions import (
    SeltzAPIError,
    SeltzAuthenticationError,
    SeltzConnectionError,
    SeltzRateLimitError,
    SeltzTimeoutError,
)

from agno.tools.seltz import SeltzTools


@pytest.fixture
def mock_seltz_client():
    """Create a mock Seltz API client."""
    with patch("agno.tools.seltz.Seltz") as mock_seltz:
        mock_client = Mock()
        mock_seltz.return_value = mock_client
        return mock_client


@pytest.fixture
def seltz_tools(mock_seltz_client):
    """Create SeltzTools instance with mocked API."""
    with patch.dict("os.environ", {"SELTZ_API_KEY": "test_key"}):
        tools = SeltzTools()
        tools.client = mock_seltz_client
        return tools


def create_mock_document(url: str, content: str | None = None):
    """Helper function to create mock document."""
    doc = Mock()
    doc.url = url
    doc.content = content
    return doc


def test_init_with_api_key():
    """Test initialization with provided API key."""
    with patch("agno.tools.seltz.Seltz") as mock_seltz:
        with patch.dict("os.environ", {"SELTZ_API_KEY": "test_key"}):
            SeltzTools()
            mock_seltz.assert_called_once_with(api_key="test_key")


def test_init_with_search_disabled():
    """Test initialization with search tool disabled."""
    with patch.dict("os.environ", {"SELTZ_API_KEY": "test_key"}):
        tools = SeltzTools(enable_search=False)
        assert "search_seltz" not in [func.name for func in tools.functions.values()]


def test_init_with_custom_endpoint():
    """Test initialization with custom endpoint and insecure flag."""
    with patch("agno.tools.seltz.Seltz") as mock_seltz:
        with patch.dict("os.environ", {"SELTZ_API_KEY": "test_key"}):
            SeltzTools(endpoint="custom.endpoint.ai", insecure=True)
            mock_seltz.assert_called_once_with(api_key="test_key", endpoint="custom.endpoint.ai", insecure=True)


def test_search_success(seltz_tools, mock_seltz_client):
    """Test successful search operation."""
    mock_response = Mock()
    mock_response.documents = [create_mock_document(url="https://example.com", content="Example content")]
    mock_seltz_client.search.return_value = mock_response

    result = seltz_tools.search_seltz("test query", max_documents=3)
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["url"] == "https://example.com"
    assert result_data[0]["content"] == "Example content"
    mock_seltz_client.search.assert_called_with("test query", max_documents=3)


def test_search_default_limit(seltz_tools, mock_seltz_client):
    """Test search uses default max_documents when not provided."""
    mock_response = Mock()
    mock_response.documents = [create_mock_document(url="https://example.com")]
    mock_seltz_client.search.return_value = mock_response

    result = seltz_tools.search_seltz("test query")
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["url"] == "https://example.com"
    mock_seltz_client.search.assert_called_with("test query", max_documents=10)


def test_parse_documents_with_missing_fields(seltz_tools):
    """Test parsing documents with missing optional fields."""
    mock_doc = create_mock_document(url="https://example.com")
    mock_response = Mock()
    mock_response.documents = [mock_doc]

    result = seltz_tools._parse_documents(mock_response.documents)
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["url"] == "https://example.com"
    assert "content" not in result_data[0]


def test_search_empty_query(seltz_tools):
    """Test search with empty query returns error."""
    result = seltz_tools.search_seltz("")
    assert "Error" in result
    assert "provide a query" in result


def test_search_without_api_key():
    """Test search without API key returns error."""
    with patch("agno.tools.seltz.Seltz"):
        with patch.dict("os.environ", {"SELTZ_API_KEY": ""}, clear=False):
            with patch.object(SeltzTools, "__init__", lambda self, **kwargs: None):
                tools = SeltzTools()
                tools.client = None
                tools.max_documents = 10
                tools.show_results = False
                result = tools.search_seltz("test query")
                assert "SELTZ_API_KEY not set" in result


def test_init_invalid_max_documents():
    """Test initialization with invalid max_documents raises error."""
    with patch.dict("os.environ", {"SELTZ_API_KEY": "test_key"}):
        with pytest.raises(ValueError, match="max_documents must be greater than 0"):
            SeltzTools(max_documents=0)


def test_search_invalid_max_documents(seltz_tools):
    """Test search with invalid max_documents returns error."""
    result = seltz_tools.search_seltz("test query", max_documents=0)
    assert "Error" in result
    assert "max_documents must be greater than 0" in result


def test_parse_documents_skips_empty(seltz_tools):
    """Test that documents with no url or content are skipped."""
    empty_doc = Mock()
    empty_doc.url = None
    empty_doc.content = None

    result = seltz_tools._parse_documents([empty_doc])
    result_data = json.loads(result)

    assert len(result_data) == 0


def test_init_with_all_flag():
    """Test initialization with all=True enables all tools."""
    with patch("agno.tools.seltz.Seltz"):
        with patch.dict("os.environ", {"SELTZ_API_KEY": "test_key"}):
            tools = SeltzTools(all=True, enable_search=False)
            assert "search_seltz" in [func.name for func in tools.functions.values()]


@pytest.mark.parametrize(
    "exception",
    [
        Exception("Unknown error"),
        SeltzAuthenticationError("Invalid API key"),
        SeltzConnectionError("Connection failed"),
        SeltzTimeoutError("Request timed out"),
        SeltzRateLimitError("Rate limit exceeded"),
        SeltzAPIError("API error"),
    ],
)
def test_error_handling(seltz_tools, mock_seltz_client, exception):
    """Test error handling in search."""
    mock_seltz_client.search.side_effect = exception

    result = seltz_tools.search_seltz("test query")
    assert "Error" in result
