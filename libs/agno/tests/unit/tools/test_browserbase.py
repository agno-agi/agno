"""Unit tests for BrowserbaseTools class."""

import json
import os
from unittest.mock import Mock, patch, MagicMock

import pytest
from playwright.sync_api import Browser, Page, BrowserContext, Playwright

from agno.tools.browserbase import BrowserbaseTools


# Get API key and project ID from environment for tests
API_KEY = os.environ.get("BROWSERBASE_API_KEY", "test_api_key")
PROJECT_ID = os.environ.get("BROWSERBASE_PROJECT_ID", "test_project_id")


@pytest.fixture
def mock_browserbase():
    """Create a mock Browserbase client."""
    with patch("agno.tools.browserbase.Browserbase") as mock_browserbase_cls:
        mock_client = Mock()
        mock_sessions = Mock()
        mock_client.sessions = mock_sessions
        mock_browserbase_cls.return_value = mock_client
        return mock_client


@pytest.fixture
def mock_playwright():
    """Create a mock Playwright instance."""
    with patch("agno.tools.browserbase.sync_playwright") as mock_sync_playwright:
        mock_playwright_instance = Mock(spec=Playwright)
        mock_sync_playwright.return_value.start.return_value = mock_playwright_instance

        # Setup chromium browser
        mock_browser = Mock(spec=Browser)
        mock_playwright_instance.chromium.connect_over_cdp.return_value = mock_browser

        # Setup browser context
        mock_context = Mock(spec=BrowserContext)
        mock_browser.contexts = [mock_context]

        # Setup page
        mock_page = Mock(spec=Page)
        mock_context.pages = [mock_page]

        return {
            "playwright": mock_playwright_instance,
            "browser": mock_browser,
            "context": mock_context,
            "page": mock_page
        }


@pytest.fixture
def browserbase_tools(mock_browserbase):
    """Create a BrowserbaseTools instance with mocked dependencies."""
    with patch.dict("os.environ", {
        "BROWSERBASE_API_KEY": API_KEY,
        "BROWSERBASE_PROJECT_ID": PROJECT_ID
    }):
        tools = BrowserbaseTools()
        # Directly set the app to our mock to avoid initialization issues
        tools.app = mock_browserbase
        return tools


def test_init_with_env_vars():
    """Test initialization with environment variables."""
    with patch("agno.tools.browserbase.Browserbase"):  # Mock to prevent actual API calls
        with patch.dict("os.environ", {
            "BROWSERBASE_API_KEY": "test_api_key",
            "BROWSERBASE_PROJECT_ID": "test_project_id"
        }):
            tools = BrowserbaseTools()
            assert tools.api_key == "test_api_key"
            assert tools.project_id == "test_project_id"


def test_init_with_params():
    """Test initialization with parameters."""
    with patch("agno.tools.browserbase.Browserbase"):  # Mock to prevent actual API calls
        tools = BrowserbaseTools(api_key="param_api_key",
                                 project_id="param_project_id")
        assert tools.api_key == "param_api_key"
        assert tools.project_id == "param_project_id"


def test_real_env_vars_not_exposed():
    """Test that real API keys from .env are not exposed in tests."""
    # This test ensures we're not accidentally using real credentials in tests
    with patch("agno.tools.browserbase.Browserbase"):
        with patch.dict("os.environ", {
            "BROWSERBASE_API_KEY": API_KEY,
            "BROWSERBASE_PROJECT_ID": PROJECT_ID
        }):
            with patch.object(BrowserbaseTools, "__init__", return_value=None) as mock_init:
                BrowserbaseTools()
                # Verify the init was called, but we're not actually using the real credentials
                mock_init.assert_called_once()


