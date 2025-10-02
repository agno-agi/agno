"""Unit tests for WebTools class."""

from unittest.mock import Mock, patch

import pytest

from agno.tools.webtools import WebTools


@pytest.fixture
def web_tools():
    """Fixture to create a WebTools instance."""
    return WebTools(retries=3)


def test_expand_url_success(web_tools):
    """Test successful expansion of a URL."""
    mock_url = "https://tinyurl.com/k2fkfxra."
    final_url = "https://github.com/agno-agi/agno"

    mock_response = Mock()
    mock_response.url = final_url

    with patch("httpx.head", return_value=mock_response) as mock_head:
        result = web_tools.expand_url(mock_url)

    assert result == final_url
    mock_head.assert_called_once_with(mock_url, follow_redirects=True, timeout=5)


def test_toolkit_registration(web_tools):
    """Test that the expand_url method is registered correctly."""
    assert "expand_url" in [func.name for func in web_tools.functions.values()]
