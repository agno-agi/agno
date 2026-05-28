"""Unit tests for InvisiblePlaywrightTools."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.invisible_playwright import InvisiblePlaywrightTools


@pytest.fixture
def mock_invisible():
    """Mock the InvisiblePlaywright context manager."""
    with patch("agno.tools.invisible_playwright.InvisiblePlaywright") as mock_cls:
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_browser.new_page.return_value = mock_page
        mock_cls.return_value.__enter__.return_value = mock_browser
        yield {"cls": mock_cls, "browser": mock_browser, "page": mock_page}


def test_initialization_default():
    """Default init enables only scrape_url."""
    tools = InvisiblePlaywrightTools()
    assert tools.name == "invisible_playwright_tools"
    fn_names = [f.name for f in tools.functions.values()]
    assert "scrape_url" in fn_names
    assert "crawl_site" not in fn_names
    assert "search_web" not in fn_names


def test_initialization_all_flag():
    """all=True enables every tool."""
    tools = InvisiblePlaywrightTools(all=True)
    fn_names = [f.name for f in tools.functions.values()]
    assert "scrape_url" in fn_names
    assert "crawl_site" in fn_names
    assert "search_web" in fn_names


def test_initialization_individual_flags():
    """Each enable_* flag registers its method."""
    tools = InvisiblePlaywrightTools(
        enable_scrape=False, enable_crawl=True, enable_search=True
    )
    fn_names = [f.name for f in tools.functions.values()]
    assert "scrape_url" not in fn_names
    assert "crawl_site" in fn_names
    assert "search_web" in fn_names


def test_initialization_custom_options():
    """Custom options are stored on the instance."""
    tools = InvisiblePlaywrightTools(
        seed=42,
        headless=False,
        proxy={"server": "socks5://proxy:1080"},
        locale="it-IT",
        timezone="Europe/Rome",
        max_pages=20,
        max_depth=3,
        search_engine="bing",
        num_results=10,
        max_length=2000,
    )
    assert tools._seed == 42
    assert tools._headless is False
    assert tools._proxy == {"server": "socks5://proxy:1080"}
    assert tools._locale == "it-IT"
    assert tools._timezone == "Europe/Rome"
    assert tools._max_pages == 20
    assert tools._max_depth == 3
    assert tools._search_engine == "bing"
    assert tools._num_results == 10
    assert tools._max_length == 2000


def test_scrape_url_empty():
    """Empty URL returns error string."""
    tools = InvisiblePlaywrightTools()
    assert tools.scrape_url("") == "Error: No URL provided"


def test_scrape_url_success(mock_invisible):
    """Successful scrape returns page content."""
    mock_invisible["page"].content.return_value = "<html>hello</html>"
    tools = InvisiblePlaywrightTools()
    result = tools.scrape_url("https://example.com")
    assert result == "<html>hello</html>"
    mock_invisible["page"].goto.assert_called_once_with("https://example.com")


def test_scrape_url_with_wait_selector(mock_invisible):
    """wait_for_selector is forwarded to the page."""
    mock_invisible["page"].content.return_value = "<html>after wait</html>"
    tools = InvisiblePlaywrightTools()
    tools.scrape_url("https://example.com", wait_for_selector=".content")
    mock_invisible["page"].wait_for_selector.assert_called_once_with(".content")


def test_scrape_url_truncation(mock_invisible):
    """Output is truncated to max_length when set."""
    mock_invisible["page"].content.return_value = "A" * 10000
    tools = InvisiblePlaywrightTools(max_length=100)
    result = tools.scrape_url("https://example.com")
    assert len(result) == 103
    assert result.endswith("...")


def test_scrape_url_no_truncation(mock_invisible):
    """max_length=None disables truncation."""
    mock_invisible["page"].content.return_value = "A" * 10000
    tools = InvisiblePlaywrightTools(max_length=None)
    result = tools.scrape_url("https://example.com")
    assert len(result) == 10000


def test_scrape_url_error(mock_invisible):
    """Underlying exception returns error string."""
    mock_invisible["page"].goto.side_effect = RuntimeError("boom")
    tools = InvisiblePlaywrightTools()
    result = tools.scrape_url("https://example.com")
    assert result.startswith("Error fetching https://example.com:")
    assert "boom" in result


def test_crawl_site_empty():
    """Empty URL returns error."""
    tools = InvisiblePlaywrightTools(enable_crawl=True)
    assert tools.crawl_site("") == "Error: No URL provided"


def test_crawl_site_single_page(mock_invisible):
    """When no in-domain links exist, only the start page is visited."""
    mock_invisible["page"].content.return_value = "<html>root</html>"
    mock_invisible["page"].eval_on_selector_all.return_value = []
    tools = InvisiblePlaywrightTools(enable_crawl=True, max_pages=5, max_depth=2)
    result = tools.crawl_site("https://example.com")
    data = json.loads(result)
    assert "https://example.com" in data
    assert data["https://example.com"] == "<html>root</html>"


def test_crawl_site_follows_same_domain_links(mock_invisible):
    """Links to the same domain are followed up to max_pages."""
    mock_invisible["page"].content.return_value = "<html>page</html>"
    # First call returns 2 same-domain links; subsequent calls return none
    mock_invisible["page"].eval_on_selector_all.side_effect = [
        ["https://example.com/a", "https://example.com/b"],
        [],
        [],
    ]
    tools = InvisiblePlaywrightTools(enable_crawl=True, max_pages=3, max_depth=2)
    result = tools.crawl_site("https://example.com")
    data = json.loads(result)
    assert len(data) == 3
    assert "https://example.com/a" in data
    assert "https://example.com/b" in data


def test_crawl_site_skips_external_domain(mock_invisible):
    """Cross-domain links are not followed."""
    mock_invisible["page"].content.return_value = "<html>page</html>"
    mock_invisible["page"].eval_on_selector_all.side_effect = [
        ["https://other.com/x", "https://example.com/internal"],
        [],
    ]
    tools = InvisiblePlaywrightTools(enable_crawl=True, max_pages=5, max_depth=2)
    result = tools.crawl_site("https://example.com")
    data = json.loads(result)
    assert "https://other.com/x" not in data
    assert "https://example.com/internal" in data


def test_crawl_site_respects_max_pages(mock_invisible):
    """Crawl stops at max_pages even if more links are queued."""
    mock_invisible["page"].content.return_value = "<html>p</html>"
    mock_invisible["page"].eval_on_selector_all.side_effect = [
        ["https://example.com/" + str(i) for i in range(10)],
    ] + [[]] * 10
    tools = InvisiblePlaywrightTools(enable_crawl=True, max_pages=3, max_depth=5)
    result = tools.crawl_site("https://example.com")
    data = json.loads(result)
    assert len(data) == 3


def test_search_web_empty():
    """Empty query returns error."""
    tools = InvisiblePlaywrightTools(enable_search=True)
    assert tools.search_web("") == "Error: No query provided"


def test_search_web_duckduckgo(mock_invisible):
    """DuckDuckGo search returns parsed result list."""
    mock_invisible["page"].eval_on_selector_all.return_value = [
        {"title": "Result A", "url": "https://a.com", "snippet": "snippet A"},
        {"title": "Result B", "url": "https://b.com", "snippet": "snippet B"},
    ]
    tools = InvisiblePlaywrightTools(enable_search=True, num_results=2)
    result = tools.search_web("python")
    data = json.loads(result)
    assert len(data) == 2
    assert data[0]["title"] == "Result A"
    mock_invisible["page"].goto.assert_called_with("https://duckduckgo.com/html/?q=python")


def test_search_web_bing(mock_invisible):
    """Bing engine sends query to bing.com."""
    mock_invisible["page"].eval_on_selector_all.return_value = [
        {"title": "Bing A", "url": "https://a.com", "snippet": "s"}
    ]
    tools = InvisiblePlaywrightTools(enable_search=True, search_engine="bing", num_results=1)
    tools.search_web("python")
    mock_invisible["page"].goto.assert_called_with("https://www.bing.com/search?q=python")


def test_search_web_unsupported_engine():
    """Unknown engine returns error string."""
    tools = InvisiblePlaywrightTools(enable_search=True, search_engine="yahoo")
    result = tools.search_web("python")
    assert "unsupported search engine 'yahoo'" in result


def test_search_web_error(mock_invisible):
    """Underlying exception returns error string."""
    mock_invisible["page"].goto.side_effect = RuntimeError("timeout")
    tools = InvisiblePlaywrightTools(enable_search=True)
    result = tools.search_web("python")
    assert result.startswith("Error searching for 'python':")


def test_launch_forwards_options(mock_invisible):
    """_launch builds InvisiblePlaywright with stored options."""
    tools = InvisiblePlaywrightTools(
        seed=7, headless=False, proxy={"server": "p:1"}, locale="fr-FR", timezone="Europe/Paris"
    )
    tools.scrape_url("https://example.com")
    mock_invisible["cls"].assert_called_once_with(
        seed=7,
        headless=False,
        proxy={"server": "p:1"},
        locale="fr-FR",
        timezone="Europe/Paris",
    )
