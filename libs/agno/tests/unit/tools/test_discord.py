"""Unit tests for DiscordTools."""

from unittest.mock import Mock, patch

import pytest

from agno.tools.discord import DiscordTools


def test_discord_tools_init_without_bot_token():
    """Test initialization fails when no bot token is provided."""
    with patch.dict("os.environ", clear=True), pytest.raises(ValueError, match="Discord bot token is required"):
        DiscordTools()


def test_discord_tools_default_timeout():
    """Test default timeout is 30 seconds."""
    tools = DiscordTools(bot_token="test-bot-token")
    assert tools.timeout == 30


def test_discord_tools_custom_timeout():
    """Test custom timeout is respected."""
    tools = DiscordTools(bot_token="test-bot-token", timeout=15)
    assert tools.timeout == 15


@patch("agno.tools.discord.requests.request")
def test_discord_tools_make_request_default_timeout(mock_request):
    """Test _make_request passes default timeout to requests.request."""
    mock_response = Mock()
    mock_response.text = '{"id": "123"}'
    mock_response.json.return_value = {"id": "123"}
    mock_request.return_value = mock_response

    tools = DiscordTools(bot_token="test-bot-token")
    result = tools._make_request("GET", "/channels/123")

    assert result == {"id": "123"}
    mock_request.assert_called_once()
    assert mock_request.call_args.kwargs["timeout"] == 30


@patch("agno.tools.discord.requests.request")
def test_discord_tools_make_request_custom_timeout(mock_request):
    """Test _make_request passes custom timeout to requests.request."""
    mock_response = Mock()
    mock_response.text = '{"id": "123"}'
    mock_response.json.return_value = {"id": "123"}
    mock_request.return_value = mock_response

    tools = DiscordTools(bot_token="test-bot-token", timeout=50)
    result = tools._make_request("POST", "/channels/123/messages", data={"content": "hello"})

    assert result == {"id": "123"}
    mock_request.assert_called_once()
    assert mock_request.call_args.kwargs["timeout"] == 50
