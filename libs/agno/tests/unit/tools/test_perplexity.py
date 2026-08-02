"""Unit tests for PerplexitySearch class."""

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agno.tools.perplexity import PerplexitySearch


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Ensure PERPLEXITY_API_KEY is unset unless explicitly needed."""
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================


def test_init_with_api_key():
    """Test initialization with a provided API key."""
    tools = PerplexitySearch(api_key="test_key")
    assert tools.api_key == "test_key"
    assert tools.max_results == 5
    assert tools.max_tokens_per_page == 2048
    assert tools.search_recency_filter is None
    assert tools.search_domain_filter is None
    assert tools.search_language_filter is None
    assert tools.show_results is False


def test_init_with_env_var(monkeypatch):
    """Test initialization with PERPLEXITY_API_KEY environment variable."""
    monkeypatch.setenv("PERPLEXITY_API_KEY", "env_key")
    tools = PerplexitySearch()
    assert tools.api_key == "env_key"


def test_init_without_api_key():
    """Test initialization without any API key logs an error."""
    tools = PerplexitySearch()
    assert tools.api_key is None


def test_init_with_custom_params():
    """Test initialization with custom parameters."""
    tools = PerplexitySearch(
        api_key="test_key",
        max_results=10,
        max_tokens_per_page=4096,
        search_recency_filter="week",
        search_domain_filter=["example.com", "test.com"],
        search_language_filter=["en", "fr"],
        show_results=True,
    )
    assert tools.api_key == "test_key"
    assert tools.max_results == 10
    assert tools.max_tokens_per_page == 4096
    assert tools.search_recency_filter == "week"
    assert tools.search_domain_filter == ["example.com", "test.com"]
    assert tools.search_language_filter == ["en", "fr"]
    assert tools.show_results is True


def test_tool_registration():
    """Test that the search tool is registered correctly."""
    tools = PerplexitySearch(api_key="test_key")
    assert "search" in [func.name for func in tools.functions.values()]


def test_async_tool_registration():
    """Test that the async search tool is registered correctly."""
    tools = PerplexitySearch(api_key="test_key")
    assert "search" in [func.name for func in tools.async_functions.values()]


# ============================================================================
# SEARCH TESTS
# ============================================================================


def test_search_success():
    """Test a successful search returns parsed results."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "id": "test-id",
        "results": [
            {
                "title": "AI Agents Overview",
                "url": "https://example.com/ai-agents",
                "snippet": "AI agents are autonomous systems...",
                "date": "2024-12-15",
            },
            {
                "title": "Building AI Agents",
                "url": "https://example.com/building-agents",
                "snippet": "How to build AI agents...",
                "date": "2024-12-10",
            },
        ],
    }

    tools = PerplexitySearch(api_key="test_key")

    with patch("agno.tools.perplexity.httpx.post", return_value=mock_response) as mock_post:
        result = tools.search("AI agents")
        result_data = json.loads(result)

        assert len(result_data) == 2
        assert result_data[0]["url"] == "https://example.com/ai-agents"
        assert result_data[0]["title"] == "AI Agents Overview"
        assert result_data[0]["snippet"] == "AI agents are autonomous systems..."
        assert result_data[0]["date"] == "2024-12-15"

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["query"] == "AI agents"
        assert call_kwargs[1]["json"]["max_results"] == 5
        assert call_kwargs[1]["headers"]["X-Source"] == "agno"
        assert call_kwargs[1]["headers"]["Authorization"] == "Bearer test_key"


def test_search_with_custom_max_results():
    """Test search with overridden max_results."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"results": []}

    tools = PerplexitySearch(api_key="test_key")

    with patch("agno.tools.perplexity.httpx.post", return_value=mock_response) as mock_post:
        tools.search("test query", max_results=10)

        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["max_results"] == 10


def test_search_with_filters():
    """Test search includes configured filters in the request body."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"results": []}

    tools = PerplexitySearch(
        api_key="test_key",
        search_recency_filter="day",
        search_domain_filter=["example.com"],
        search_language_filter=["en"],
    )

    with patch("agno.tools.perplexity.httpx.post", return_value=mock_response) as mock_post:
        tools.search("test query")

        call_kwargs = mock_post.call_args
        body = call_kwargs[1]["json"]
        assert body["search_recency_filter"] == "day"
        assert body["search_domain_filter"] == ["example.com"]
        assert body["search_language_filter"] == ["en"]


