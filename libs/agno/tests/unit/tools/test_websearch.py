"""Unit tests for WebSearchTools class."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.websearch import VALID_TIMELIMITS, WebSearchTools


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
        tools = WebSearchTools()
        assert tools.backend == "auto"
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
        tools = WebSearchTools(timelimit="d")
        assert tools.timelimit == "d"


def test_init_with_region():
    """Test initialization with region parameter."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(region="us-en")
        assert tools.region == "us-en"


def test_init_with_backend():
    """Test initialization with custom backend parameter."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(backend="google")
        assert tools.backend == "google"


def test_init_with_all_params():
    """Test initialization with all parameters."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(
            enable_search=True,
            enable_news=True,
            backend="bing",
            modifier="site:example.com",
            fixed_max_results=20,
            proxy="http://proxy:8080",
            timeout=60,
            verify_ssl=False,
            timelimit="m",
            region="ru-ru",
        )
        assert tools.backend == "bing"
        assert tools.proxy == "http://proxy:8080"
        assert tools.timeout == 60
        assert tools.fixed_max_results == 20
        assert tools.modifier == "site:example.com"
        assert tools.verify_ssl is False
        assert tools.timelimit == "m"
        assert tools.region == "ru-ru"


# ============================================================================
# TIMELIMIT VALIDATION TESTS
# ============================================================================


def test_valid_timelimit_day():
    """Test that 'd' is a valid timelimit."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(timelimit="d")
        assert tools.timelimit == "d"


def test_valid_timelimit_week():
    """Test that 'w' is a valid timelimit."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(timelimit="w")
        assert tools.timelimit == "w"


def test_valid_timelimit_month():
    """Test that 'm' is a valid timelimit."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(timelimit="m")
        assert tools.timelimit == "m"


def test_valid_timelimit_year():
    """Test that 'y' is a valid timelimit."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(timelimit="y")
        assert tools.timelimit == "y"


def test_valid_timelimit_none():
    """Test that None is a valid timelimit."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(timelimit=None)
        assert tools.timelimit is None


def test_invalid_timelimit_raises_error():
    """Test that invalid timelimit raises ValueError."""
    with patch("agno.tools.websearch.DDGS"):
        with pytest.raises(ValueError) as exc_info:
            WebSearchTools(timelimit="invalid")
        assert "Invalid timelimit 'invalid'" in str(exc_info.value)
        assert "'d' (day)" in str(exc_info.value)
        assert "'w' (week)" in str(exc_info.value)
        assert "'m' (month)" in str(exc_info.value)
        assert "'y' (year)" in str(exc_info.value)


def test_invalid_timelimit_empty_string():
    """Test that empty string timelimit raises ValueError."""
    with patch("agno.tools.websearch.DDGS"):
        with pytest.raises(ValueError) as exc_info:
            WebSearchTools(timelimit="")
        assert "Invalid timelimit ''" in str(exc_info.value)


def test_invalid_timelimit_uppercase():
    """Test that uppercase timelimit raises ValueError (case-sensitive)."""
    with patch("agno.tools.websearch.DDGS"):
        with pytest.raises(ValueError) as exc_info:
            WebSearchTools(timelimit="D")
        assert "Invalid timelimit 'D'" in str(exc_info.value)


def test_invalid_timelimit_full_word():
    """Test that full word timelimit raises ValueError."""
    with patch("agno.tools.websearch.DDGS"):
        with pytest.raises(ValueError) as exc_info:
            WebSearchTools(timelimit="day")
        assert "Invalid timelimit 'day'" in str(exc_info.value)


def test_valid_timelimits_constant():
    """Test that VALID_TIMELIMITS contains expected values."""
    assert VALID_TIMELIMITS == frozenset({"d", "w", "m", "y"})


# ============================================================================
# TOOL REGISTRATION TESTS
# ============================================================================


def test_enable_search_only():
    """Test enabling only search function."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(enable_search=True, enable_news=False)
        tool_names = [t.__name__ for t in tools.tools]
        assert "web_search" in tool_names
        assert "search_news" not in tool_names


def test_enable_news_only():
    """Test enabling only news function."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(enable_search=False, enable_news=True)
        tool_names = [t.__name__ for t in tools.tools]
        assert "web_search" not in tool_names
        assert "search_news" in tool_names


def test_enable_both():
    """Test enabling both search and news functions."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(enable_search=True, enable_news=True)
        tool_names = [t.__name__ for t in tools.tools]
        assert "web_search" in tool_names
        assert "search_news" in tool_names


def test_disable_both():
    """Test disabling both functions."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(enable_search=False, enable_news=False)
        assert len(tools.tools) == 0


# ============================================================================
# WEB SEARCH TESTS
# ============================================================================


def test_web_search_basic(mock_ddgs):
    """Test basic web search."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = [
        {"title": "Result 1", "href": "https://example.com", "body": "Description 1"},
    ]

    tools = WebSearchTools()
    result = tools.web_search("test query")
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["title"] == "Result 1"
    mock_instance.text.assert_called_once_with(query="test query", max_results=5, backend="auto")


