"""Unit tests for DuckDuckGoTools class."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.duckduckgo import DuckDuckGoTools


@pytest.fixture
def mock_ddgs():
    """Create a mock DDGS instance."""
    with patch("agno.tools.websearch.DDGS") as mock_ddgs_cls:
        mock_instance = MagicMock()
        mock_ddgs_cls.return_value.__enter__ = MagicMock(return_value=mock_instance)
        mock_ddgs_cls.return_value.__exit__ = MagicMock(return_value=False)
        yield mock_instance, mock_ddgs_cls


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================


def test_init_defaults():
    """Test initialization with default parameters."""
    with patch("agno.tools.websearch.DDGS"):
        tools = DuckDuckGoTools()
        assert tools.backend == "duckduckgo"
        assert tools.proxy is None
        assert tools.timeout == 10
        assert tools.fixed_max_results is None
        assert tools.modifier is None
        assert tools.verify_ssl is True
        assert tools.timelimit is None
        assert tools.region is None


def test_init_with_timelimit():
    """Test initialization with timelimit parameter."""
    with patch("agno.tools.websearch.DDGS"):
        tools = DuckDuckGoTools(timelimit="d")
        assert tools.timelimit == "d"


def test_init_with_region():
    """Test initialization with region parameter."""
    with patch("agno.tools.websearch.DDGS"):
        tools = DuckDuckGoTools(region="us-en")
        assert tools.region == "us-en"


def test_init_with_backend():
    """Test initialization with custom backend parameter."""
    with patch("agno.tools.websearch.DDGS"):
        tools = DuckDuckGoTools(backend="html")
        assert tools.backend == "html"


def test_init_backend_defaults_to_duckduckgo():
    """Test that backend defaults to duckduckgo when not specified."""
    with patch("agno.tools.websearch.DDGS"):
        tools = DuckDuckGoTools()
        assert tools.backend == "duckduckgo"


def test_init_with_all_new_params():
    """Test initialization with all new parameters."""
    with patch("agno.tools.websearch.DDGS"):
        tools = DuckDuckGoTools(
            timelimit="w",
            region="uk-en",
            backend="lite",
        )
        assert tools.timelimit == "w"
        assert tools.region == "uk-en"
        assert tools.backend == "lite"


def test_init_with_all_params():
    """Test initialization with all parameters."""
    with patch("agno.tools.websearch.DDGS"):
        tools = DuckDuckGoTools(
            enable_search=True,
            enable_news=True,
            modifier="site:example.com",
            fixed_max_results=20,
            proxy="http://proxy:8080",
            timeout=60,
            verify_ssl=False,
            timelimit="m",
            region="ru-ru",
            backend="api",
        )
        assert tools.backend == "api"
        assert tools.proxy == "http://proxy:8080"
        assert tools.timeout == 60
        assert tools.fixed_max_results == 20
        assert tools.modifier == "site:example.com"
        assert tools.verify_ssl is False
        assert tools.timelimit == "m"
        assert tools.region == "ru-ru"


# ============================================================================
# BACKWARD COMPATIBILITY TESTS
# ============================================================================


def test_backward_compat_aliases():
    """Test that backward compatibility aliases exist."""
    with patch("agno.tools.websearch.DDGS"):
        tools = DuckDuckGoTools()
        assert tools.duckduckgo_search == tools.web_search
        assert tools.duckduckgo_news == tools.search_news


# ============================================================================
# SEARCH WITH TIMELIMIT TESTS
# ============================================================================


def test_web_search_with_timelimit(mock_ddgs):
    """Test that timelimit is passed to ddgs.text()."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = DuckDuckGoTools(timelimit="d")
    tools.web_search("test query")

    mock_instance.text.assert_called_once_with(query="test query", max_results=5, backend="duckduckgo", timelimit="d")


def test_search_news_with_timelimit(mock_ddgs):
    """Test that timelimit is passed to ddgs.news()."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = []

    tools = DuckDuckGoTools(timelimit="w")
    tools.search_news("test news")

    mock_instance.news.assert_called_once_with(query="test news", max_results=5, backend="duckduckgo", timelimit="w")


def test_web_search_without_timelimit(mock_ddgs):
    """Test that timelimit is not passed when None."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = DuckDuckGoTools()
    tools.web_search("test query")

    mock_instance.text.assert_called_once_with(query="test query", max_results=5, backend="duckduckgo")


# ============================================================================
# SEARCH WITH REGION TESTS
# ============================================================================


def test_web_search_with_region(mock_ddgs):
    """Test that region is passed to ddgs.text()."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = DuckDuckGoTools(region="us-en")
    tools.web_search("test query")

    mock_instance.text.assert_called_once_with(query="test query", max_results=5, backend="duckduckgo", region="us-en")


def test_search_news_with_region(mock_ddgs):
    """Test that region is passed to ddgs.news()."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = []

    tools = DuckDuckGoTools(region="uk-en")
    tools.search_news("test news")

    mock_instance.news.assert_called_once_with(query="test news", max_results=5, backend="duckduckgo", region="uk-en")


