"""Unit tests for TzafonTools class."""

import json
import os
from unittest.mock import MagicMock, Mock, patch

import pytest
from playwright.sync_api import Browser, BrowserContext, Page

from agno.tools.tzafon import TzafonTools

TEST_API_KEY = os.environ.get("TZAFON_API_KEY", "test_api_key")
TEST_BASE_URL = "https://api.tzafon.ai"


@pytest.fixture
def mock_tzafon():
    """Create a mock Tzafon client."""
    with patch("agno.tools.tzafon.Computer") as mock_computer_cls:
        mock_client = Mock()
        mock_computer_cls.return_value = mock_client
        return mock_client


@pytest.fixture
def mock_playwright():
    """Create a mock Playwright instance."""
    with patch("agno.tools.tzafon.sync_playwright") as mock_sync_playwright:
        # Create a mock playwright instance without using spec
        mock_playwright_instance = Mock()

        # Setup the return value for sync_playwright()
        mock_sync_playwright.return_value = mock_playwright_instance
        # Setup start() to return the instance itself
        mock_playwright_instance.start.return_value = mock_playwright_instance

        # Setup chromium browser
        mock_browser = Mock(spec=Browser)
        mock_playwright_instance.chromium = Mock()
        mock_playwright_instance.chromium.connect_over_cdp = Mock(return_value=mock_browser)

        # Setup browser context
        mock_context = Mock(spec=BrowserContext)
        mock_browser.contexts = [mock_context]

        # Setup page
        mock_page = Mock(spec=Page)
        mock_context.pages = [mock_page]
        # Also setup new_page in case pages[0] is accessed but empty/falsy logic in real code
        # but in the code it is `context.pages[0] or context.new_page()`
        # If contexts[0] returns mock_context, and mock_context.pages is a list with mock_page
        mock_context.new_page.return_value = mock_page

        return {
            "playwright": mock_playwright_instance,
            "browser": mock_browser,
            "context": mock_context,
            "page": mock_page,
        }


@pytest.fixture
def tzafon_tools(mock_tzafon):
    """Create a TzafonTools instance with mocked dependencies."""
    with patch.dict("os.environ", {"TZAFON_API_KEY": TEST_API_KEY}):
        tools = TzafonTools()
        # Ensure the client is our mock (though init already does this due to patch)
        tools._client = mock_tzafon
        return tools


def test_init_with_env_vars():
    """Test initialization with environment variables."""
    with patch("agno.tools.tzafon.Computer"):
        with patch.dict("os.environ", {"TZAFON_API_KEY": TEST_API_KEY}, clear=True):
            tools = TzafonTools()
            assert tools.api_key == TEST_API_KEY


def test_init_with_params():
    """Test initialization with parameters."""
    with patch("agno.tools.tzafon.Computer"), patch.dict("os.environ", {}, clear=True):
        tools = TzafonTools(api_key="param_api_key")
        assert tools.api_key == "param_api_key"


def test_init_with_missing_api_key():
    """Test initialization with missing API key raises ValueError."""
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="TZAFON_API_KEY is not set"):
            TzafonTools()


def test_initialize_browser(tzafon_tools, mock_playwright, mock_tzafon):
    """Test _initialize_browser method."""
    # Setup mock computer
    mock_computer = Mock()
    mock_computer.id = "test_computer_id"
    mock_tzafon.create.return_value = mock_computer

    # Call the method
    tzafon_tools._initialize_browser()

    # Verify computer creation
    mock_tzafon.create.assert_called_once_with(kind="browser")
    assert tzafon_tools._computer == mock_computer

    # Verify playwright connection
    expected_cdp_url = f"{TEST_BASE_URL}/computers/test_computer_id/cdp?token={TEST_API_KEY}"
    mock_playwright["playwright"].chromium.connect_over_cdp.assert_called_once_with(expected_cdp_url)

    # Verify internal state
    assert tzafon_tools._playwright == mock_playwright["playwright"]
    assert tzafon_tools._browser == mock_playwright["browser"]
    assert tzafon_tools._page == mock_playwright["page"]


def test_navigate_to(tzafon_tools, mock_playwright, mock_tzafon):
    """Test navigate_to method."""
    # Setup mock page and computer
    mock_page = mock_playwright["page"]
    mock_page.title.return_value = "Test Page Title"

    mock_computer = Mock()
    mock_computer.id = "test_computer_id"
    mock_tzafon.create.return_value = mock_computer

    # Pre-set components to avoid full initialization if we want,
    # but the method calls _initialize_browser(), so we should let it run or mock it.
    # Since we tested _initialize_browser separately, we can mock it here to isolate navigate_to logic
    # OR we can let it run. Let's let it run but ensure mocks are ready.

    # We need to make sure _initialize_browser uses our mock_playwright.
    # The fixture mock_playwright patches `sync_playwright` so it should work automatically.

    # Call the method
    result = tzafon_tools.navigate_to("https://example.com")
    result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "success"
    assert result_data["title"] == "Test Page Title"
    assert result_data["url"] == "https://example.com"
    mock_page.goto.assert_called_once_with("https://example.com", wait_until="networkidle")


