"""Unit tests for PlaywrightTools class."""

import json
from unittest.mock import Mock, patch

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, Playwright

from agno.tools.playwright import PlaywrightTools

DEFAULT_TIMEOUT = 60000


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
    mock_page.locator.return_value = Mock()
    return mock_page


def create_mock_browser(mock_page: Mock = None) -> tuple[Mock, Mock, Mock]:
    if mock_page is None:
        mock_page = create_mock_page()

    mock_context = Mock(spec=BrowserContext)
    mock_context.new_page.return_value = mock_page

    mock_browser = Mock(spec=Browser)
    mock_browser.new_context.return_value = mock_context

    return mock_browser, mock_context, mock_page


@pytest.fixture
def mock_playwright_env():
    with patch("agno.tools.playwright.sync_playwright") as mock_sync_playwright:
        mock_page = create_mock_page()
        mock_browser, mock_context, _ = create_mock_browser(mock_page)

        mock_playwright_instance = Mock(spec=Playwright)
        mock_playwright_instance.chromium = Mock()
        mock_playwright_instance.chromium.launch.return_value = mock_browser
        mock_sync_playwright.return_value.start.return_value = mock_playwright_instance

        yield {
            "sync_playwright": mock_sync_playwright,
            "playwright": mock_playwright_instance,
            "browser": mock_browser,
            "context": mock_context,
            "page": mock_page,
        }


@pytest.fixture
def playwright_tools(mock_playwright_env):
    tools = PlaywrightTools()
    yield tools


@pytest.fixture
def playwright_tools_initialized(mock_playwright_env):
    tools = PlaywrightTools()
    tools._playwright = mock_playwright_env["playwright"]
    tools._browser = mock_playwright_env["browser"]
    tools._page = mock_playwright_env["page"]
    tools._session_initialized = True
    return tools


def test_init_with_defaults():
    with patch("agno.tools.playwright.sync_playwright"):
        tools = PlaywrightTools()

        assert tools.timeout == DEFAULT_TIMEOUT
        assert tools.headless is True
        assert tools._playwright is None
        assert tools._browser is None
        assert tools._page is None
        assert tools._session_initialized is False


def test_init_with_custom_params():
    with patch("agno.tools.playwright.sync_playwright"):
        tools = PlaywrightTools(timeout=30000, headless=False)

        assert tools.timeout == 30000
        assert tools.headless is False


def test_init_registers_all_tools():
    with patch("agno.tools.playwright.sync_playwright"):
        tools = PlaywrightTools()

        expected_tools = [
            "navigate_to",
            "screenshot",
            "get_page_content",
            "close_session",
            "get_current_url",
            "go_back",
            "go_forward",
            "reload_page",
            "click_element",
            "fill_input",
            "wait_for_element",
            "scroll_page",
            "extract_text",
            "get_page_title",
            "submit_form",
        ]

        registered_tools = [func.name for func in tools.functions.values()]
        for tool_name in expected_tools:
            assert tool_name in registered_tools


def test_ensure_browser_ready_initializes_browser(playwright_tools, mock_playwright_env):
    playwright_tools._ensure_browser_ready()

    assert playwright_tools._session_initialized is True
    mock_playwright_env["playwright"].chromium.launch.assert_called_once_with(headless=True)
    mock_playwright_env["browser"].new_context.assert_called_once()
    mock_playwright_env["context"].new_page.assert_called_once()


def test_ensure_browser_ready_skips_if_initialized(playwright_tools_initialized, mock_playwright_env):
    mock_playwright_env["sync_playwright"].reset_mock()

    playwright_tools_initialized._ensure_browser_ready()

    mock_playwright_env["sync_playwright"].assert_not_called()


def test_ensure_browser_ready_error_triggers_cleanup(mock_playwright_env):
    mock_playwright_env["playwright"].chromium.launch.side_effect = Exception("Launch failed")

    tools = PlaywrightTools()

    with pytest.raises(Exception, match="Launch failed"):
        tools._ensure_browser_ready()

    assert tools._session_initialized is False


