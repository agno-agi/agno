"""Unit tests for WebSearchTools class."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.websearch import WebSearchTools


@pytest.fixture
def mock_ddgs():
    """Create a mock DDGS instance."""
    with patch("agno.tools.websearch.DDGS") as mock_ddgs_cls:
        mock_instance = MagicMock()
        mock_ddgs_cls.return_value.__enter__ = MagicMock(return_value=mock_instance)
        mock_ddgs_cls.return_value.__exit__ = MagicMock(return_value=False)
        yield mock_instance, mock_ddgs_cls


@pytest.fixture
def websearch_tools(mock_ddgs):
    """Create a WebSearchTools instance with mocked dependencies."""
    _ = mock_ddgs  # Ensure fixture is used
    return WebSearchTools()


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================


def test_init_defaults():
    """Test initialization with default parameters."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools()
        assert tools.backend == "auto"
        assert tools.proxy is None
        assert tools.timeout == 10
        assert tools.fixed_max_results is None
        assert tools.modifier is None
        assert tools.verify_ssl is True


def test_init_with_backend():
    """Test initialization with specific backend."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(backend="duckduckgo")
        assert tools.backend == "duckduckgo"


def test_init_with_google_backend():
    """Test initialization with google backend."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(backend="google")
        assert tools.backend == "google"


def test_init_with_bing_backend():
    """Test initialization with bing backend."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(backend="bing")
        assert tools.backend == "bing"


def test_init_with_brave_backend():
    """Test initialization with brave backend."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(backend="brave")
        assert tools.backend == "brave"


def test_init_with_proxy():
    """Test initialization with proxy."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(proxy="socks5://localhost:9050")
        assert tools.proxy == "socks5://localhost:9050"


def test_init_with_timeout():
    """Test initialization with custom timeout."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(timeout=30)
        assert tools.timeout == 30


def test_init_with_fixed_max_results():
    """Test initialization with fixed max results."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(fixed_max_results=10)
        assert tools.fixed_max_results == 10


def test_init_with_modifier():
    """Test initialization with search modifier."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(modifier="site:github.com")
        assert tools.modifier == "site:github.com"


def test_init_with_verify_ssl_false():
    """Test initialization with SSL verification disabled."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(verify_ssl=False)
        assert tools.verify_ssl is False


def test_init_with_all_params():
    """Test initialization with all parameters."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(
            backend="google",
            proxy="http://proxy:8080",
            timeout=60,
            fixed_max_results=20,
            modifier="site:example.com",
            verify_ssl=False,
        )
        assert tools.backend == "google"
        assert tools.proxy == "http://proxy:8080"
        assert tools.timeout == 60
        assert tools.fixed_max_results == 20
        assert tools.modifier == "site:example.com"
        assert tools.verify_ssl is False


# ============================================================================
# TOOLKIT INTEGRATION TESTS
# ============================================================================


def test_toolkit_name():
    """Test that the toolkit has the correct name."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools()
        assert tools.name == "websearch"


def test_toolkit_default_tools():
    """Test that both search and news tools are enabled by default."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools()
        tool_names = [t.__name__ for t in tools.tools]
        assert "web_search" in tool_names
        assert "search_news" in tool_names
        assert len(tools.tools) == 2


def test_toolkit_search_only():
    """Test enabling only search function."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(enable_search=True, enable_news=False)
        tool_names = [t.__name__ for t in tools.tools]
        assert "web_search" in tool_names
        assert "search_news" not in tool_names
        assert len(tools.tools) == 1


def test_toolkit_news_only():
    """Test enabling only news function."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(enable_search=False, enable_news=True)
        tool_names = [t.__name__ for t in tools.tools]
        assert "web_search" not in tool_names
        assert "search_news" in tool_names
        assert len(tools.tools) == 1


def test_toolkit_no_tools():
    """Test disabling all tools."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(enable_search=False, enable_news=False)
        assert len(tools.tools) == 0


# ============================================================================
# WEB_SEARCH TESTS
# ============================================================================


def test_web_search_basic(websearch_tools, mock_ddgs):
    """Test basic web search."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = [
        {"title": "Result 1", "href": "https://example1.com", "body": "Description 1"},
        {"title": "Result 2", "href": "https://example2.com", "body": "Description 2"},
    ]

    result = websearch_tools.web_search("test query")
    result_data = json.loads(result)

    assert len(result_data) == 2
    assert result_data[0]["title"] == "Result 1"
    assert result_data[1]["title"] == "Result 2"
    mock_instance.text.assert_called_once()


