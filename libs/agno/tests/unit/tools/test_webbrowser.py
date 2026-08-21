"""Unit tests for WebBrowserTools class."""

import json
from unittest.mock import patch

import pytest

from agno.tools.webbrowser import WebBrowserTools


@pytest.fixture
def webbrowser_tools():
    """Create a WebBrowserTools instance with open_page enabled."""
    return WebBrowserTools(open_page=True)


def test_initialization():
    """Test initialization of WebBrowserTools."""
    # Default: open_page disabled
    tools = WebBrowserTools()
    assert tools.name == "webbrowser_tools"
    function_names = [func.name for func in tools.functions.values()]
    assert "open_page" not in function_names

    # With open_page enabled
    tools = WebBrowserTools(open_page=True)
    function_names = [func.name for func in tools.functions.values()]
    assert "open_page" in function_names


@patch("webbrowser.open_new_tab")
def test_open_page(mock_open_new_tab, webbrowser_tools):
    """Test open_page operation."""
    url = "https://example.com"
    result = webbrowser_tools.open_page(url)

    mock_open_new_tab.assert_called_once_with(url)
    data = json.loads(result)
    assert data["status"] == "success"


@patch("webbrowser.open_new")
def test_open_page_new_window(mock_open_new, webbrowser_tools):
    """Test open_page with new_window=True."""
    url = "https://example.com"
    result = webbrowser_tools.open_page(url, new_window=True)

    mock_open_new.assert_called_once_with(url)
    data = json.loads(result)
    assert data["status"] == "success"


@patch("webbrowser.open_new_tab", side_effect=Exception("Browser error"))
def test_open_page_error_handling(mock_open_new_tab, webbrowser_tools):
    """Test error handling when browser opening fails."""
    url = "https://example.com"
    result = webbrowser_tools.open_page(url)

    mock_open_new_tab.assert_called_once_with(url)
    data = json.loads(result)
    assert "error" in data