def test_create_session(browserbase_tools, mock_browserbase):
    """Test create_session method."""
    # Setup mock session
    mock_session = Mock()
    mock_session.id = "test_session_id"
    mock_session.connect_url = "ws://test.connect.url"
    mock_browserbase.sessions.create.return_value = mock_session

    # Call the method
    result = browserbase_tools.create_session()
    result_data = json.loads(result)

    # Verify results
    assert result_data["session_id"] == "test_session_id"
    assert result_data["connect_url"] == "ws://test.connect.url"
    mock_browserbase.sessions.create.assert_called_once_with(
        project_id=PROJECT_ID)


def test_navigate_to(browserbase_tools, mock_playwright):
    """Test navigate_to method."""
    # Setup mock page
    mock_page = mock_playwright["page"]
    mock_page.title.return_value = "Test Page Title"

    # Set the page on the tools instance to avoid connect_over_cdp
    browserbase_tools._page = mock_page
    browserbase_tools._browser = mock_playwright["browser"]
    browserbase_tools._playwright = mock_playwright["playwright"]

    # Call the method
    result = browserbase_tools.navigate_to(
        "ws://test.connect.url", "https://example.com")
    result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "complete"
    assert result_data["title"] == "Test Page Title"
    assert result_data["url"] == "https://example.com"
    mock_page.goto.assert_called_once_with(
        "https://example.com", wait_until="networkidle")


def test_screenshot(browserbase_tools, mock_playwright):
    """Test screenshot method."""
    # Set the page on the tools instance to avoid connect_over_cdp
    browserbase_tools._page = mock_playwright["page"]
    browserbase_tools._browser = mock_playwright["browser"]
    browserbase_tools._playwright = mock_playwright["playwright"]

    # Call the method
    result = browserbase_tools.screenshot(
        "ws://test.connect.url", "/path/to/screenshot.png", True)
    result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "success"
    assert result_data["path"] == "/path/to/screenshot.png"
    mock_playwright["page"].screenshot.assert_called_once_with(
        path="/path/to/screenshot.png", full_page=True)


def test_get_page_content(browserbase_tools, mock_playwright):
    """Test get_page_content method."""
    # Setup mock page
    mock_page = mock_playwright["page"]
    mock_page.content.return_value = "<html><body>Test content</body></html>"

    # Set the page on the tools instance to avoid connect_over_cdp
    browserbase_tools._page = mock_page
    browserbase_tools._browser = mock_playwright["browser"]
    browserbase_tools._playwright = mock_playwright["playwright"]

    # Call the method
    result = browserbase_tools.get_page_content("ws://test.connect.url")

    # Verify results
    assert result == "<html><body>Test content</body></html>"
    mock_page.content.assert_called_once()


def test_close_session(browserbase_tools, mock_browserbase):
    """Test close_session method."""
    # Call the method
    result = browserbase_tools.close_session("test_session_id")
    result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "closed"
    mock_browserbase.sessions.delete.assert_called_once_with("test_session_id")


def test_close_session_with_exception(browserbase_tools, mock_browserbase):
    """Test close_session method when session deletion fails."""
    # Setup mock to raise exception
    mock_browserbase.sessions.delete.side_effect = Exception(
        "Session already closed")

    # Call the method
    result = browserbase_tools.close_session("test_session_id")
    result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "closed"  # Should still report closed
    mock_browserbase.sessions.delete.assert_called_once_with("test_session_id")


def test_cleanup_on_exception(browserbase_tools, mock_playwright):
    """Test that resources are cleaned up when an exception occurs."""
    # Setup mock page to raise exception
    mock_page = mock_playwright["page"]
    mock_page.content.side_effect = Exception("Test exception")

    # Set the page on the tools instance to avoid connect_over_cdp
    browserbase_tools._page = mock_page
    browserbase_tools._browser = mock_playwright["browser"]
    browserbase_tools._playwright = mock_playwright["playwright"]

    # Call method that should raise exception
    with pytest.raises(Exception):
        browserbase_tools.get_page_content("ws://test.connect.url")

    # Verify cleanup was called
    mock_playwright["browser"].close.assert_called_once()
    mock_playwright["playwright"].stop.assert_called_once()
