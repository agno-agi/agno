"""Unit tests for WebBrowserTools class."""

from unittest.mock import patch

import pytest

from agno.tools.webbrowser import WebBrowserTools


@pytest.fixture
def webbrowser_tools():
    """Create a WebBrowserTools instance."""
    return WebBrowserTools()


def test_initialization(webbrowser_tools):
    """Test initialization of WebBrowserTools."""
    # Check if the tool name is correct
    assert webbrowser_tools.name == "webbrowser_tools"

    # Check if open_page function is registered
    function_names = [func.name for func in webbrowser_tools.functions.values()]
    assert "open_page" in function_names
    assert len(webbrowser_tools.functions) == 1  # Only open_page should be registered


@patch("webbrowser.open_new_tab")
def test_open_page(mock_open_new_tab, webbrowser_tools):
    """Test open_page operation."""
    # Test opening a regular URL
    url = "https://example.com"
    result = webbrowser_tools.open_page(url)

    # Verify the mock was called with the correct URL
    mock_open_new_tab.assert_called_once_with(url)

    # Since the function doesn't return anything special, we'd expect None
    assert result is None


@patch("webbrowser.open_new")
def test_open_page_new_window(mock_open_new, webbrowser_tools):
    """Test open_page operation."""
    # Test opening a regular URL
    url = "https://example.com"
    result = webbrowser_tools.open_page(url, new_window=True)

    # Verify the mock was called with the correct URL
    mock_open_new.assert_called_once_with(url)

    # Since the function doesn't return anything special, we'd expect None
    assert result is None


@patch("webbrowser.open_new_tab", side_effect=Exception("Browser error"))
def test_open_page_error_handling(mock_open_new_tab, webbrowser_tools):
    """Test error handling when browser opening fails."""
    url = "https://example.com"

    # The function should raise an exception if the browser fails to open
    with pytest.raises(Exception) as excinfo:
        webbrowser_tools.open_page(url)

    # Verify the exception is propagated
    assert "Browser error" in str(excinfo.value)

    # Verify the mock was called with the correct URL
    mock_open_new_tab.assert_called_once_with(url)
