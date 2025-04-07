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
def mock_agentql():
    """Create a mock AgentQL wrapper."""
    with patch("agno.tools.agentql.agentql") as mock_agentql:
        wrapped_page = Mock()
        mock_agentql.wrap.return_value = wrapped_page
        return mock_agentql, wrapped_page


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


@pytest.mark.skip(reason="This test doesn't mock playwright module correctly.")
def test_scrape_website_success(mock_playwright, mock_agentql, agentql_tools):
    """Test successful website scraping."""
    # Unpack the mock_agentql fixture
    mock_agentql_module, wrapped_page = mock_agentql

    # Set up the mock response for query_data
    wrapped_page.query_data.return_value = {
        "text_content": ["Example Domain", "This domain is for use in illustrative examples"]
    }

    result = agentql_tools.scrape_website("https://example.com")

    # Verify the page navigation occurred
    wrapped_page.goto.assert_called_once_with("https://example.com")

    # Verify query_data was called with correct query
    wrapped_page.query_data.assert_called_once_with("""
        {
            text_content[]
        }
        """)

    # Check the result contains expected content
    assert "Example Domain" in result
    assert "This domain is for use in illustrative examples" in result
    assert isinstance(result, str)
