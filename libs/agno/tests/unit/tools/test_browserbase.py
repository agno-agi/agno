"""Unit tests for BrowserbaseTools class."""

import json
from unittest.mock import Mock, patch

import pytest
from playwright.sync_api import Browser, BrowserContext, Page

from agno.tools.browserbase import BrowserbaseTools

TEST_API_KEY = "test_api_key"
TEST_PROJECT_ID = "test_project_id"
TEST_BASE_URL = "https://custom.browserbase.com"
TEST_CONNECT_URL = "ws://test.connect.url"


def create_mock_page(
    url: str = "https://example.com",
    title: str = "Test Page",
    content: str = "<html><body>Test content</body></html>",
) -> Mock:
    mock_page = Mock(spec=Page)
    mock_page.url = url
    mock_page.title.return_value = title
    mock_page.content.return_value = content
    mock_page.evaluate.return_value = "Page text content"
    return mock_page


def create_mock_session(
    session_id: str = "test_session_id",
    connect_url: str = TEST_CONNECT_URL,
) -> Mock:
    mock_session = Mock()
    mock_session.id = session_id
    mock_session.connect_url = connect_url
    return mock_session


def create_mock_browser_context(mock_page: Mock = None) -> tuple[Mock, Mock]:
    if mock_page is None:
        mock_page = create_mock_page()

    mock_context = Mock(spec=BrowserContext)
    mock_context.pages = [mock_page]
    mock_context.new_page.return_value = mock_page

    mock_browser = Mock(spec=Browser)
    mock_browser.contexts = [mock_context]

    return mock_browser, mock_context


@pytest.fixture
def mock_browserbase_client():
    with patch("agno.tools.browserbase.Browserbase") as mock_browserbase_cls:
        mock_client = Mock()
        mock_client.sessions = Mock()
        mock_browserbase_cls.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_playwright_env():
    with patch("agno.tools.browserbase.sync_playwright") as mock_sync_playwright:
        mock_page = create_mock_page()
        mock_browser, mock_context = create_mock_browser_context(mock_page)

        mock_playwright_instance = Mock()
        mock_playwright_instance.chromium = Mock()
        mock_playwright_instance.chromium.connect_over_cdp.return_value = mock_browser
        mock_sync_playwright.return_value.start.return_value = mock_playwright_instance

        yield {
            "playwright": mock_playwright_instance,
            "browser": mock_browser,
            "context": mock_context,
            "page": mock_page,
        }


@pytest.fixture
def browserbase_tools(mock_browserbase_client):
    with patch.dict("os.environ", {"BROWSERBASE_API_KEY": TEST_API_KEY, "BROWSERBASE_PROJECT_ID": TEST_PROJECT_ID}):
        tools = BrowserbaseTools()
        tools.app = mock_browserbase_client
        yield tools


@pytest.fixture
def browserbase_tools_with_page(browserbase_tools, mock_playwright_env):
    browserbase_tools._page = mock_playwright_env["page"]
    browserbase_tools._browser = mock_playwright_env["browser"]
    browserbase_tools._playwright = mock_playwright_env["playwright"]
    return browserbase_tools


def test_init_with_env_vars():
    with patch("agno.tools.browserbase.Browserbase") as mock_browserbase:
        with patch.dict(
            "os.environ",
            {"BROWSERBASE_API_KEY": TEST_API_KEY, "BROWSERBASE_PROJECT_ID": TEST_PROJECT_ID},
            clear=True,
        ):
            tools = BrowserbaseTools()

            assert tools.api_key == TEST_API_KEY
            assert tools.project_id == TEST_PROJECT_ID
            assert tools.base_url is None
            mock_browserbase.assert_called_once_with(api_key=TEST_API_KEY)


def test_init_with_params():
    with patch("agno.tools.browserbase.Browserbase") as mock_browserbase:
        with patch.dict("os.environ", {}, clear=True):
            tools = BrowserbaseTools(
                api_key="param_api_key",
                project_id="param_project_id",
                base_url=TEST_BASE_URL,
            )

            assert tools.api_key == "param_api_key"
            assert tools.project_id == "param_project_id"
            assert tools.base_url == TEST_BASE_URL
            mock_browserbase.assert_called_once_with(api_key="param_api_key", base_url=TEST_BASE_URL)


def test_init_with_missing_api_key():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="BROWSERBASE_API_KEY is required"):
            BrowserbaseTools()


def test_init_with_missing_project_id():
    with patch("agno.tools.browserbase.Browserbase"):
        with patch.dict("os.environ", {"BROWSERBASE_API_KEY": TEST_API_KEY}, clear=True):
            with pytest.raises(ValueError, match="BROWSERBASE_PROJECT_ID is required"):
                BrowserbaseTools()


def test_init_registers_all_tools():
    with patch("agno.tools.browserbase.Browserbase"):
        with patch.dict(
            "os.environ",
            {"BROWSERBASE_API_KEY": TEST_API_KEY, "BROWSERBASE_PROJECT_ID": TEST_PROJECT_ID},
        ):
            tools = BrowserbaseTools()

            expected_tools = [
                "navigate_to", "screenshot", "get_page_content", "close_session",
                "get_current_url", "go_back", "go_forward", "reload_page",
                "click_element", "fill_input", "wait_for_element", "get_page_title",
                "scroll_page", "extract_text",
            ]

            registered_tools = [func.name for func in tools.functions.values()]
            for tool_name in expected_tools:
                assert tool_name in registered_tools


