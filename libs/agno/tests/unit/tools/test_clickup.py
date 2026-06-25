"""Unit tests for ClickUpTools class."""

from unittest.mock import patch, Mock

import pytest

from agno.tools.clickup import ClickUpTools


@pytest.fixture
def mock_requests():
    with patch("agno.tools.clickup.requests") as mock:
        yield mock


@pytest.fixture
def clickup_tools():
    return ClickUpTools(api_key="test_key", master_space_id="space123")


def test_default_timeout(clickup_tools):
    """ClickUpTools stores the default timeout of 30 seconds."""
    assert clickup_tools.timeout == 30


def test_custom_timeout():
    """ClickUpTools stores a custom timeout value."""
    tools = ClickUpTools(api_key="test_key", master_space_id="space123", timeout=60)
    assert tools.timeout == 60


def test_make_request_passes_timeout(clickup_tools, mock_requests):
    """_make_request forwards self.timeout to requests.request."""
    clickup_tools.timeout = 45
    mock_response = Mock()
    mock_response.json.return_value = {"tasks": []}
    mock_response.raise_for_status = Mock()
    mock_requests.request.return_value = mock_response

    clickup_tools._make_request("GET", "team/space123/space")

    _, kwargs = mock_requests.request.call_args
    assert kwargs["timeout"] == 45


def test_make_request_timeout_raises(clickup_tools, mock_requests):
    """_make_request propagates Timeout exceptions from requests."""
    import requests as req
    mock_requests.request.side_effect = req.exceptions.Timeout("timed out")
    mock_requests.exceptions = req.exceptions

    result = clickup_tools._make_request("GET", "team/space123/space")
    assert "error" in result