def test_navigate_to_failed(tzafon_tools, mock_playwright):
    """Test navigate_to method failure handling."""
    with patch.object(tzafon_tools, "_initialize_browser", side_effect=Exception("Connection failed")):
        with pytest.raises(Exception, match="Connection failed"):
            tzafon_tools.navigate_to("https://example.com")

        # Verify cleanup is called (though _initialize_browser failed, so maybe not much to cleanup)
        # But if it failed later...

    # Let's test failure during goto
    tzafon_tools._page = mock_playwright["page"]
    tzafon_tools._page.goto.side_effect = Exception("Navigation failed")

    # We need to mock _initialize_browser to NOT overwrite our manual setup
    # or ensure it re-uses/sets up correctly.
    # Simpler to just patch _initialize_browser to do nothing for this specific test case
    # assuming we already "have" a browser
    with patch.object(tzafon_tools, "_initialize_browser"):
        with patch.object(tzafon_tools, "_cleanup") as mock_cleanup:
            with pytest.raises(Exception, match="Navigation failed"):
                tzafon_tools.navigate_to("https://example.com")

            mock_cleanup.assert_called_once()


def test_screenshot(tzafon_tools, mock_playwright):
    """Test screenshot method."""
    # Set the page on the tools instance directly
    tzafon_tools._page = mock_playwright["page"]

    # Call the method
    result = tzafon_tools.screenshot("/path/to/screenshot.png", True)
    result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "success"
    assert result_data["path"] == "/path/to/screenshot.png"
    mock_playwright["page"].screenshot.assert_called_once_with(path="/path/to/screenshot.png", full_page=True)


def test_screenshot_failed(tzafon_tools):
    """Test screenshot failure."""
    tzafon_tools._page = Mock()
    tzafon_tools._page.screenshot.side_effect = Exception("Screenshot failed")

    with patch.object(tzafon_tools, "_cleanup") as mock_cleanup:
        with pytest.raises(Exception, match="Screenshot failed"):
            tzafon_tools.screenshot("path.png")

        mock_cleanup.assert_called_once()


def test_get_page_content(tzafon_tools, mock_playwright):
    """Test get_page_content method."""
    # Setup mock page
    mock_page = mock_playwright["page"]
    mock_page.content.return_value = "<html><body>Test content</body></html>"

    # Set the page on the tools instance
    tzafon_tools._page = mock_page

    # Call the method
    result = tzafon_tools.get_page_content()

    # Verify results
    assert result == "<html><body>Test content</body></html>"
    mock_page.content.assert_called_once()


def test_terminate_session(tzafon_tools, mock_tzafon):
    """Test terminate_session method."""
    # Setup mock computer
    mock_computer = Mock()
    tzafon_tools._computer = mock_computer

    # Mock cleanup to verify it's called
    with patch.object(tzafon_tools, "_cleanup") as mock_cleanup:
        # Call the method
        result = tzafon_tools.terminate_session()
        result_data = json.loads(result)

        # Verify results
        assert result_data["status"] == "success"
        assert "Browser resources cleaned up" in result_data["message"]

        # Verify cleanup and computer termination
        mock_cleanup.assert_called_once()
        mock_computer.terminate.assert_called_once()


def test_terminate_session_error(tzafon_tools):
    """Test terminate_session method when an exception occurs."""
    # Setup mock to raise exception during cleanup
    with patch.object(tzafon_tools, "_cleanup", side_effect=Exception("Cleanup failed")):
        # Call the method
        result = tzafon_tools.terminate_session()
        result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "error"
    assert "Cleanup completed with error" in result_data["message"]
    assert "Cleanup failed" in result_data["message"]


def test_cleanup(tzafon_tools, mock_playwright):
    """Test _cleanup method."""
    # Set up some resources
    tzafon_tools._browser = mock_playwright["browser"]
    tzafon_tools._playwright = mock_playwright["playwright"]
    tzafon_tools._page = mock_playwright["page"]

    # Call cleanup
    tzafon_tools._cleanup()

    # Verify resources are closed/released
    mock_playwright["browser"].close.assert_called_once()
    mock_playwright["playwright"].stop.assert_called_once()

    assert tzafon_tools._browser is None
    assert tzafon_tools._playwright is None
    assert tzafon_tools._page is None
