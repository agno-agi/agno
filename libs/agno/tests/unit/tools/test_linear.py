"""Unit tests for LinearTools."""

from unittest.mock import Mock, patch

import pytest

from agno.tools.linear import LinearTools


def test_linear_tools_init_without_api_key():
    """Test initialization fails when no API key is provided."""
    with patch.dict("os.environ", clear=True), pytest.raises(ValueError, match="Linear API key is required"):
        LinearTools()


def test_linear_tools_default_timeout():
    """Test default timeout is 30 seconds."""
    tools = LinearTools(api_key="test-api-key")
    assert tools.timeout == 30


def test_linear_tools_custom_timeout():
    """Test custom timeout is respected."""
    tools = LinearTools(api_key="test-api-key", timeout=45)
    assert tools.timeout == 45


@patch("agno.tools.linear.requests.post")
def test_linear_tools_execute_query_default_timeout(mock_post):
    """Test _execute_query passes default timeout to requests.post."""
    mock_response = Mock()
    mock_response.json.return_value = {"data": {"viewer": {"id": "1", "name": "Test"}}}
    mock_post.return_value = mock_response

    tools = LinearTools(api_key="test-api-key")
    result = tools._execute_query("query { viewer { id name } }")

    assert result == {"viewer": {"id": "1", "name": "Test"}}
    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs["timeout"] == 30


@patch("agno.tools.linear.requests.post")
def test_linear_tools_execute_query_custom_timeout(mock_post):
    """Test _execute_query passes custom timeout to requests.post."""
    mock_response = Mock()
    mock_response.json.return_value = {"data": {"viewer": {"id": "1", "name": "Test"}}}
    mock_post.return_value = mock_response

    tools = LinearTools(api_key="test-api-key", timeout=60)
    result = tools._execute_query("query { viewer { id name } }")

    assert result == {"viewer": {"id": "1", "name": "Test"}}
    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs["timeout"] == 60
