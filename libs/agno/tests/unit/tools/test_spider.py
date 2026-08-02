"""Unit tests for SpiderTools class."""

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("spider")

from agno.tools.spider import SpiderTools  # noqa: E402


@pytest.fixture
def mock_spider():
    """Create a mock Spider client instance."""
    with patch("agno.tools.spider.ExternalSpider") as mock_spider_cls:
        mock_app = MagicMock()
        mock_app.search.return_value = []
        mock_app.scrape_url.return_value = []
        mock_app.crawl_url.return_value = []
        mock_spider_cls.return_value = mock_app
        yield mock_app


def get_options_sent(mock_method):
    """Return the options dict sent to the spider client method."""
    return mock_method.call_args[0][1]


# ============================================================================
# SEARCH MAX RESULTS TESTS
# ============================================================================


def test_search_web_uses_constructor_max_results(mock_spider):
    """Test that max_results set on the toolkit reaches the client."""
    tools = SpiderTools(max_results=3)
    tools.search_web("test query")

    assert get_options_sent(mock_spider.search)["num"] == 3


def test_search_web_explicit_max_results_overrides_constructor(mock_spider):
    """Test that an explicit max_results argument wins over the constructor value."""
    tools = SpiderTools(max_results=3)
    tools.search_web("test query", max_results=20)

    assert get_options_sent(mock_spider.search)["num"] == 20


def test_search_web_defaults_to_five(mock_spider):
    """Test that max_results falls back to 5 when not configured anywhere."""
    tools = SpiderTools()
    tools.search_web("test query")

    assert get_options_sent(mock_spider.search)["num"] == 5


def test_search_web_explicit_max_results_overrides_optional_params(mock_spider):
    """Test that an explicit max_results argument wins over an optional_params num key."""
    tools = SpiderTools(optional_params={"num": 1})
    tools.search_web("test query", max_results=20)

    assert get_options_sent(mock_spider.search)["num"] == 20


def test_search_web_optional_params_num_without_call_arg(mock_spider):
    """Test that an optional_params num key still beats the hardcoded default."""
    tools = SpiderTools(optional_params={"num": 7})
    tools.search_web("test query")

    assert get_options_sent(mock_spider.search)["num"] == 7


# ============================================================================
# CRAWL LIMIT TESTS
# ============================================================================


def test_crawl_explicit_limit_overrides_optional_params(mock_spider):
    """Test that an explicit limit argument wins over an optional_params limit key."""
    tools = SpiderTools(optional_params={"limit": 2})
    tools.crawl("https://example.com", limit=50)

    assert get_options_sent(mock_spider.crawl_url)["limit"] == 50


def test_crawl_optional_params_limit_without_call_arg(mock_spider):
    """Test that an optional_params limit key still beats the hardcoded default."""
    tools = SpiderTools(optional_params={"limit": 2})
    tools.crawl("https://example.com")

    assert get_options_sent(mock_spider.crawl_url)["limit"] == 2


def test_crawl_defaults_to_ten(mock_spider):
    """Test that limit falls back to 10 when not configured anywhere."""
    tools = SpiderTools()
    tools.crawl("https://example.com")

    assert get_options_sent(mock_spider.crawl_url)["limit"] == 10