def test_web_search_without_region(mock_ddgs):
    """Test that region is not passed when None."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = DuckDuckGoTools()
    tools.web_search("test query")

    mock_instance.text.assert_called_once_with(query="test query", max_results=5, backend="duckduckgo")


# ============================================================================
# SEARCH WITH BACKEND TESTS
# ============================================================================


def test_web_search_with_custom_backend(mock_ddgs):
    """Test that custom backend is passed to ddgs.text()."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = DuckDuckGoTools(backend="html")
    tools.web_search("test query")

    mock_instance.text.assert_called_once_with(query="test query", max_results=5, backend="html")


def test_search_news_with_custom_backend(mock_ddgs):
    """Test that custom backend is passed to ddgs.news()."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = []

    tools = DuckDuckGoTools(backend="lite")
    tools.search_news("test news")

    mock_instance.news.assert_called_once_with(query="test news", max_results=5, backend="lite")


# ============================================================================
# COMBINED PARAMETERS TESTS
# ============================================================================


def test_web_search_with_all_params(mock_ddgs):
    """Test web search with timelimit, region, and custom backend."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = [
        {"title": "Result 1", "href": "https://example.com", "body": "Description 1"},
    ]

    tools = DuckDuckGoTools(
        timelimit="m",
        region="us-en",
        backend="api",
        fixed_max_results=10,
        modifier="site:github.com",
    )
    result = tools.web_search("python frameworks")
    result_data = json.loads(result)

    assert len(result_data) == 1
    mock_instance.text.assert_called_once_with(
        query="site:github.com python frameworks",
        max_results=10,
        backend="api",
        timelimit="m",
        region="us-en",
    )


def test_search_news_with_all_params(mock_ddgs):
    """Test news search with timelimit, region, and custom backend."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = [
        {"title": "News 1", "url": "https://news.com", "body": "News body 1"},
    ]

    tools = DuckDuckGoTools(
        timelimit="d",
        region="uk-en",
        backend="html",
        fixed_max_results=3,
    )
    result = tools.search_news("breaking news")
    result_data = json.loads(result)

    assert len(result_data) == 1
    mock_instance.news.assert_called_once_with(
        query="breaking news",
        max_results=3,
        backend="html",
        timelimit="d",
        region="uk-en",
    )


# ============================================================================
# TIMELIMIT VALUES TESTS
# ============================================================================


def test_timelimit_day(mock_ddgs):
    """Test timelimit with 'd' for day."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = DuckDuckGoTools(timelimit="d")
    tools.web_search("test")

    call_kwargs = mock_instance.text.call_args[1]
    assert call_kwargs["timelimit"] == "d"


def test_timelimit_week(mock_ddgs):
    """Test timelimit with 'w' for week."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = DuckDuckGoTools(timelimit="w")
    tools.web_search("test")

    call_kwargs = mock_instance.text.call_args[1]
    assert call_kwargs["timelimit"] == "w"


def test_timelimit_month(mock_ddgs):
    """Test timelimit with 'm' for month."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = DuckDuckGoTools(timelimit="m")
    tools.web_search("test")

    call_kwargs = mock_instance.text.call_args[1]
    assert call_kwargs["timelimit"] == "m"


def test_timelimit_year(mock_ddgs):
    """Test timelimit with 'y' for year."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = DuckDuckGoTools(timelimit="y")
    tools.web_search("test")

    call_kwargs = mock_instance.text.call_args[1]
    assert call_kwargs["timelimit"] == "y"


# ============================================================================
# TIMELIMIT VALIDATION TESTS
# ============================================================================


def test_invalid_timelimit_raises_error():
    """Test that invalid timelimit raises ValueError."""
    with patch("agno.tools.websearch.DDGS"):
        with pytest.raises(ValueError) as exc_info:
            DuckDuckGoTools(timelimit="invalid")
        assert "Invalid timelimit 'invalid'" in str(exc_info.value)


def test_invalid_timelimit_empty_string():
    """Test that empty string timelimit raises ValueError."""
    with patch("agno.tools.websearch.DDGS"):
        with pytest.raises(ValueError) as exc_info:
            DuckDuckGoTools(timelimit="")
        assert "Invalid timelimit ''" in str(exc_info.value)


def test_invalid_timelimit_uppercase():
    """Test that uppercase timelimit raises ValueError (case-sensitive)."""
    with patch("agno.tools.websearch.DDGS"):
        with pytest.raises(ValueError) as exc_info:
            DuckDuckGoTools(timelimit="W")
        assert "Invalid timelimit 'W'" in str(exc_info.value)


def test_invalid_timelimit_full_word():
    """Test that full word timelimit raises ValueError."""
    with patch("agno.tools.websearch.DDGS"):
        with pytest.raises(ValueError) as exc_info:
            DuckDuckGoTools(timelimit="week")
        assert "Invalid timelimit 'week'" in str(exc_info.value)