def test_navigate_to_success(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.title.return_value = "Example Page"

    result = playwright_tools_initialized.navigate_to("https://example.com")
    result_data = json.loads(result)

    assert result_data["status"] == "complete"
    assert result_data["title"] == "Example Page"
    assert result_data["url"] == "https://example.com"
    mock_page.goto.assert_called_once_with("https://example.com", wait_until="networkidle", timeout=DEFAULT_TIMEOUT)


def test_get_current_url(playwright_tools_initialized, mock_playwright_env):
    mock_playwright_env["page"].url = "https://current.example.com"

    result = playwright_tools_initialized.get_current_url()
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["url"] == "https://current.example.com"


def test_go_back_success(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.url = "https://previous.example.com"

    result = playwright_tools_initialized.go_back()
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["action"] == "go_back"
    assert result_data["url"] == "https://previous.example.com"


def test_go_back_error(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.go_back.side_effect = Exception("No history")

    with pytest.raises(Exception, match="No history"):
        playwright_tools_initialized.go_back()


def test_go_forward_success(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.url = "https://next.example.com"

    result = playwright_tools_initialized.go_forward()
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["action"] == "go_forward"
    assert result_data["url"] == "https://next.example.com"


def test_go_forward_error(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.go_forward.side_effect = Exception("No forward history")

    with pytest.raises(Exception, match="No forward history"):
        playwright_tools_initialized.go_forward()


def test_reload_page_success(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.url = "https://reloaded.example.com"

    result = playwright_tools_initialized.reload_page()
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["action"] == "reload"
    assert result_data["url"] == "https://reloaded.example.com"


def test_reload_page_error(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.reload.side_effect = Exception("Reload failed")

    with pytest.raises(Exception, match="Reload failed"):
        playwright_tools_initialized.reload_page()


def test_get_page_content(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.content.return_value = "<html><body><h1>Hello</h1></body></html>"

    result = playwright_tools_initialized.get_page_content()

    assert result == "<html><body><h1>Hello</h1></body></html>"
    mock_page.content.assert_called_once()


def test_get_page_title(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.title.return_value = "My Page Title"

    result = playwright_tools_initialized.get_page_title()
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["title"] == "My Page Title"


def test_extract_text_full_page(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.evaluate.return_value = "Full page text content"

    result = playwright_tools_initialized.extract_text()
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["text"] == "Full page text content"
    assert result_data["selector"] is None


def test_extract_text_with_selector(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_element = Mock()
    mock_element.text_content.return_value = "Element text"
    mock_page.query_selector.return_value = mock_element

    result = playwright_tools_initialized.extract_text(selector=".content")
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["text"] == "Element text"
    assert result_data["selector"] == ".content"


def test_extract_text_selector_not_found(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.query_selector.return_value = None

    result = playwright_tools_initialized.extract_text(selector=".nonexistent")
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["text"] == ""


def test_extract_text_error(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.wait_for_load_state.side_effect = Exception("Timeout")

    with pytest.raises(Exception, match="Timeout"):
        playwright_tools_initialized.extract_text()


def test_screenshot_full_page(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = playwright_tools_initialized.screenshot("/tmp/screenshot.png", full_page=True)
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["path"] == "/tmp/screenshot.png"
    mock_page.screenshot.assert_called_once_with(path="/tmp/screenshot.png", full_page=True)


def test_screenshot_viewport_only(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = playwright_tools_initialized.screenshot("/tmp/viewport.png", full_page=False)
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    mock_page.screenshot.assert_called_once_with(path="/tmp/viewport.png", full_page=False)


def test_click_element(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = playwright_tools_initialized.click_element("button.submit")
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["action"] == "click"
    assert result_data["selector"] == "button.submit"
    mock_page.click.assert_called_once_with("button.submit", timeout=DEFAULT_TIMEOUT)


def test_fill_input(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = playwright_tools_initialized.fill_input("input#email", "test@example.com")
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["action"] == "fill"
    assert result_data["selector"] == "input#email"
    assert result_data["text"] == "test@example.com"
    mock_page.fill.assert_called_once_with("input#email", "test@example.com", timeout=DEFAULT_TIMEOUT)


def test_wait_for_element(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = playwright_tools_initialized.wait_for_element(".loading-complete")
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["action"] == "wait_for_element"
    assert result_data["selector"] == ".loading-complete"
    mock_page.wait_for_selector.assert_called_once_with(".loading-complete", timeout=DEFAULT_TIMEOUT)


def test_submit_form_with_navigation(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.expect_navigation.return_value.__enter__ = Mock()
    mock_page.expect_navigation.return_value.__exit__ = Mock(return_value=False)

    result = playwright_tools_initialized.submit_form("form#login", wait_for_navigation=True)
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["action"] == "form_submit"
    assert result_data["selector"] == "form#login"
    mock_page.locator.assert_called_once_with("form#login")


def test_submit_form_without_navigation(playwright_tools_initialized, mock_playwright_env):
    result = playwright_tools_initialized.submit_form("form#search", wait_for_navigation=False)
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["action"] == "form_submit"


def test_submit_form_error(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.locator.side_effect = Exception("Form not found")

    with pytest.raises(Exception, match="Form not found"):
        playwright_tools_initialized.submit_form("form#nonexistent")


def test_scroll_page_down(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = playwright_tools_initialized.scroll_page(direction="down", pixels=500)
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["action"] == "scroll"
    assert result_data["direction"] == "down"
    assert result_data["pixels"] == 500
    mock_page.evaluate.assert_called_once_with("window.scrollBy(0, 500)")


def test_scroll_page_up(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = playwright_tools_initialized.scroll_page(direction="up", pixels=300)
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["direction"] == "up"
    mock_page.evaluate.assert_called_once_with("window.scrollBy(0, -300)")


def test_scroll_page_left(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    playwright_tools_initialized.scroll_page(direction="left", pixels=200)

    mock_page.evaluate.assert_called_once_with("window.scrollBy(-200, 0)")


def test_scroll_page_right(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    playwright_tools_initialized.scroll_page(direction="right", pixels=200)

    mock_page.evaluate.assert_called_once_with("window.scrollBy(200, 0)")


def test_scroll_page_invalid_direction(playwright_tools_initialized):
    with pytest.raises(ValueError, match="Invalid direction"):
        playwright_tools_initialized.scroll_page(direction="diagonal", pixels=100)


def test_scroll_page_pixels_validation_min(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = playwright_tools_initialized.scroll_page(direction="down", pixels=-100)
    result_data = json.loads(result)

    assert result_data["pixels"] == 1
    mock_page.evaluate.assert_called_once_with("window.scrollBy(0, 1)")


def test_scroll_page_pixels_validation_max(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]

    result = playwright_tools_initialized.scroll_page(direction="down", pixels=50000)
    result_data = json.loads(result)

    assert result_data["pixels"] == 10000
    mock_page.evaluate.assert_called_once_with("window.scrollBy(0, 10000)")


def test_close_session_success(playwright_tools_initialized):
    result = playwright_tools_initialized.close_session()
    result_data = json.loads(result)

    assert result_data["status"] == "closed"
    assert "Local browser closed" in result_data["message"]
    assert playwright_tools_initialized._session_initialized is False


def test_close_session_cleanup_exception(playwright_tools_initialized):
    with patch.object(playwright_tools_initialized, "_cleanup_resources", side_effect=Exception("Cleanup failed")):
        result = playwright_tools_initialized.close_session()
        result_data = json.loads(result)

        assert result_data["status"] == "warning"
        assert "Cleanup completed with warning" in result_data["message"]


def test_cleanup_resources_handles_browser_close_error(playwright_tools_initialized, mock_playwright_env):
    mock_playwright_env["browser"].close.side_effect = Exception("Close error")

    playwright_tools_initialized._cleanup_resources()

    assert playwright_tools_initialized._browser is None
    assert playwright_tools_initialized._session_initialized is False


def test_cleanup_resources_handles_playwright_stop_error(playwright_tools_initialized, mock_playwright_env):
    mock_playwright_env["playwright"].stop.side_effect = Exception("Stop error")

    playwright_tools_initialized._cleanup_resources()

    assert playwright_tools_initialized._playwright is None


def test_get_page_content_empty_page(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.content.return_value = ""

    result = playwright_tools_initialized.get_page_content()

    assert result == ""


def test_scroll_with_default_values(playwright_tools_initialized, mock_playwright_env):
    result = playwright_tools_initialized.scroll_page()
    result_data = json.loads(result)

    assert result_data["direction"] == "down"
    assert result_data["pixels"] == 500


def test_cleanup_with_no_resources():
    with patch("agno.tools.playwright.sync_playwright"):
        tools = PlaywrightTools()
        tools._browser = None
        tools._playwright = None
        tools._page = None

        tools._cleanup_resources()

        assert tools._session_initialized is False


def test_wait_and_extract_text_success(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_element = Mock()
    mock_element.inner_text.return_value = "Found text"
    mock_page.query_selector.return_value = mock_element

    result = playwright_tools_initialized.wait_and_extract_text(".content")
    result_data = json.loads(result)

    assert result_data["status"] == "success"
    assert result_data["text"] == "Found text"
    assert result_data["attempt"] == 1


def test_wait_and_extract_text_empty_content(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_element = Mock()
    mock_element.inner_text.return_value = ""
    mock_page.query_selector.return_value = mock_element

    result = playwright_tools_initialized.wait_and_extract_text(".content", max_attempts=2, wait_seconds=0)
    result_data = json.loads(result)

    assert result_data["status"] == "warning"
    assert "No content found" in result_data["message"]


def test_wait_and_extract_text_error(playwright_tools_initialized, mock_playwright_env):
    mock_page = mock_playwright_env["page"]
    mock_page.wait_for_selector.side_effect = Exception("Timeout")

    result = playwright_tools_initialized.wait_and_extract_text(".content", max_attempts=1)
    result_data = json.loads(result)

    assert result_data["status"] == "error"
    assert "Timeout" in result_data["error"]


def test_custom_timeout_used_in_operations(mock_playwright_env):
    custom_timeout = 30000

    with patch("agno.tools.playwright.sync_playwright"):
        tools = PlaywrightTools(timeout=custom_timeout)
        tools._playwright = mock_playwright_env["playwright"]
        tools._browser = mock_playwright_env["browser"]
        tools._page = mock_playwright_env["page"]
        tools._session_initialized = True

        tools.click_element("button")

        mock_playwright_env["page"].click.assert_called_once_with("button", timeout=custom_timeout)