def test_web_search_with_timelimit(mock_ddgs):
    """Test that timelimit is passed to ddgs.text()."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools(timelimit="d")
    tools.web_search("test query")

    mock_instance.text.assert_called_once_with(query="test query", max_results=5, backend="auto", timelimit="d")


def test_web_search_with_region(mock_ddgs):
    """Test that region is passed to ddgs.text()."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools(region="us-en")
    tools.web_search("test query")

    mock_instance.text.assert_called_once_with(query="test query", max_results=5, backend="auto", region="us-en")


def test_web_search_with_modifier(mock_ddgs):
    """Test that modifier is prepended to query."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools(modifier="site:github.com")
    tools.web_search("python")

    mock_instance.text.assert_called_once_with(query="site:github.com python", max_results=5, backend="auto")


def test_web_search_with_fixed_max_results(mock_ddgs):
    """Test that fixed_max_results overrides max_results parameter."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools(fixed_max_results=10)
    tools.web_search("test", max_results=5)  # Should use 10, not 5

    mock_instance.text.assert_called_once_with(query="test", max_results=10, backend="auto")


def test_web_search_with_custom_max_results(mock_ddgs):
    """Test web search with custom max_results parameter."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools()
    tools.web_search("test", max_results=20)

    mock_instance.text.assert_called_once_with(query="test", max_results=20, backend="auto")


def test_web_search_without_optional_params(mock_ddgs):
    """Test that optional params are not passed when None."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools()
    tools.web_search("test query")

    # Should not include timelimit or region
    mock_instance.text.assert_called_once_with(query="test query", max_results=5, backend="auto")


def test_web_search_with_all_params(mock_ddgs):
    """Test web search with all parameters."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = [
        {"title": "Result 1", "href": "https://example.com", "body": "Description 1"},
    ]

    tools = WebSearchTools(
        backend="google",
        timelimit="w",
        region="uk-en",
        modifier="site:docs.python.org",
        fixed_max_results=15,
    )
    result = tools.web_search("asyncio")
    result_data = json.loads(result)

    assert len(result_data) == 1
    mock_instance.text.assert_called_once_with(
        query="site:docs.python.org asyncio",
        max_results=15,
        backend="google",
        timelimit="w",
        region="uk-en",
    )


# ============================================================================
# NEWS SEARCH TESTS
# ============================================================================


def test_search_news_basic(mock_ddgs):
    """Test basic news search."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = [
        {"title": "News 1", "url": "https://news.com", "body": "News body 1"},
    ]

    tools = WebSearchTools()
    result = tools.search_news("breaking news")
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["title"] == "News 1"
    mock_instance.news.assert_called_once_with(query="breaking news", max_results=5, backend="auto")


def test_search_news_with_timelimit(mock_ddgs):
    """Test that timelimit is passed to ddgs.news()."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = []

    tools = WebSearchTools(timelimit="d")
    tools.search_news("test news")

    mock_instance.news.assert_called_once_with(query="test news", max_results=5, backend="auto", timelimit="d")


def test_search_news_with_region(mock_ddgs):
    """Test that region is passed to ddgs.news()."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = []

    tools = WebSearchTools(region="de-de")
    tools.search_news("test news")

    mock_instance.news.assert_called_once_with(query="test news", max_results=5, backend="auto", region="de-de")


def test_search_news_with_fixed_max_results(mock_ddgs):
    """Test that fixed_max_results overrides max_results parameter."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = []

    tools = WebSearchTools(fixed_max_results=3)
    tools.search_news("test", max_results=10)  # Should use 3, not 10

    mock_instance.news.assert_called_once_with(query="test", max_results=3, backend="auto")


def test_search_news_with_all_params(mock_ddgs):
    """Test news search with all parameters."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = [
        {"title": "News 1", "url": "https://news.com", "body": "News body 1"},
    ]

    tools = WebSearchTools(
        backend="bing",
        timelimit="m",
        region="fr-fr",
        fixed_max_results=8,
    )
    result = tools.search_news("technology")
    result_data = json.loads(result)

    assert len(result_data) == 1
    mock_instance.news.assert_called_once_with(
        query="technology",
        max_results=8,
        backend="bing",
        timelimit="m",
        region="fr-fr",
    )


# ============================================================================
# BACKEND TESTS
# ============================================================================


def test_backend_auto(mock_ddgs):
    """Test auto backend selection."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools(backend="auto")
    tools.web_search("test")

    call_kwargs = mock_instance.text.call_args[1]
    assert call_kwargs["backend"] == "auto"


def test_backend_duckduckgo(mock_ddgs):
    """Test DuckDuckGo backend."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools(backend="duckduckgo")
    tools.web_search("test")

    call_kwargs = mock_instance.text.call_args[1]
    assert call_kwargs["backend"] == "duckduckgo"