def test_web_search_with_max_results(websearch_tools, mock_ddgs):
    """Test web search with custom max_results."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    websearch_tools.web_search("test query", max_results=10)

    mock_instance.text.assert_called_once_with(query="test query", max_results=10, backend="auto")


def test_web_search_with_fixed_max_results():
    """Test that fixed_max_results overrides max_results parameter."""
    with patch("agno.tools.websearch.DDGS") as mock_ddgs_cls:
        mock_instance = MagicMock()
        mock_ddgs_cls.return_value.__enter__ = MagicMock(return_value=mock_instance)
        mock_ddgs_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_instance.text.return_value = []

        tools = WebSearchTools(fixed_max_results=3)
        tools.web_search("test query", max_results=10)

        mock_instance.text.assert_called_once_with(query="test query", max_results=3, backend="auto")


def test_web_search_with_modifier():
    """Test web search with query modifier."""
    with patch("agno.tools.websearch.DDGS") as mock_ddgs_cls:
        mock_instance = MagicMock()
        mock_ddgs_cls.return_value.__enter__ = MagicMock(return_value=mock_instance)
        mock_ddgs_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_instance.text.return_value = []

        tools = WebSearchTools(modifier="site:github.com")
        tools.web_search("python frameworks")

        mock_instance.text.assert_called_once_with(
            query="site:github.com python frameworks", max_results=5, backend="auto"
        )


def test_web_search_with_backend():
    """Test web search with specific backend."""
    with patch("agno.tools.websearch.DDGS") as mock_ddgs_cls:
        mock_instance = MagicMock()
        mock_ddgs_cls.return_value.__enter__ = MagicMock(return_value=mock_instance)
        mock_ddgs_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_instance.text.return_value = []

        tools = WebSearchTools(backend="google")
        tools.web_search("test query")

        mock_instance.text.assert_called_once_with(query="test query", max_results=5, backend="google")


def test_web_search_empty_results(websearch_tools, mock_ddgs):
    """Test web search with empty results."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    result = websearch_tools.web_search("obscure query")
    result_data = json.loads(result)

    assert result_data == []


def test_web_search_json_serialization(websearch_tools, mock_ddgs):
    """Test that web search returns valid JSON."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = [{"title": "Test", "href": "https://test.com", "body": "Test body"}]

    result = websearch_tools.web_search("test")

    # Should not raise an exception
    parsed = json.loads(result)
    assert isinstance(parsed, list)

    # Verify it can be serialized again (round-trip test)
    json.dumps(parsed)


# ============================================================================
# SEARCH_NEWS TESTS
# ============================================================================


def test_search_news_basic(websearch_tools, mock_ddgs):
    """Test basic news search."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = [
        {"title": "News 1", "url": "https://news1.com", "body": "News body 1", "date": "2024-01-01"},
        {"title": "News 2", "url": "https://news2.com", "body": "News body 2", "date": "2024-01-02"},
    ]

    result = websearch_tools.search_news("test news")
    result_data = json.loads(result)

    assert len(result_data) == 2
    assert result_data[0]["title"] == "News 1"
    assert result_data[1]["title"] == "News 2"
    mock_instance.news.assert_called_once()


def test_search_news_with_max_results(websearch_tools, mock_ddgs):
    """Test news search with custom max_results."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = []

    websearch_tools.search_news("test news", max_results=10)

    mock_instance.news.assert_called_once_with(query="test news", max_results=10, backend="auto")


def test_search_news_with_fixed_max_results():
    """Test that fixed_max_results overrides max_results parameter for news."""
    with patch("agno.tools.websearch.DDGS") as mock_ddgs_cls:
        mock_instance = MagicMock()
        mock_ddgs_cls.return_value.__enter__ = MagicMock(return_value=mock_instance)
        mock_ddgs_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_instance.news.return_value = []

        tools = WebSearchTools(fixed_max_results=3)
        tools.search_news("test news", max_results=10)

        mock_instance.news.assert_called_once_with(query="test news", max_results=3, backend="auto")


def test_search_news_with_backend():
    """Test news search with specific backend."""
    with patch("agno.tools.websearch.DDGS") as mock_ddgs_cls:
        mock_instance = MagicMock()
        mock_ddgs_cls.return_value.__enter__ = MagicMock(return_value=mock_instance)
        mock_ddgs_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_instance.news.return_value = []

        tools = WebSearchTools(backend="bing")
        tools.search_news("test news")

        mock_instance.news.assert_called_once_with(query="test news", max_results=5, backend="bing")


def test_search_news_empty_results(websearch_tools, mock_ddgs):
    """Test news search with empty results."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = []

    result = websearch_tools.search_news("obscure news")
    result_data = json.loads(result)

    assert result_data == []


