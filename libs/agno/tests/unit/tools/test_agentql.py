"""Unit tests for AgentQLTools class."""

from unittest.mock import Mock, patch

import pytest

from agno.tools.agentql import AgentQLTools


@pytest.fixture
def mock_playwright():
    """Create a mock Playwright instance."""
    with patch("agno.tools.agentql.sync_playwright") as mock_pw:
        mock_browser = Mock()
        mock_page = Mock()
        mock_browser.new_page.return_value = mock_page
        mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = mock_browser
        return mock_pw


@pytest.fixture
def agentql_tools():
    """Create AgentQLTools instance with test API key."""
    with patch.dict("os.environ", {"AGENTQL_API_KEY": "test_key"}):
        return AgentQLTools()


def test_init_with_api_key():
    """Test initialization with API key."""
    tools = AgentQLTools(api_key="test_key")
    assert tools.api_key == "test_key"


def test_init_without_api_key():
    """Test initialization without API key."""
    with patch.dict("os.environ", clear=True):
        with pytest.raises(ValueError, match="AGENTQL_API_KEY not set"):
            AgentQLTools()


def test_scrape_website_no_url(agentql_tools):
    """Test scraping with no URL provided."""
    result = agentql_tools.scrape_website("")
    assert result == "No URL provided"


def test_scrape_website_no_api_key():
    """Test scraping without API key."""
    with patch.dict("os.environ", clear=True):
        with pytest.raises(ValueError, match="AGENTQL_API_KEY not set"):
            tools = AgentQLTools()
            tools.scrape_website("https://example.com")


def test_custom_scrape_no_query(agentql_tools):
    """Test custom scraping without a query."""
    result = agentql_tools.custom_scrape_website("https://example.com")
    assert "Custom AgentQL query not provided" in result


def test_scrape_website_success(mock_playwright, agentql_tools):
    """Test successful website scraping."""
    mock_page = mock_playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_page.return_value
    mock_page.query_data.return_value = {"text_content": ["text1", "text2", "text2", "text3"]}

    result = agentql_tools.scrape_website("https://example.com")
    assert "Example Domain" in result
