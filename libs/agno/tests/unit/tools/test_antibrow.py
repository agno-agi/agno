"""Unit tests for AntibrowTools, in the shape agno's own tool tests use:
the SDK entry point is patched, so nothing here launches a browser."""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from agno.tools.antibrow import AntibrowTools


@pytest.fixture
def mock_launch():
    with patch("agno.tools.antibrow.launch") as launch:
        page = Mock()
        page.title.return_value = "Example Domain"
        page.url = "https://example.com/"
        response = Mock()
        response.status = 200
        page.goto.return_value = response
        locator = MagicMock()
        locator.first.inner_text.return_value = "Example Domain"
        page.locator.return_value = locator
        browser = Mock()
        browser.new_page.return_value = page
        launch.return_value = browser
        yield {"launch": launch, "browser": browser, "page": page, "locator": locator}


@pytest.fixture
def tools(mock_launch):
    return AntibrowTools(api_key="test_key", profile="test-profile")


def test_toolkit_registers_every_tool(tools):
    assert tools.name == "antibrow_tools"
    assert sorted(f.name for f in tools.functions.values()) == [
        "click",
        "close_session",
        "fill",
        "get_page_content",
        "navigate_to",
        "screenshot",
    ]


def test_disabled_tools_are_not_registered(mock_launch):
    tools = AntibrowTools(api_key="k", enable_screenshot=False, enable_fill=False)
    names = {f.name for f in tools.functions.values()}
    assert "screenshot" not in names and "fill" not in names
    assert "navigate_to" in names


def test_browser_is_launched_once_and_lazily(tools, mock_launch):
    assert mock_launch["launch"].call_count == 0
    tools.navigate_to("https://example.com")
    tools.get_page_content()
    assert mock_launch["launch"].call_count == 1
    _, kwargs = mock_launch["launch"].call_args
    assert kwargs["api_key"] == "test_key"
    assert kwargs["focus_window"] is False


def test_navigate_to_returns_status_title_url(tools, mock_launch):
    result = json.loads(tools.navigate_to("https://example.com"))
    assert result == {"status": 200, "title": "Example Domain", "url": "https://example.com/"}
    mock_launch["page"].goto.assert_called_once_with("https://example.com", wait_until="load")


def test_get_page_content_uses_body_by_default(tools, mock_launch):
    result = json.loads(tools.get_page_content())
    assert result["content"] == "Example Domain"
    mock_launch["page"].locator.assert_called_with("body")


def test_get_page_content_truncates(mock_launch):
    mock_launch["locator"].first.inner_text.return_value = "x" * 50
    tools = AntibrowTools(api_key="k", max_content_length=10)
    result = json.loads(tools.get_page_content())
    assert result["content"] == "x" * 10 + "\n\n[content truncated]"


def test_click_and_fill(tools, mock_launch):
    assert json.loads(tools.click("#go")) == {"clicked": "#go", "url": "https://example.com/"}
    assert json.loads(tools.fill("#q", "hello")) == {"filled": "#q", "characters": 5}
    mock_launch["locator"].first.fill.assert_called_once_with("hello")


def test_screenshot(tools, mock_launch):
    assert json.loads(tools.screenshot("/tmp/shot.png")) == {"status": "success", "path": "/tmp/shot.png"}
    mock_launch["page"].screenshot.assert_called_once_with(path="/tmp/shot.png", full_page=True)


def test_close_session_is_idempotent(tools, mock_launch):
    tools.navigate_to("https://example.com")
    assert json.loads(tools.close_session())["status"] == "closed"
    mock_launch["browser"].close.assert_called_once()
    assert json.loads(tools.close_session())["status"] == "closed"
    mock_launch["browser"].close.assert_called_once()


def test_a_failed_launch_leaves_nothing_behind(mock_launch):
    mock_launch["launch"].side_effect = RuntimeError("no kernel")
    tools = AntibrowTools(api_key="k")
    with pytest.raises(RuntimeError):
        tools.navigate_to("https://example.com")
    assert tools._browser is None and tools._page is None