def test_ensure_session_creates_new_session(browserbase_tools, mock_browserbase_client):
    mock_session = create_mock_session()
    mock_browserbase_client.sessions.create.return_value = mock_session

    browserbase_tools._ensure_session()

    assert browserbase_tools._session == mock_session
    assert browserbase_tools._connect_url == TEST_CONNECT_URL
    mock_browserbase_client.sessions.create.assert_called_once_with(project_id=TEST_PROJECT_ID)


def test_ensure_session_reuses_existing_session(browserbase_tools, mock_browserbase_client):
    existing_session = create_mock_session(session_id="existing_session")
    browserbase_tools._session = existing_session

    browserbase_tools._ensure_session()

    mock_browserbase_client.sessions.create.assert_not_called()
    assert browserbase_tools._session == existing_session


def test_initialize_browser_with_connect_url(browserbase_tools, mock_playwright_env):
    browserbase_tools._initialize_browser(TEST_CONNECT_URL)

    assert browserbase_tools._connect_url == TEST_CONNECT_URL
    mock_playwright_env["playwright"].chromium.connect_over_cdp.assert_called_once_with(TEST_CONNECT_URL)


def test_navigate_to_success(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.title.return_value = "Example Page"

    result = browserbase_tools_with_page.navigate_to("https://example.com")
    result_data = json.loads(result)

    assert result_data["status"] == "complete"
    assert result_data["title"] == "Example Page"
    assert result_data["url"] == "https://example.com"
    mock_page.goto.assert_called_once_with("https://example.com", wait_until="networkidle", timeout=600000)


def test_navigate_to_with_custom_timeout(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    browserbase_tools_with_page.navigate_to("https://example.com", timeout=30000)

    mock_page.goto.assert_called_once_with("https://example.com", wait_until="networkidle", timeout=30000)


def test_get_current_url(browserbase_tools_with_page, mock_playwright_env):
    mock_playwright_env["page"].url = "https://current.example.com"

    result = browserbase_tools_with_page.get_current_url()
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["url"] == "https://current.example.com"


def test_go_back(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.url = "https://previous.example.com"

    result = browserbase_tools_with_page.go_back()
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["action"] == "go_back"
    assert result_data["url"] == "https://previous.example.com"
    mock_page.go_back.assert_called_once_with(wait_until="networkidle")


def test_go_forward(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.url = "https://next.example.com"

    result = browserbase_tools_with_page.go_forward()
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["action"] == "go_forward"
    assert result_data["url"] == "https://next.example.com"
    mock_page.go_forward.assert_called_once_with(wait_until="networkidle")


def test_reload_page(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.url = "https://reloaded.example.com"

    result = browserbase_tools_with_page.reload_page()
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["action"] == "reload"
    assert result_data["url"] == "https://reloaded.example.com"
    mock_page.reload.assert_called_once_with(wait_until="networkidle")


def test_get_page_content(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.content.return_value = "<html><body><h1>Hello</h1></body></html>"

    result = browserbase_tools_with_page.get_page_content()

    assert result == "<html><body><h1>Hello</h1></body></html>"
    mock_page.content.assert_called_once()


def test_get_page_title(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.title.return_value = "My Page Title"

    result = browserbase_tools_with_page.get_page_title()
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["title"] == "My Page Title"


def test_extract_text_full_page(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.evaluate.return_value = "Full page text content"

    result = browserbase_tools_with_page.extract_text()
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["text"] == "Full page text content"
    assert result_data["selector"] is None


def test_extract_text_with_selector(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_element = Mock()
    mock_element.text_content.return_value = "Element text"
    mock_page.query_selector.return_value = mock_element

    result = browserbase_tools_with_page.extract_text(selector=".content")
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["text"] == "Element text"
    assert result_data["selector"] == ".content"
    mock_page.query_selector.assert_called_once_with(".content")


def test_extract_text_selector_not_found(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.query_selector.return_value = None

    result = browserbase_tools_with_page.extract_text(selector=".nonexistent")
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["text"] == ""
    assert result_data["selector"] == ".nonexistent"


def test_screenshot_full_page(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = browserbase_tools_with_page.screenshot("/tmp/screenshot.png", full_page=True)
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["path"] == "/tmp/screenshot.png"
    mock_page.screenshot.assert_called_once_with(path="/tmp/screenshot.png", full_page=True)


def test_screenshot_viewport_only(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = browserbase_tools_with_page.screenshot("/tmp/viewport.png", full_page=False)
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    mock_page.screenshot.assert_called_once_with(path="/tmp/viewport.png", full_page=False)


def test_click_element(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = browserbase_tools_with_page.click_element("button.submit")
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["action"] == "click"
    assert result_data["selector"] == "button.submit"
    mock_page.click.assert_called_once_with("button.submit", timeout=600000)


def test_fill_input(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = browserbase_tools_with_page.fill_input("input#email", "test@example.com")
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["action"] == "fill"
    assert result_data["selector"] == "input#email"
    assert result_data["text"] == "test@example.com"
    mock_page.fill.assert_called_once_with("input#email", "test@example.com", timeout=600000)


def test_wait_for_element(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = browserbase_tools_with_page.wait_for_element(".loading-complete")
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["action"] == "wait_for_element"
    assert result_data["selector"] == ".loading-complete"
    mock_page.wait_for_selector.assert_called_once_with(".loading-complete", timeout=600000)


def test_scroll_page_down(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = browserbase_tools_with_page.scroll_page(direction="down", pixels=500)
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["action"] == "scroll"
    assert result_data["direction"] == "down"
    assert result_data["pixels"] == 500
    mock_page.evaluate.assert_called_once_with("window.scrollBy(0, 500)")


def test_scroll_page_up(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = browserbase_tools_with_page.scroll_page(direction="up", pixels=300)
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["direction"] == "up"
    mock_page.evaluate.assert_called_once_with("window.scrollBy(0, -300)")


def test_scroll_page_left(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    browserbase_tools_with_page.scroll_page(direction="left", pixels=200)

    mock_page.evaluate.assert_called_once_with("window.scrollBy(-200, 0)")


def test_scroll_page_right(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    browserbase_tools_with_page.scroll_page(direction="right", pixels=200)

    mock_page.evaluate.assert_called_once_with("window.scrollBy(200, 0)")


def test_scroll_page_invalid_direction(browserbase_tools_with_page):
    with pytest.raises(ValueError, match="Invalid direction"):
        browserbase_tools_with_page.scroll_page(direction="diagonal", pixels=100)


def test_close_session_success(browserbase_tools):
    result = browserbase_tools.close_session()
    result_data = json.loads(result)

    assert result_data["status"] == "closed"
    assert "Browser resources cleaned up" in result_data["message"]
    assert browserbase_tools._session is None
    assert browserbase_tools._connect_url is None


def test_close_session_with_active_session(browserbase_tools, mock_browserbase_client):
    mock_session = create_mock_session()
    browserbase_tools._session = mock_session

    result = browserbase_tools.close_session()
    result_data = json.loads(result)

    assert result_data["status"] == "closed"
    assert browserbase_tools._session is None


def test_close_session_cleanup_exception(browserbase_tools):
    with patch.object(browserbase_tools, "_cleanup", side_effect=Exception("Cleanup failed")):
        result = browserbase_tools.close_session()
        result_data = json.loads(result)

        assert result_data["status"] == "warning"
        assert "Cleanup completed with warning" in result_data["message"]
        assert "Cleanup failed" in result_data["message"]


def test_navigate_to_error(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.goto.side_effect = Exception("Navigation failed")

    with pytest.raises(Exception, match="Navigation failed"):
        browserbase_tools_with_page.navigate_to("https://example.com")


def test_click_element_timeout(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.click.side_effect = Exception("Timeout waiting for element")

    with pytest.raises(Exception, match="Timeout"):
        browserbase_tools_with_page.click_element(".nonexistent")


def test_fill_input_error(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.fill.side_effect = Exception("Element not editable")

    with pytest.raises(Exception, match="Element not editable"):
        browserbase_tools_with_page.fill_input("div.readonly", "text")


def test_screenshot_error(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.screenshot.side_effect = Exception("Screenshot failed")

    with pytest.raises(Exception, match="Screenshot failed"):
        browserbase_tools_with_page.screenshot("/invalid/path.png")


def test_session_creation_error(browserbase_tools, mock_browserbase_client):
    mock_browserbase_client.sessions.create.side_effect = Exception("API Error")

    with pytest.raises(Exception, match="API Error"):
        browserbase_tools._ensure_session()


def test_get_page_content_empty_page(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.content.return_value = ""

    result = browserbase_tools_with_page.get_page_content()

    assert result == ""


def test_navigate_to_with_connect_url(browserbase_tools, mock_playwright_env):
    browserbase_tools._page = mock_playwright_env["page"]
    browserbase_tools._browser = mock_playwright_env["browser"]
    browserbase_tools._playwright = mock_playwright_env["playwright"]

    result = browserbase_tools.navigate_to("https://example.com", connect_url="ws://custom.connect.url")
    result_data = json.loads(result)

    assert result_data["status"] == "complete"


def test_scroll_with_default_values(browserbase_tools_with_page, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = browserbase_tools_with_page.scroll_page()
    result_data = json.loads(result)

    assert result_data["direction"] == "down"
    assert result_data["pixels"] == 500
    mock_page.evaluate.assert_called_once_with("window.scrollBy(0, 500)")


def test_cleanup_with_no_resources(browserbase_tools):
    browserbase_tools._browser = None
    browserbase_tools._playwright = None
    browserbase_tools._page = None

    browserbase_tools._cleanup()

    assert browserbase_tools._browser is None
    assert browserbase_tools._playwright is None
    assert browserbase_tools._page is None
