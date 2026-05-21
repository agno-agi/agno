"""Unit tests for BrowserbaseTools class."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from playwright.async_api import Browser as AsyncBrowser
from playwright.async_api import BrowserContext as AsyncBrowserContext
from playwright.async_api import Page as AsyncPage
from playwright.sync_api import Browser, BrowserContext, Page

from agno.tools.browserbase import BrowserbaseTools

TEST_API_KEY = os.environ.get("BROWSERBASE_API_KEY", "test_api_key")
TEST_PROJECT_ID = os.environ.get("BROWSERBASE_PROJECT_ID", "test_project_id")
TEST_BASE_URL = os.environ.get("BROWSERBASE_BASE_URL")


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
    with patch("playwright.sync_api.sync_playwright") as mock_sync_playwright:
        # Create a mock playwright instance without using spec
        mock_playwright_instance = Mock()

        # Setup the return value for sync_playwright()
        mock_sync_playwright.return_value = mock_playwright_instance

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

        return {
            "playwright": mock_playwright_instance,
            "browser": mock_browser,
            "context": mock_context,
            "page": mock_page,
        }


@pytest.fixture
def browserbase_tools(mock_browserbase):
    """Create a BrowserbaseTools instance with mocked dependencies."""
    with patch.dict("os.environ", {"BROWSERBASE_API_KEY": TEST_API_KEY, "BROWSERBASE_PROJECT_ID": TEST_PROJECT_ID}):
        tools = BrowserbaseTools()
        # Directly set the app to our mock to avoid initialization issues
        tools.app = mock_browserbase
        return tools


def test_init_with_env_vars():
    """Test initialization with environment variables."""
    with patch("agno.tools.browserbase.Browserbase"):
        with patch.dict(
            "os.environ", {"BROWSERBASE_API_KEY": TEST_API_KEY, "BROWSERBASE_PROJECT_ID": TEST_PROJECT_ID}, clear=True
        ):  # Clear=True to ensure no other env vars leak in
            tools = BrowserbaseTools()
            assert tools.api_key == TEST_API_KEY
            assert tools.project_id == TEST_PROJECT_ID
            assert tools.base_url is None


def test_init_with_params():
    """Test initialization with parameters."""
    with patch("agno.tools.browserbase.Browserbase"), patch.dict("os.environ", {}, clear=True):
        tools = BrowserbaseTools(api_key="param_api_key", project_id="param_project_id", base_url=TEST_BASE_URL)
        assert tools.api_key == "param_api_key"
        assert tools.project_id == "param_project_id"
        assert tools.base_url == TEST_BASE_URL


def test_init_with_missing_api_key():
    """Test initialization with missing API key raises ValueError."""
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="BROWSERBASE_API_KEY is required"):
            BrowserbaseTools()


def test_init_with_missing_project_id():
    """Test initialization with missing project ID raises ValueError."""
    with (
        patch.dict("os.environ", {"BROWSERBASE_API_KEY": TEST_API_KEY}, clear=True),
        patch("agno.tools.browserbase.Browserbase"),
    ):
        with pytest.raises(ValueError, match="BROWSERBASE_PROJECT_ID is required"):
            BrowserbaseTools()


def test_ensure_session(browserbase_tools, mock_browserbase):
    """Test _ensure_session method creates a session if none exists."""
    # Setup mock session
    mock_session = Mock()
    mock_session.id = "test_session_id"
    mock_session.connect_url = "ws://test.connect.url"
    mock_browserbase.sessions.create.return_value = mock_session

    # Call the method
    browserbase_tools._ensure_session()

    # Verify results
    assert browserbase_tools._session == mock_session
    assert browserbase_tools._connect_url == "ws://test.connect.url"
    mock_browserbase.sessions.create.assert_called_once_with(project_id=TEST_PROJECT_ID)

    # Reset the mock and call again - should not create a new session
    mock_browserbase.sessions.create.reset_mock()
    browserbase_tools._ensure_session()
    mock_browserbase.sessions.create.assert_not_called()


def test_initialize_browser(browserbase_tools):
    """Test _initialize_browser method with connect_url."""
    # Mock the entire _initialize_browser method to avoid actual browser initialization
    with patch.object(browserbase_tools, "_ensure_session"):
        # Set up a mock for the playwright instance
        mock_playwright = Mock()
        mock_browser = Mock()
        mock_context = Mock()
        mock_page = Mock()

        # Set up the mock browser with a list-like contexts attribute
        mock_browser.contexts = MagicMock()
        mock_browser.contexts.__getitem__.return_value = mock_context

        # Set up the mock context with a list-like pages attribute
        mock_context.pages = MagicMock()
        mock_context.pages.__getitem__.return_value = mock_page

        # Set up the chromium connect_over_cdp method
        mock_playwright.chromium = Mock()
        mock_playwright.chromium.connect_over_cdp = Mock(return_value=mock_browser)

        # Set up the sync_playwright().start() chain
        with patch("playwright.sync_api.sync_playwright") as mock_sync_playwright:
            mock_sync_playwright.return_value = Mock()
            mock_sync_playwright.return_value.start.return_value = mock_playwright

            # Call the method with a connect_url
            browserbase_tools._initialize_browser("ws://test.connect.url")

            # Verify the connect_url was set
            assert browserbase_tools._connect_url == "ws://test.connect.url"
            mock_playwright.chromium.connect_over_cdp.assert_called_once_with("ws://test.connect.url")


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
    result = browserbase_tools.navigate_to("https://example.com")
    result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "complete"
    assert result_data["title"] == "Test Page Title"
    assert result_data["url"] == "https://example.com"
    mock_page.goto.assert_called_once_with("https://example.com", wait_until="networkidle")


def test_screenshot(browserbase_tools, mock_playwright):
    """Test screenshot method."""
    # Set the page on the tools instance to avoid connect_over_cdp
    browserbase_tools._page = mock_playwright["page"]
    browserbase_tools._browser = mock_playwright["browser"]
    browserbase_tools._playwright = mock_playwright["playwright"]

    # Call the method
    result = browserbase_tools.screenshot("/path/to/screenshot.png", True)
    result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "success"
    assert result_data["path"] == "/path/to/screenshot.png"
    mock_playwright["page"].screenshot.assert_called_once_with(path="/path/to/screenshot.png", full_page=True)


def test_get_page_content(browserbase_tools, mock_playwright):
    """Test get_page_content method with text_only=True (default)."""
    # Setup mock page
    mock_page = mock_playwright["page"]
    mock_page.content.return_value = "<html><body>Test content</body></html>"

    # Set the page on the tools instance to avoid connect_over_cdp
    browserbase_tools._page = mock_page
    browserbase_tools._browser = mock_playwright["browser"]
    browserbase_tools._playwright = mock_playwright["playwright"]

    # Call the method
    result = browserbase_tools.get_page_content()

    # Verify results - text_only=True by default, so HTML tags are stripped
    assert result == "Test content"
    mock_page.content.assert_called_once()


def test_get_page_content_raw_html(mock_browserbase, mock_playwright):
    """Test get_page_content method with parse_html=False returns raw HTML."""
    with (
        patch("agno.tools.browserbase.Browserbase"),
        patch.dict("os.environ", {"BROWSERBASE_API_KEY": TEST_API_KEY, "BROWSERBASE_PROJECT_ID": TEST_PROJECT_ID}),
    ):
        tools = BrowserbaseTools(parse_html=False)
        tools.app = mock_browserbase

        # Setup mock page
        mock_page = mock_playwright["page"]
        mock_page.content.return_value = "<html><body>Test content</body></html>"

        # Set the page on the tools instance to avoid connect_over_cdp
        tools._page = mock_page
        tools._browser = mock_playwright["browser"]
        tools._playwright = mock_playwright["playwright"]

        # Call the method
        result = tools.get_page_content()

        # Verify results - parse_html=False, so raw HTML is returned
        assert result == "<html><body>Test content</body></html>"
        mock_page.content.assert_called_once()


def test_close_session_with_session_id(browserbase_tools, mock_browserbase):
    """Test close_session method."""
    # Call the method
    result = browserbase_tools.close_session()
    result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "closed"
    # We no longer expect sessions.delete to be called
    # Instead, verify that cleanup was performed
    assert "Browser resources cleaned up" in result_data["message"]


def test_close_session_without_session_id(browserbase_tools, mock_browserbase):
    """Test close_session method with current session."""
    # Setup mock session
    mock_session = Mock()
    mock_session.id = "current_session_id"
    browserbase_tools._session = mock_session

    # Call the method
    result = browserbase_tools.close_session()
    result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "closed"
    assert browserbase_tools._session is None


def test_close_session_with_exception(browserbase_tools, mock_browserbase):
    """Test close_session method when an exception occurs."""
    # Setup mock to raise exception during cleanup
    with patch.object(browserbase_tools, "_cleanup", side_effect=Exception("Cleanup failed")):
        # Call the method
        result = browserbase_tools.close_session()
        result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "warning"
    assert "Cleanup completed with warning" in result_data["message"]
    assert "Cleanup failed" in result_data["message"]


# ==================== Async Tests ====================


@pytest.fixture
def mock_async_playwright():
    """Create a mock async Playwright instance."""
    with patch("playwright.async_api.async_playwright") as mock_async_playwright_fn:
        # Create a mock playwright instance
        mock_playwright_instance = Mock()

        # Setup the return value for async_playwright()
        mock_async_playwright_fn.return_value = mock_playwright_instance

        # Setup chromium browser
        mock_browser = Mock(spec=AsyncBrowser)
        mock_playwright_instance.chromium = Mock()
        mock_playwright_instance.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

        # Setup browser context
        mock_context = Mock(spec=AsyncBrowserContext)
        mock_browser.contexts = [mock_context]

        # Setup page
        mock_page = Mock(spec=AsyncPage)
        mock_context.pages = [mock_page]
        mock_context.new_page = AsyncMock(return_value=mock_page)

        # Make start async
        mock_playwright_instance.start = AsyncMock(return_value=mock_playwright_instance)

        # Make stop async
        mock_playwright_instance.stop = AsyncMock()

        # Make browser close async
        mock_browser.close = AsyncMock()

        return {
            "playwright": mock_playwright_instance,
            "browser": mock_browser,
            "context": mock_context,
            "page": mock_page,
        }


@pytest.fixture
def async_browserbase_tools(mock_browserbase):
    """Create a BrowserbaseTools instance for async testing.

    Note: With the new implementation, the same BrowserbaseTools instance
    can be used for both sync and async operations. Async tools are automatically
    selected when using arun()/aprint_response().
    """
    with patch.dict("os.environ", {"BROWSERBASE_API_KEY": TEST_API_KEY, "BROWSERBASE_PROJECT_ID": TEST_PROJECT_ID}):
        tools = BrowserbaseTools()
        # Directly set the app to our mock to avoid initialization issues
        tools.app = mock_browserbase
        return tools


def test_async_tools_registered():
    """Test that both sync and async tools are registered automatically."""
    with patch("agno.tools.browserbase.Browserbase"):
        with patch.dict(
            "os.environ", {"BROWSERBASE_API_KEY": TEST_API_KEY, "BROWSERBASE_PROJECT_ID": TEST_PROJECT_ID}, clear=True
        ):
            tools = BrowserbaseTools()
            # Verify sync tools are registered in functions dict
            assert "navigate_to" in tools.functions
            assert "screenshot" in tools.functions
            assert "get_page_content" in tools.functions
            assert "close_session" in tools.functions
            # Verify async tools are registered in async_functions dict
            assert "navigate_to" in tools.async_functions
            assert "screenshot" in tools.async_functions
            assert "get_page_content" in tools.async_functions
            assert "close_session" in tools.async_functions


@pytest.mark.asyncio
async def test_ainitialize_browser(async_browserbase_tools):
    """Test _ainitialize_browser method with connect_url."""
    with patch.object(async_browserbase_tools, "_ensure_session"):
        # Set up a mock for the playwright instance
        mock_playwright = Mock()
        mock_browser = Mock()
        mock_context = Mock()
        mock_page = Mock()

        # Set up the mock browser with a list-like contexts attribute
        mock_browser.contexts = [mock_context]

        # Set up the mock context with pages
        mock_context.pages = [mock_page]

        # Set up the chromium connect_over_cdp method
        mock_playwright.chromium = Mock()
        mock_playwright.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

        # Make start async
        mock_playwright.start = AsyncMock(return_value=mock_playwright)

        # Set up the async_playwright() chain
        with patch("playwright.async_api.async_playwright") as mock_async_playwright:
            mock_async_playwright.return_value = mock_playwright

            # Call the method with a connect_url
            await async_browserbase_tools._ainitialize_browser("ws://test.connect.url")

            # Verify the connect_url was set
            assert async_browserbase_tools._connect_url == "ws://test.connect.url"
            mock_playwright.chromium.connect_over_cdp.assert_called_once_with("ws://test.connect.url")


@pytest.mark.asyncio
async def test_anavigate_to(async_browserbase_tools, mock_async_playwright):
    """Test anavigate_to method."""
    # Setup mock page
    mock_page = mock_async_playwright["page"]
    mock_page.goto = AsyncMock()
    mock_page.title = AsyncMock(return_value="Test Page Title")

    # Set the page on the tools instance to avoid connect_over_cdp
    async_browserbase_tools._async_page = mock_page
    async_browserbase_tools._async_browser = mock_async_playwright["browser"]
    async_browserbase_tools._async_playwright = mock_async_playwright["playwright"]

    # Call the method
    result = await async_browserbase_tools.anavigate_to("https://example.com")
    result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "complete"
    assert result_data["title"] == "Test Page Title"
    assert result_data["url"] == "https://example.com"
    mock_page.goto.assert_called_once_with("https://example.com", wait_until="networkidle")


@pytest.mark.asyncio
async def test_ascreenshot(async_browserbase_tools, mock_async_playwright):
    """Test ascreenshot method."""
    # Setup mock page
    mock_page = mock_async_playwright["page"]
    mock_page.screenshot = AsyncMock()

    # Set the page on the tools instance to avoid connect_over_cdp
    async_browserbase_tools._async_page = mock_page
    async_browserbase_tools._async_browser = mock_async_playwright["browser"]
    async_browserbase_tools._async_playwright = mock_async_playwright["playwright"]

    # Call the method
    result = await async_browserbase_tools.ascreenshot("/path/to/screenshot.png", True)
    result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "success"
    assert result_data["path"] == "/path/to/screenshot.png"
    mock_page.screenshot.assert_called_once_with(path="/path/to/screenshot.png", full_page=True)


@pytest.mark.asyncio
async def test_aget_page_content(async_browserbase_tools, mock_async_playwright):
    """Test aget_page_content method with text_only=True (default)."""
    # Setup mock page
    mock_page = mock_async_playwright["page"]
    mock_page.content = AsyncMock(return_value="<html><body>Test content</body></html>")

    # Set the page on the tools instance to avoid connect_over_cdp
    async_browserbase_tools._async_page = mock_page
    async_browserbase_tools._async_browser = mock_async_playwright["browser"]
    async_browserbase_tools._async_playwright = mock_async_playwright["playwright"]

    # Call the method
    result = await async_browserbase_tools.aget_page_content()

    # Verify results - text_only=True by default, so HTML tags are stripped
    assert result == "Test content"
    mock_page.content.assert_called_once()


@pytest.mark.asyncio
async def test_aget_page_content_raw_html(mock_browserbase, mock_async_playwright):
    """Test aget_page_content method with parse_html=False returns raw HTML."""
    with (
        patch("agno.tools.browserbase.Browserbase"),
        patch.dict("os.environ", {"BROWSERBASE_API_KEY": TEST_API_KEY, "BROWSERBASE_PROJECT_ID": TEST_PROJECT_ID}),
    ):
        tools = BrowserbaseTools(parse_html=False)
        tools.app = mock_browserbase

        # Setup mock page
        mock_page = mock_async_playwright["page"]
        mock_page.content = AsyncMock(return_value="<html><body>Test content</body></html>")

        # Set the page on the tools instance to avoid connect_over_cdp
        tools._async_page = mock_page
        tools._async_browser = mock_async_playwright["browser"]
        tools._async_playwright = mock_async_playwright["playwright"]

        # Call the method
        result = await tools.aget_page_content()

        # Verify results - parse_html=False, so raw HTML is returned
        assert result == "<html><body>Test content</body></html>"
        mock_page.content.assert_called_once()


@pytest.mark.asyncio
async def test_aclose_session_basic(async_browserbase_tools, mock_browserbase):
    """Test aclose_session method."""
    # Call the method
    result = await async_browserbase_tools.aclose_session()
    result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "closed"
    assert "Browser resources cleaned up" in result_data["message"]


@pytest.mark.asyncio
async def test_aclose_session_with_session(async_browserbase_tools, mock_browserbase):
    """Test aclose_session method with current session."""
    # Setup mock session
    mock_session = Mock()
    mock_session.id = "current_session_id"
    async_browserbase_tools._session = mock_session

    # Call the method
    result = await async_browserbase_tools.aclose_session()
    result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "closed"
    assert async_browserbase_tools._session is None


@pytest.mark.asyncio
async def test_aclose_session_with_exception(async_browserbase_tools, mock_browserbase):
    """Test aclose_session method when an exception occurs."""
    # Setup mock to raise exception during cleanup
    with patch.object(async_browserbase_tools, "_acleanup", side_effect=Exception("Async cleanup failed")):
        # Call the method
        result = await async_browserbase_tools.aclose_session()
        result_data = json.loads(result)

    # Verify results
    assert result_data["status"] == "warning"
    assert "Cleanup completed with warning" in result_data["message"]
    assert "Async cleanup failed" in result_data["message"]


@pytest.mark.asyncio
async def test_anavigate_to_with_error_cleanup(async_browserbase_tools, mock_async_playwright):
    """Test anavigate_to properly cleans up on error."""
    # Setup mock page that raises an error
    mock_page = mock_async_playwright["page"]
    mock_page.goto = AsyncMock(side_effect=Exception("Navigation failed"))

    # Set the page on the tools instance
    async_browserbase_tools._async_page = mock_page
    async_browserbase_tools._async_browser = mock_async_playwright["browser"]
    async_browserbase_tools._async_playwright = mock_async_playwright["playwright"]

    # Mock the cleanup method to verify it's called
    cleanup_mock = AsyncMock()
    async_browserbase_tools._acleanup = cleanup_mock

    # Call the method and expect an exception
    with pytest.raises(Exception, match="Navigation failed"):
        await async_browserbase_tools.anavigate_to("https://example.com")

    # Verify cleanup was called
    cleanup_mock.assert_called_once()


@pytest.mark.asyncio
async def test_ascreenshot_with_error_cleanup(async_browserbase_tools, mock_async_playwright):
    """Test ascreenshot properly cleans up on error."""
    # Setup mock page that raises an error
    mock_page = mock_async_playwright["page"]
    mock_page.screenshot = AsyncMock(side_effect=Exception("Screenshot failed"))

    # Set the page on the tools instance
    async_browserbase_tools._async_page = mock_page
    async_browserbase_tools._async_browser = mock_async_playwright["browser"]
    async_browserbase_tools._async_playwright = mock_async_playwright["playwright"]

    # Mock the cleanup method to verify it's called
    cleanup_mock = AsyncMock()
    async_browserbase_tools._acleanup = cleanup_mock

    # Call the method and expect an exception
    with pytest.raises(Exception, match="Screenshot failed"):
        await async_browserbase_tools.ascreenshot("/path/to/screenshot.png")

    # Verify cleanup was called
    cleanup_mock.assert_called_once()


@pytest.mark.asyncio
async def test_aget_page_content_with_error_cleanup(async_browserbase_tools, mock_async_playwright):
    """Test aget_page_content properly cleans up on error."""
    # Setup mock page that raises an error
    mock_page = mock_async_playwright["page"]
    mock_page.content = AsyncMock(side_effect=Exception("Content retrieval failed"))

    # Set the page on the tools instance
    async_browserbase_tools._async_page = mock_page
    async_browserbase_tools._async_browser = mock_async_playwright["browser"]
    async_browserbase_tools._async_playwright = mock_async_playwright["playwright"]

    # Mock the cleanup method to verify it's called
    cleanup_mock = AsyncMock()
    async_browserbase_tools._acleanup = cleanup_mock

    # Call the method and expect an exception
    with pytest.raises(Exception, match="Content retrieval failed"):
        await async_browserbase_tools.aget_page_content()

    # Verify cleanup was called
    cleanup_mock.assert_called_once()


@pytest.mark.asyncio
async def test_acleanup(async_browserbase_tools):
    """Test _acleanup method properly closes resources."""
    # Setup mock browser and playwright
    mock_browser = Mock()
    mock_browser.close = AsyncMock()
    mock_playwright = Mock()
    mock_playwright.stop = AsyncMock()

    async_browserbase_tools._async_browser = mock_browser
    async_browserbase_tools._async_playwright = mock_playwright
    async_browserbase_tools._async_page = Mock()

    # Call cleanup
    await async_browserbase_tools._acleanup()

    # Verify resources were cleaned up
    mock_browser.close.assert_called_once()
    mock_playwright.stop.assert_called_once()
    assert async_browserbase_tools._async_browser is None
    assert async_browserbase_tools._async_playwright is None
    assert async_browserbase_tools._async_page is None


@pytest.mark.asyncio
async def test_anavigate_to_with_connect_url(async_browserbase_tools):
    """Test anavigate_to with explicit connect_url parameter."""
    # Setup mocks
    mock_playwright = Mock()
    mock_browser = Mock()
    mock_context = Mock()
    mock_page = Mock()

    mock_browser.contexts = [mock_context]
    mock_context.pages = [mock_page]

    mock_playwright.chromium = Mock()
    mock_playwright.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
    mock_playwright.start = AsyncMock(return_value=mock_playwright)

    mock_page.goto = AsyncMock()
    mock_page.title = AsyncMock(return_value="Test Title")

    with patch("playwright.async_api.async_playwright") as mock_async_playwright:
        mock_async_playwright.return_value = mock_playwright

        # Call with explicit connect_url
        result = await async_browserbase_tools.anavigate_to(
            "https://example.com", connect_url="ws://custom.connect.url"
        )
        result_data = json.loads(result)

        # Verify the custom connect_url was used
        assert async_browserbase_tools._connect_url == "ws://custom.connect.url"
        mock_playwright.chromium.connect_over_cdp.assert_called_once_with("ws://custom.connect.url")
        assert result_data["status"] == "complete"


@pytest.mark.asyncio
async def test_ascreenshot_with_connect_url(async_browserbase_tools):
    """Test ascreenshot with explicit connect_url parameter."""
    # Setup mocks
    mock_playwright = Mock()
    mock_browser = Mock()
    mock_context = Mock()
    mock_page = Mock()

    mock_browser.contexts = [mock_context]
    mock_context.pages = [mock_page]

    mock_playwright.chromium = Mock()
    mock_playwright.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
    mock_playwright.start = AsyncMock(return_value=mock_playwright)

    mock_page.screenshot = AsyncMock()

    with patch("playwright.async_api.async_playwright") as mock_async_playwright:
        mock_async_playwright.return_value = mock_playwright

        # Call with explicit connect_url
        result = await async_browserbase_tools.ascreenshot(
            "/path/to/screenshot.png", full_page=False, connect_url="ws://custom.connect.url"
        )
        result_data = json.loads(result)

        # Verify the custom connect_url was used
        assert async_browserbase_tools._connect_url == "ws://custom.connect.url"
        mock_page.screenshot.assert_called_once_with(path="/path/to/screenshot.png", full_page=False)
        assert result_data["status"] == "success"


@pytest.mark.asyncio
async def test_aget_page_content_with_connect_url(async_browserbase_tools):
    """Test aget_page_content with explicit connect_url parameter."""
    # Setup mocks
    mock_playwright = Mock()
    mock_browser = Mock()
    mock_context = Mock()
    mock_page = Mock()

    mock_browser.contexts = [mock_context]
    mock_context.pages = [mock_page]

    mock_playwright.chromium = Mock()
    mock_playwright.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
    mock_playwright.start = AsyncMock(return_value=mock_playwright)

    mock_page.content = AsyncMock(return_value="<html>Custom content</html>")

    with patch("playwright.async_api.async_playwright") as mock_async_playwright:
        mock_async_playwright.return_value = mock_playwright

        # Call with explicit connect_url
        result = await async_browserbase_tools.aget_page_content(connect_url="ws://custom.connect.url")

        # Verify the custom connect_url was used
        assert async_browserbase_tools._connect_url == "ws://custom.connect.url"
        # text_only=True by default, so HTML tags are stripped
        assert result == "Custom content"