def test_search_missing_optional_fields():
    """Test search handles results with missing optional fields."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "results": [
            {"url": "https://example.com"},
        ],
    }

    tools = PerplexitySearch(api_key="test_key")

    with patch("agno.tools.perplexity.httpx.post", return_value=mock_response):
        result = tools.search("test query")
        result_data = json.loads(result)

        assert len(result_data) == 1
        assert result_data[0]["url"] == "https://example.com"
        assert "title" not in result_data[0]
        assert "snippet" not in result_data[0]
        assert "date" not in result_data[0]


def test_search_empty_results():
    """Test search with empty results."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"results": []}

    tools = PerplexitySearch(api_key="test_key")

    with patch("agno.tools.perplexity.httpx.post", return_value=mock_response):
        result = tools.search("test query")
        result_data = json.loads(result)
        assert result_data == []


def test_search_api_error():
    """Test search handles API errors gracefully."""
    tools = PerplexitySearch(api_key="test_key")

    with patch("agno.tools.perplexity.httpx.post", side_effect=Exception("API connection failed")):
        result = tools.search("test query")
        result_data = json.loads(result)
        assert "error" in result_data
        assert "API connection failed" in result_data["error"]


def test_search_request_url():
    """Test that search requests are sent to the correct URL."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"results": []}

    tools = PerplexitySearch(api_key="test_key")

    with patch("agno.tools.perplexity.httpx.post", return_value=mock_response) as mock_post:
        tools.search("test query")

        call_args = mock_post.call_args
        assert call_args[0][0] == "https://api.perplexity.ai/search"


# ============================================================================
# ASYNC SEARCH TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_asearch_success():
    """Test a successful async search returns parsed results."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "id": "test-id",
        "results": [
            {
                "title": "AI Agents Overview",
                "url": "https://example.com/ai-agents",
                "snippet": "AI agents are autonomous systems...",
                "date": "2024-12-15",
            },
            {
                "title": "Building AI Agents",
                "url": "https://example.com/building-agents",
                "snippet": "How to build AI agents...",
                "date": "2024-12-10",
            },
        ],
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    tools = PerplexitySearch(api_key="test_key")

    with patch("agno.tools.perplexity.httpx.AsyncClient") as mock_async_client:
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await tools.asearch("AI agents")
        result_data = json.loads(result)

        assert len(result_data) == 2
        assert result_data[0]["url"] == "https://example.com/ai-agents"
        assert result_data[0]["title"] == "AI Agents Overview"
        assert result_data[1]["url"] == "https://example.com/building-agents"

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["json"]["query"] == "AI agents"
        assert call_kwargs[1]["json"]["max_results"] == 5


@pytest.mark.asyncio
async def test_asearch_with_filters():
    """Test async search includes configured filters in the request body."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"results": []}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    tools = PerplexitySearch(
        api_key="test_key",
        search_recency_filter="day",
        search_domain_filter=["example.com"],
        search_language_filter=["en"],
    )

    with patch("agno.tools.perplexity.httpx.AsyncClient") as mock_async_client:
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

        await tools.asearch("test query")

        call_kwargs = mock_client.post.call_args
        body = call_kwargs[1]["json"]
        assert body["search_recency_filter"] == "day"
        assert body["search_domain_filter"] == ["example.com"]
        assert body["search_language_filter"] == ["en"]


@pytest.mark.asyncio
async def test_asearch_api_error():
    """Test async search handles API errors gracefully."""
    mock_client = AsyncMock()
    mock_client.post.side_effect = Exception("API connection failed")

    tools = PerplexitySearch(api_key="test_key")

    with patch("agno.tools.perplexity.httpx.AsyncClient") as mock_async_client:
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await tools.asearch("test query")
        result_data = json.loads(result)
        assert "error" in result_data
        assert "API connection failed" in result_data["error"]


@pytest.mark.asyncio
async def test_asearch_empty_results():
    """Test async search with empty results."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"results": []}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    tools = PerplexitySearch(api_key="test_key")

    with patch("agno.tools.perplexity.httpx.AsyncClient") as mock_async_client:
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await tools.asearch("test query")
        result_data = json.loads(result)
        assert result_data == []