def test_backend_google(mock_ddgs):
    """Test Google backend."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools(backend="google")
    tools.web_search("test")

    call_kwargs = mock_instance.text.call_args[1]
    assert call_kwargs["backend"] == "google"


def test_backend_bing(mock_ddgs):
    """Test Bing backend."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools(backend="bing")
    tools.web_search("test")

    call_kwargs = mock_instance.text.call_args[1]
    assert call_kwargs["backend"] == "bing"


def test_backend_brave(mock_ddgs):
    """Test Brave backend."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools(backend="brave")
    tools.web_search("test")

    call_kwargs = mock_instance.text.call_args[1]
    assert call_kwargs["backend"] == "brave"


def test_backend_yandex(mock_ddgs):
    """Test Yandex backend."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools(backend="yandex")
    tools.web_search("test")

    call_kwargs = mock_instance.text.call_args[1]
    assert call_kwargs["backend"] == "yandex"


def test_backend_yahoo(mock_ddgs):
    """Test Yahoo backend."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools(backend="yahoo")
    tools.web_search("test")

    call_kwargs = mock_instance.text.call_args[1]
    assert call_kwargs["backend"] == "yahoo"


# ============================================================================
# DDGS CLIENT CONFIGURATION TESTS
# ============================================================================


def test_ddgs_client_with_proxy(mock_ddgs):
    """Test that proxy is stored correctly."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(proxy="socks5://localhost:9050")
        assert tools.proxy == "socks5://localhost:9050"


def test_ddgs_client_with_timeout(mock_ddgs):
    """Test that timeout is stored correctly."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(timeout=30)
        assert tools.timeout == 30


def test_ddgs_client_with_verify_ssl_false(mock_ddgs):
    """Test that verify_ssl=False is stored correctly."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(verify_ssl=False)
        assert tools.verify_ssl is False


def test_ddgs_client_with_all_config(mock_ddgs):
    """Test DDGS client with all configuration options."""
    with patch("agno.tools.websearch.DDGS"):
        tools = WebSearchTools(
            proxy="http://proxy:8080",
            timeout=60,
            verify_ssl=False,
        )
        assert tools.proxy == "http://proxy:8080"
        assert tools.timeout == 60
        assert tools.verify_ssl is False


# ============================================================================
# REGION TESTS
# ============================================================================


def test_region_us_en(mock_ddgs):
    """Test US English region."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools(region="us-en")
    tools.web_search("test")

    call_kwargs = mock_instance.text.call_args[1]
    assert call_kwargs["region"] == "us-en"


def test_region_uk_en(mock_ddgs):
    """Test UK English region."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools(region="uk-en")
    tools.web_search("test")

    call_kwargs = mock_instance.text.call_args[1]
    assert call_kwargs["region"] == "uk-en"


def test_region_de_de(mock_ddgs):
    """Test German region."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools(region="de-de")
    tools.web_search("test")

    call_kwargs = mock_instance.text.call_args[1]
    assert call_kwargs["region"] == "de-de"


def test_region_fr_fr(mock_ddgs):
    """Test French region."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools(region="fr-fr")
    tools.web_search("test")

    call_kwargs = mock_instance.text.call_args[1]
    assert call_kwargs["region"] == "fr-fr"


def test_region_ru_ru(mock_ddgs):
    """Test Russian region."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools(region="ru-ru")
    tools.web_search("test")

    call_kwargs = mock_instance.text.call_args[1]
    assert call_kwargs["region"] == "ru-ru"


# ============================================================================
# JSON OUTPUT TESTS
# ============================================================================


def test_web_search_returns_json(mock_ddgs):
    """Test that web_search returns valid JSON."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = [
        {"title": "Test", "href": "https://test.com", "body": "Test body"},
    ]

    tools = WebSearchTools()
    result = tools.web_search("test")

    # Should be valid JSON
    parsed = json.loads(result)
    assert isinstance(parsed, list)
    assert len(parsed) == 1


def test_search_news_returns_json(mock_ddgs):
    """Test that search_news returns valid JSON."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = [
        {"title": "News", "url": "https://news.com", "body": "News body"},
    ]

    tools = WebSearchTools()
    result = tools.search_news("test")

    # Should be valid JSON
    parsed = json.loads(result)
    assert isinstance(parsed, list)
    assert len(parsed) == 1


def test_web_search_empty_results(mock_ddgs):
    """Test web_search with empty results."""
    mock_instance, _ = mock_ddgs
    mock_instance.text.return_value = []

    tools = WebSearchTools()
    result = tools.web_search("nonexistent query")

    parsed = json.loads(result)
    assert parsed == []


def test_search_news_empty_results(mock_ddgs):
    """Test search_news with empty results."""
    mock_instance, _ = mock_ddgs
    mock_instance.news.return_value = []

    tools = WebSearchTools()
    result = tools.search_news("nonexistent news")

    parsed = json.loads(result)
    assert parsed == []
