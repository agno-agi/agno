"""Unit tests for DiscordTools class."""

from unittest.mock import patch

import pytest

from agno.tools.discord import DiscordTools


@pytest.fixture
def mock_requests_request():
    """Mock requests.request to return an empty Discord response."""
    with patch("agno.tools.discord.requests.request") as mock_request:
        mock_request.return_value.text = ""
        yield mock_request


def test_send_message_passes_default_timeout(mock_requests_request):
    """Test that the Discord request receives the default HTTP timeout."""
    tools = DiscordTools(bot_token="test-bot-token")
    tools.send_message("123", "hello")

    assert mock_requests_request.call_args[1]["timeout"] == 30


def test_send_message_passes_configured_timeout(mock_requests_request):
    """Test that the Discord request receives the configured HTTP timeout."""
    tools = DiscordTools(bot_token="test-bot-token", timeout=12)
    tools.send_message("123", "hello")

    assert mock_requests_request.call_args[1]["timeout"] == 12
