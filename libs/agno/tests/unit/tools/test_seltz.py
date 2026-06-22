"""Unit tests for SeltzTools class."""

import json
from unittest.mock import Mock, patch

import pytest

try:
    from seltz import Seltz  # noqa: F401
    from seltz.exceptions import (
        SeltzAPIError,
        SeltzAuthenticationError,
        SeltzConnectionError,
        SeltzRateLimitError,
        SeltzTimeoutError,
    )

    from agno.tools.seltz import SeltzTools
except (ImportError, Exception):
    pytest.skip("seltz not installed or incompatible version", allow_module_level=True)


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
    """Helper function to create mock document that mimics SDK protobuf Document."""
    doc = Mock(spec=["url", "content"])
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

    result = seltz_tools.search_seltz("test query", max_results=3)
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["url"] == "https://example.com"
    assert result_data[0]["content"] == "Example content"
    mock_seltz_client.search.assert_called_with(query="test query", max_results=3)


def test_search_default_limit(seltz_tools, mock_seltz_client):
    """Test search uses default max_results when not provided."""
    mock_response = Mock()
    mock_response.documents = [create_mock_document(url="https://example.com")]
    mock_seltz_client.search.return_value = mock_response

    result = seltz_tools.search_seltz("test query")
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["url"] == "https://example.com"
    mock_seltz_client.search.assert_called_with(query="test query", max_results=10)


def test_search_uses_toolkit_default_max_results(mock_seltz_client):
    """Test search uses configured toolkit max_results when not provided."""
    mock_response = Mock()
    mock_response.documents = [create_mock_document(url="https://example.com")]
    mock_seltz_client.search.return_value = mock_response

    with patch.dict("os.environ", {"SELTZ_API_KEY": "test_key"}):
        tools = SeltzTools(max_results=4)
        tools.client = mock_seltz_client

    tools.search_seltz("test query")

    mock_seltz_client.search.assert_called_with(query="test query", max_results=4)


def test_search_accepts_legacy_max_documents_alias(seltz_tools, mock_seltz_client):
    """Test search accepts legacy max_documents alias."""
    mock_response = Mock()
    mock_response.documents = [create_mock_document(url="https://example.com")]
    mock_seltz_client.search.return_value = mock_response

    seltz_tools.search_seltz("test query", max_documents=3)

    mock_seltz_client.search.assert_called_with(query="test query", max_results=3)


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
                tools.max_results = 10
                tools.max_documents = 10
                tools.context = None
                tools.profile = None
                tools.show_results = False
                result = tools.search_seltz("test query")
                assert "SELTZ_API_KEY not set" in result


def test_init_invalid_max_results():
    """Test initialization with invalid max_results raises error."""
    with patch.dict("os.environ", {"SELTZ_API_KEY": "test_key"}):
        with pytest.raises(ValueError, match="max_results must be greater than 0"):
            SeltzTools(max_results=0)


def test_init_invalid_max_documents():
    """Test initialization with invalid max_documents alias raises error."""
    with patch.dict("os.environ", {"SELTZ_API_KEY": "test_key"}):
        with pytest.raises(ValueError, match="max_documents must be greater than 0"):
            SeltzTools(max_documents=0)


def test_search_invalid_max_documents(seltz_tools):
    """Test search with invalid max_documents returns error."""
    result = seltz_tools.search_seltz("test query", max_documents=0)
    assert "Error" in result
    assert "max_documents must be greater than 0" in result


def test_search_invalid_max_results(seltz_tools):
    """Test search with invalid max_results returns error."""
    result = seltz_tools.search_seltz("test query", max_results=0)
    assert "Error" in result
    assert "max_results must be greater than 0" in result


def test_parse_documents_skips_empty(seltz_tools):
    """Test that documents with no url or content are skipped."""
    empty_doc = Mock(spec=["url", "content"])
    empty_doc.url = ""
    empty_doc.content = ""

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


def test_search_with_current_sdk_filters(seltz_tools, mock_seltz_client):
    """Test search with current SDK filter parameters."""
    mock_response = Mock()
    mock_response.documents = [create_mock_document(url="https://example.com", content="Example content")]
    mock_seltz_client.search.return_value = mock_response

    result = seltz_tools.search_seltz(
        "test query",
        max_results=3,
        scope="news",
        include_domains=["example.com"],
        exclude_domains=["exclude.com"],
        from_date="2026-01-01",
        to_date="2026-01-31",
    )
    result_data = json.loads(result)

    assert len(result_data) == 1
    mock_seltz_client.search.assert_called_with(
        query="test query",
        max_results=3,
        scope="news",
        include_domains=["example.com"],
        exclude_domains=["exclude.com"],
        from_date="2026-01-01",
        to_date="2026-01-31",
    )


def test_search_with_legacy_sdk_uses_includes_and_context(seltz_tools):
    """Test search with the legacy SDK API."""

    class LegacySeltzClient:
        def __init__(self, response):
            self.response = response
            self.search_mock = Mock()

        def search(self, query: str, *, includes=None, context=None, profile=None):
            self.search_mock(query=query, includes=includes, context=context, profile=profile)
            return self.response

    mock_response = Mock()
    mock_response.documents = [create_mock_document(url="https://example.com", content="Example content")]
    legacy_client = LegacySeltzClient(response=mock_response)
    seltz_tools.client = legacy_client
    seltz_tools.context = "default context"
    seltz_tools.profile = "test_profile"

    with patch("agno.tools.seltz.Includes") as mock_includes:
        mock_includes_instance = Mock()
        mock_includes.return_value = mock_includes_instance

        result = seltz_tools.search_seltz("test query", max_documents=3, context="search context")

        assert len(json.loads(result)) == 1
        mock_includes.assert_called_once_with(max_documents=3)
        legacy_client.search_mock.assert_called_once_with(
            query="test query",
            includes=mock_includes_instance,
            context="search context",
            profile="test_profile",
        )


def test_init_with_context_and_profile():
    """Test initialization with context and profile parameters."""
    with patch("agno.tools.seltz.Seltz"):
        with patch.dict("os.environ", {"SELTZ_API_KEY": "test_key"}):
            tools = SeltzTools(context="default context", profile="test_profile")
            assert tools.context == "default context"
            assert tools.profile == "test_profile"
