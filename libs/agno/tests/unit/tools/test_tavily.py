"""Unit tests for TavilyTools class."""

import json
from unittest.mock import Mock, patch

import pytest

from agno.tools.tavily import TavilyTools


@pytest.fixture
def mock_tavily_client():
    """Create a mock Tavily API client."""
    with patch("agno.tools.tavily.TavilyClient") as mock_tavily:
        mock_client = Mock()
        mock_tavily.return_value = mock_client
        return mock_client


@pytest.fixture
def tavily_tools_context(mock_tavily_client):
    """Create TavilyTools instance with search context enabled."""
    with patch.dict("os.environ", {"TAVILY_API_KEY": "test_key"}):
        tools = TavilyTools(enable_search=False, enable_search_context=True)
        tools.client = mock_tavily_client
        return tools


@pytest.fixture
def tavily_tools(mock_tavily_client):
    """Create TavilyTools instance with search enabled."""
    with patch.dict("os.environ", {"TAVILY_API_KEY": "test_key"}):
        tools = TavilyTools(enable_search=True, enable_search_context=False)
        tools.client = mock_tavily_client
        return tools


def test_init_with_api_key():
    """Test initialization with provided API key."""
    with patch("agno.tools.tavily.TavilyClient") as mock_tavily:
        with patch.dict("os.environ", {"TAVILY_API_KEY": "test_key"}):
            TavilyTools()
            mock_tavily.assert_called_once_with(api_key="test_key")


def test_init_with_selective_tools():
    """Test initialization with only selected tools."""
    with patch.dict("os.environ", {"TAVILY_API_KEY": "test_key"}):
        tools = TavilyTools(
            enable_search=True,
            enable_search_context=False,
        )

        assert "web_search_using_tavily" in [func.name for func in tools.functions.values()]
        assert "web_search_with_tavily" not in [func.name for func in tools.functions.values()]


def test_web_search_using_tavily_success(tavily_tools, mock_tavily_client):
    """Test successful search operation for web_search_using_tavily."""
    tavily_tools.format = "json"
    mock_response = {
        "answer": "Test answer",
        "response_time": 1.0,
        "auto_parameters": {},
        "request_id": "123",
        "results": [
            {"title": "Test Title", "url": "http://example.com", "content": "Test content", "score": 0.9}
        ]
    }
    mock_tavily_client.search.return_value = mock_response

    result = tavily_tools.web_search_using_tavily("test query", max_results=1)
    result_data = json.loads(result)

    assert result_data["query"] == "test query"
    assert result_data["answer"] == "Test answer"
    assert len(result_data["results"]) == 1
    assert result_data["results"][0]["title"] == "Test Title"
    assert result_data["results"][0]["url"] == "http://example.com"


def test_web_search_using_tavily_markdown_format(tavily_tools, mock_tavily_client):
    """Test web_search_using_tavily with markdown format."""
    tavily_tools.format = "markdown"
    mock_response = {
        "answer": "Test answer",
        "response_time": 1.0,
        "results": [
            {"title": "Test Title", "url": "http://example.com", "content": "Test content", "score": 0.9}
        ]
    }
    mock_tavily_client.search.return_value = mock_response

    result = tavily_tools.web_search_using_tavily("test query")

    assert "# test query" in result
    assert "### Summary" in result
    assert "Test answer" in result
    assert "[Test Title](http://example.com)" in result


def test_web_search_with_tavily_success(tavily_tools_context, mock_tavily_client):
    """Test successful search operation for web_search_with_tavily."""
    mock_response = "Mocked search context result"
    mock_tavily_client.get_search_context.return_value = mock_response

    result = tavily_tools_context.web_search_with_tavily("test query")
    assert result == mock_response
    mock_tavily_client.get_search_context.assert_called_once_with(
        query="test query",
        search_depth=tavily_tools_context.search_depth,
        max_tokens=tavily_tools_context.max_tokens,
        include_answer=tavily_tools_context.include_answer
    )