def test_search_news_json_serialization(websearch_tools, mock_ddgs):
    """Test that news search returns valid JSON."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = [{"title": "Test News", "url": "https://test.com", "body": "Test body"}]

    result = websearch_tools.search_news("test")

    # Should not raise an exception
    parsed = json.loads(result)
    assert isinstance(parsed, list)

    # Verify it can be serialized again (round-trip test)
    json.dumps(parsed)


# ============================================================================
# DDGS CLIENT CONFIGURATION TESTS
# ============================================================================


def test_ddgs_client_with_proxy():
    """Test that DDGS client is initialized with proxy."""
    with patch("agno.tools.websearch.DDGS") as mock_ddgs_cls:
        mock_instance = MagicMock()
        mock_ddgs_cls.return_value.__enter__ = MagicMock(return_value=mock_instance)
        mock_ddgs_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_instance.text.return_value = []

        tools = WebSearchTools(proxy="socks5://localhost:9050")
        tools.web_search("test")

        mock_ddgs_cls.assert_called_with(proxy="socks5://localhost:9050", timeout=10, verify=True)


def test_ddgs_client_with_timeout():
    """Test that DDGS client is initialized with custom timeout."""
    with patch("agno.tools.websearch.DDGS") as mock_ddgs_cls:
        mock_instance = MagicMock()
        mock_ddgs_cls.return_value.__enter__ = MagicMock(return_value=mock_instance)
        mock_ddgs_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_instance.text.return_value = []

        tools = WebSearchTools(timeout=60)
        tools.web_search("test")

        mock_ddgs_cls.assert_called_with(proxy=None, timeout=60, verify=True)


def test_ddgs_client_with_verify_ssl_false():
    """Test that DDGS client is initialized with SSL verification disabled."""
    with patch("agno.tools.websearch.DDGS") as mock_ddgs_cls:
        mock_instance = MagicMock()
        mock_ddgs_cls.return_value.__enter__ = MagicMock(return_value=mock_instance)
        mock_ddgs_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_instance.text.return_value = []

        tools = WebSearchTools(verify_ssl=False)
        tools.web_search("test")

        mock_ddgs_cls.assert_called_with(proxy=None, timeout=10, verify=False)


def test_ddgs_client_with_all_params():
    """Test that DDGS client is initialized with all parameters."""
    with patch("agno.tools.websearch.DDGS") as mock_ddgs_cls:
        mock_instance = MagicMock()
        mock_ddgs_cls.return_value.__enter__ = MagicMock(return_value=mock_instance)
        mock_ddgs_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_instance.text.return_value = []

        tools = WebSearchTools(
            proxy="http://proxy:8080",
            timeout=30,
            verify_ssl=False,
        )
        tools.web_search("test")

        mock_ddgs_cls.assert_called_with(proxy="http://proxy:8080", timeout=30, verify=False)


# ============================================================================
# EXCEPTION HANDLING TESTS
# ============================================================================


def test_web_search_exception_propagation(websearch_tools, mock_ddgs):
    """Test that exceptions from DDGS are propagated."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.side_effect = Exception("API Error")

    with pytest.raises(Exception, match="API Error"):
        websearch_tools.web_search("test query")


def test_search_news_exception_propagation(websearch_tools, mock_ddgs):
    """Test that exceptions from DDGS news are propagated."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.side_effect = Exception("News API Error")

    with pytest.raises(Exception, match="News API Error"):
        websearch_tools.search_news("test news")


# ============================================================================
# EDGE CASES
# ============================================================================


def test_web_search_special_characters(websearch_tools, mock_ddgs):
    """Test web search with special characters in query."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    websearch_tools.web_search("test query with special chars: @#$%")

    mock_instance.text.assert_called_once()
    call_args = mock_instance.text.call_args
    assert "test query with special chars: @#$%" in call_args[1]["query"]


def test_search_news_special_characters(websearch_tools, mock_ddgs):
    """Test news search with special characters in query."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = []

    websearch_tools.search_news("test news with special chars: @#$%")

    mock_instance.news.assert_called_once()
    call_args = mock_instance.news.call_args
    assert call_args[1]["query"] == "test news with special chars: @#$%"


def test_web_search_unicode_query(websearch_tools, mock_ddgs):
    """Test web search with unicode characters."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    websearch_tools.web_search("日本語テスト")

    mock_instance.text.assert_called_once()
    call_args = mock_instance.text.call_args
    assert call_args[1]["query"] == "日本語テスト"


def test_search_news_unicode_query(websearch_tools, mock_ddgs):
    """Test news search with unicode characters."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = []

    websearch_tools.search_news("日本語ニュース")

    mock_instance.news.assert_called_once()
    call_args = mock_instance.news.call_args
    assert call_args[1]["query"] == "日本語ニュース"


def test_web_search_long_query(websearch_tools, mock_ddgs):
    """Test web search with a very long query."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []
    long_query = "test " * 100

    websearch_tools.web_search(long_query)

    mock_instance.text.assert_called_once()


def test_modifier_with_empty_query():
    """Test modifier is prepended even with empty-ish query."""
    with patch("agno.tools.websearch.DDGS") as mock_ddgs_cls:
        mock_instance = MagicMock()
        mock_ddgs_cls.return_value.__enter__ = MagicMock(return_value=mock_instance)
        mock_ddgs_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_instance.text.return_value = []

        tools = WebSearchTools(modifier="site:github.com")
        tools.web_search("")

        mock_instance.text.assert_called_once_with(query="site:github.com ", max_results=5, backend="auto")
