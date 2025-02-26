"""Unit tests for WebexTools class."""

import json
from unittest.mock import Mock, patch

import pytest
from requests import Response
from webexpythonsdk import WebexAPI
from webexpythonsdk.exceptions import RateLimitError

from agno.tools.webex import WebexTools


@pytest.fixture
def mock_webex_api():
    """Create a mock Webex API client."""
    with patch("agno.tools.webex.WebexAPI") as mock_api:
        # Create mock for nested attributes
        mock_client = Mock(spec=WebexAPI)
        mock_messages = Mock()
        mock_rooms = Mock()

        # Set up the nested structure
        mock_client.messages = mock_messages
        mock_client.rooms = mock_rooms

        mock_api.return_value = mock_client
        return mock_client


@pytest.fixture
def webex_tools(mock_webex_api):
    """Create WebexTools instance with mocked API."""
    with patch.dict("os.environ", {"WEBEX_ACCESS_TOKEN": "test_token"}):
        tools = WebexTools()
        tools.client = mock_webex_api
        return tools


def test_init_with_api_token():
    """Test initialization with provided API token."""
    with patch("agno.tools.webex.WebexAPI") as mock_api:
        WebexTools(access_token="test_token")
        mock_api.assert_called_once_with(access_token="test_token")


def test_init_with_env_var():
    """Test initialization with environment variable."""
    with patch("agno.tools.webex.WebexAPI") as mock_api:
        with patch.dict("os.environ", {"WEBEX_ACCESS_TOKEN": "env_token"}):
            WebexTools()
            mock_api.assert_called_once_with(access_token="env_token")


def test_init_without_token():
    """Test initialization without API token."""
    with patch.dict("os.environ", clear=True):
        with pytest.raises(ValueError, match="Webex access token is not set"):
            WebexTools()


def test_init_with_selective_tools():
    """Test initialization with only selected tools."""
    with patch.dict("os.environ", {"WEBEX_ACCESS_TOKEN": "test_token"}):
        tools = WebexTools(
            send_message=True,
            list_rooms=False,
        )

        assert "send_message" in [func.name for func in tools.functions.values()]
        assert "list_rooms" not in [func.name for func in tools.functions.values()]


def test_send_message_success(webex_tools, mock_webex_api):
    """Test successful message sending."""
    mock_response = Mock()
    mock_response.json_data = {
        "id": "msg123",
        "roomId": "room123",
        "text": "Test message",
        "created": "2024-01-01T10:00:00.000Z",
    }

    mock_webex_api.messages.create.return_value = mock_response

    result = webex_tools.send_message("room123", "Test message")
    result_data = json.loads(result)

    assert result_data["id"] == "msg123"
    assert result_data["roomId"] == "room123"
    assert result_data["text"] == "Test message"
    mock_webex_api.messages.create.assert_called_once_with(roomId="room123", text="Test message")


def test_list_rooms_success(webex_tools, mock_webex_api):
    """Test successful room listing."""
    # Create mock room objects
    mock_room1 = Mock()
    mock_room1.id = "room123"
    mock_room1.title = "Test Room 1"
    mock_room1.type = "group"
    mock_room1.isPublic = True
    mock_room1.isReadOnly = False

    mock_room2 = Mock()
    mock_room2.id = "room456"
    mock_room2.title = "Test Room 2"
    mock_room2.type = "direct"
    mock_room2.isPublic = False
    mock_room2.isReadOnly = True

    # Set up the mock return value
    mock_webex_api.rooms.list.return_value = [mock_room1, mock_room2]

    result = webex_tools.list_rooms()
    result_data = json.loads(result)

    assert len(result_data["rooms"]) == 2
    assert result_data["rooms"][0]["id"] == "room123"
    assert result_data["rooms"][0]["title"] == "Test Room 1"
    assert result_data["rooms"][1]["id"] == "room456"
    assert result_data["rooms"][1]["title"] == "Test Room 2"


def test_list_rooms_failure(webex_tools, mock_webex_api):
    """Test room listing failure."""
    response = Response()
    response.status_code = 429  # Rate limit status code
    response.reason = "Too Many Requests"
    mock_webex_api.rooms.list.side_effect = RateLimitError(response)

    result = webex_tools.list_rooms()
    result_data = json.loads(result)

    assert "error" in result_data
    assert "Too Many Requests" in str(result_data["error"])


def test_list_rooms_empty(webex_tools, mock_webex_api):
    """Test listing when no rooms are available."""
    mock_webex_api.rooms.list.return_value = []

    result = webex_tools.list_rooms()
    result_data = json.loads(result)

    assert len(result_data["rooms"]) == 0


def test_send_message_rate_limit(webex_tools, mock_webex_api):
    """Test sending empty message."""
    response = Response()
    response.status_code = 429  # Rate limit status code
    response.reason = "Too Many Requests"
    mock_webex_api.messages.create.side_effect = RateLimitError(response)

    result = webex_tools.send_message("room123", "")
    result_data = json.loads(result)

    assert "error" in result_data
    assert "Too Many Requests" in str(result_data["error"])
