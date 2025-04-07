"""Unit tests for ZoomTools class."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests

from agno.tools.zoom import ZoomTools


@pytest.fixture
def zoom_tools():
    """Create a ZoomTools instance with mock credentials"""
    return ZoomTools(
        account_id="test_account_id",
        client_id="test_client_id",
        client_secret="test_client_secret",
    )


@pytest.fixture
def mock_token_response():
    """Mock successful token response"""
    return {
        "access_token": "test_access_token",
        "token_type": "bearer",
        "expires_in": 3600,
    }


def test_init_with_credentials():
    """Test initialization with provided credentials"""
    tool = ZoomTools(
        account_id="test_account_id",
        client_id="test_client_id",
        client_secret="test_client_secret",
    )
    assert tool.account_id == "test_account_id"
    assert tool.client_id == "test_client_id"
    assert tool.client_secret == "test_client_secret"


@patch.dict(
    "os.environ",
    {
        "ZOOM_ACCOUNT_ID": "env_account_id",
        "ZOOM_CLIENT_ID": "env_client_id",
        "ZOOM_CLIENT_SECRET": "env_client_secret",
    },
)
def test_init_with_env_vars():
    """Test initialization with environment variables"""
    tool = ZoomTools()
    assert tool.account_id == "env_account_id"
    assert tool.client_id == "env_client_id"
    assert tool.client_secret == "env_client_secret"


def test_get_access_token_success(zoom_tools, mock_token_response):
    """Test successful access token generation"""
    with patch("requests.post") as mock_post:
        mock_post.return_value.json.return_value = mock_token_response
        mock_post.return_value.raise_for_status = MagicMock()

        token = zoom_tools.get_access_token()

        assert token == "test_access_token"
        mock_post.assert_called_once()

        # Verify request format
        args, kwargs = mock_post.call_args
        assert args[0] == "https://zoom.us/oauth/token"
        assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
        assert kwargs["data"]["grant_type"] == "account_credentials"
        assert kwargs["data"]["account_id"] == "test_account_id"


def test_get_access_token_reuse(zoom_tools, mock_token_response):
    """Test token reuse when not expired"""
    with patch("requests.post") as mock_post:
        mock_post.return_value.json.return_value = mock_token_response
        mock_post.return_value.raise_for_status = MagicMock()

        # First call should make the request
        token1 = zoom_tools.get_access_token()
        assert token1 == "test_access_token"
        assert mock_post.call_count == 1

        # Second call should reuse the token
        token2 = zoom_tools.get_access_token()
        assert token2 == "test_access_token"
        assert mock_post.call_count == 1  # No additional calls


def test_get_access_token_refresh_on_expiry(zoom_tools, mock_token_response):
    """Test token refresh when expired"""
    with patch("requests.post") as mock_post:
        mock_post.return_value.json.return_value = mock_token_response
        mock_post.return_value.raise_for_status = MagicMock()

        # Get initial token
        token1 = zoom_tools.get_access_token()
        assert token1 == "test_access_token"

        # Manually expire the token
        zoom_tools._ZoomTools__token_expiry = datetime.now() - timedelta(seconds=1)

        # Should get new token
        token2 = zoom_tools.get_access_token()
        assert token2 == "test_access_token"
        assert mock_post.call_count == 2


def test_get_access_token_failure(zoom_tools):
    """Test handling of token generation failure"""
    with patch("requests.post") as mock_post:
        mock_post.side_effect = requests.RequestException("API Error")

        token = zoom_tools.get_access_token()
        assert token == ""
        assert zoom_tools._ZoomTools__access_token is None
        assert zoom_tools._ZoomTools__token_expiry is None


@pytest.mark.parametrize(
    "method_name,expected_args",
    [
        (
            "schedule_meeting",
            {"topic": "Test Meeting", "start_time": "2024-02-01T10:00:00Z", "duration": 60, "timezone": "UTC"},
        ),
        ("get_upcoming_meetings", {"user_id": "me"}),
        ("list_meetings", {"user_id": "me", "type": "scheduled"}),
        ("get_meeting_recordings", {"meeting_id": "123456789"}),
        ("delete_meeting", {"meeting_id": "123456789"}),
        ("get_meeting", {"meeting_id": "123456789"}),
    ],
)
def test_api_methods_auth_failure(zoom_tools, method_name, expected_args):
    """Test API methods handle authentication failure gracefully"""
    with patch.object(ZoomTools, "get_access_token", return_value=""):
        method = getattr(zoom_tools, method_name)
        result = method(**expected_args)
        error_response = json.loads(result)
        assert "error" in error_response
        assert error_response["error"] == "Failed to obtain access token"


def test_schedule_meeting_success(zoom_tools):
    """Test successful meeting scheduling"""
    mock_response = {
        "id": 123456789,
        "topic": "Test Meeting",
        "start_time": "2024-02-01T10:00:00Z",
        "duration": 60,
        "join_url": "https://zoom.us/j/123456789",
    }

    with patch.object(ZoomTools, "get_access_token", return_value="test_token"), patch("requests.post") as mock_post:
        mock_post.return_value.json.return_value = mock_response
        mock_post.return_value.raise_for_status = MagicMock()

        result = zoom_tools.schedule_meeting(topic="Test Meeting", start_time="2024-02-01T10:00:00Z", duration=60)

        result_data = json.loads(result)
        assert result_data["meeting_id"] == 123456789
        assert result_data["topic"] == "Test Meeting"
        assert result_data["join_url"] == "https://zoom.us/j/123456789"


def test_get_meeting_success(zoom_tools):
    """Test successful meeting retrieval"""
    mock_response = {
        "id": 123456789,
        "topic": "Test Meeting",
        "type": 2,
        "start_time": "2024-02-01T10:00:00Z",
        "duration": 60,
        "timezone": "UTC",
        "created_at": "2024-01-31T10:00:00Z",
        "join_url": "https://zoom.us/j/123456789",
        "settings": {"host_video": True},
    }

    with patch.object(ZoomTools, "get_access_token", return_value="test_token"), patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = mock_response
        mock_get.return_value.raise_for_status = MagicMock()

        result = zoom_tools.get_meeting("123456789")

        result_data = json.loads(result)
        assert result_data["meeting_id"] == "123456789"
        assert result_data["topic"] == "Test Meeting"
        assert result_data["join_url"] == "https://zoom.us/j/123456789"


def test_get_upcoming_meetings_success(zoom_tools):
    """Test successful retrieval of upcoming meetings"""
    mock_response = {
        "page_count": 1,
        "page_number": 1,
        "page_size": 30,
        "total_records": 2,
        "meetings": [
            {
                "id": 123456789,
                "topic": "Meeting 1",
                "start_time": "2024-02-01T10:00:00Z",
            },
            {
                "id": 987654321,
                "topic": "Meeting 2",
                "start_time": "2024-02-02T15:00:00Z",
            },
        ],
    }

    with patch.object(ZoomTools, "get_access_token", return_value="test_token"), patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = mock_response
        mock_get.return_value.raise_for_status = MagicMock()

        result = zoom_tools.get_upcoming_meetings()
        result_data = json.loads(result)

        assert result_data["message"] == "Upcoming meetings retrieved successfully"
        assert len(result_data["meetings"]) == 2
        assert result_data["meetings"][0]["id"] == 123456789
        assert result_data["meetings"][1]["id"] == 987654321


def test_list_meetings_success(zoom_tools):
    """Test successful listing of meetings"""
    mock_response = {
        "page_count": 1,
        "page_number": 1,
        "page_size": 30,
        "total_records": 2,
        "meetings": [
            {
                "id": 123456789,
                "topic": "Scheduled Meeting 1",
                "type": 2,
                "start_time": "2024-02-01T10:00:00Z",
            },
            {
                "id": 987654321,
                "topic": "Scheduled Meeting 2",
                "type": 2,
                "start_time": "2024-02-02T15:00:00Z",
            },
        ],
    }

    with patch.object(ZoomTools, "get_access_token", return_value="test_token"), patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = mock_response
        mock_get.return_value.raise_for_status = MagicMock()

        result = zoom_tools.list_meetings(type="scheduled")
        result_data = json.loads(result)

        assert result_data["message"] == "Meetings retrieved successfully"
        assert result_data["total_records"] == 2
        assert len(result_data["meetings"]) == 2
        assert result_data["meetings"][0]["id"] == 123456789
        assert result_data["meetings"][1]["topic"] == "Scheduled Meeting 2"


def test_get_meeting_recordings_success(zoom_tools):
    """Test successful retrieval of meeting recordings"""
    mock_response = {
        "id": 123456789,
        "uuid": "abcd1234",
        "host_id": "host123",
        "topic": "Recorded Meeting",
        "start_time": "2024-02-01T10:00:00Z",
        "duration": 60,
        "total_size": 1000000,
        "recording_count": 2,
        "recording_files": [
            {
                "id": "rec1",
                "meeting_id": "123456789",
                "recording_type": "shared_screen_with_speaker_view",
                "file_type": "MP4",
                "file_size": 500000,
            },
            {
                "id": "rec2",
                "meeting_id": "123456789",
                "recording_type": "audio_only",
                "file_type": "M4A",
                "file_size": 500000,
            },
        ],
    }

    with patch.object(ZoomTools, "get_access_token", return_value="test_token"), patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = mock_response
        mock_get.return_value.raise_for_status = MagicMock()

        result = zoom_tools.get_meeting_recordings("123456789")
        result_data = json.loads(result)

        assert result_data["message"] == "Meeting recordings retrieved successfully"
        assert result_data["meeting_id"] == "123456789"
        assert result_data["recording_count"] == 2
        assert len(result_data["recording_files"]) == 2
        assert result_data["recording_files"][0]["recording_type"] == "shared_screen_with_speaker_view"
        assert result_data["recording_files"][1]["recording_type"] == "audio_only"


def test_delete_meeting_success(zoom_tools):
    """Test successful meeting deletion"""
    with patch.object(ZoomTools, "get_access_token", return_value="test_token"), patch(
        "requests.delete"
    ) as mock_delete:
        mock_delete.return_value.status_code = 204
        mock_delete.return_value.raise_for_status = MagicMock()

        result = zoom_tools.delete_meeting("123456789")
        result_data = json.loads(result)

        assert result_data["message"] == "Meeting deleted successfully!"
        assert result_data["meeting_id"] == "123456789"

        # Verify the delete request
        mock_delete.assert_called_once()
        args, kwargs = mock_delete.call_args
        assert args[0] == "https://api.zoom.us/v2/meetings/123456789"
        assert kwargs["headers"]["Authorization"] == "Bearer test_token"


@pytest.mark.parametrize(
    "method_name,mock_func,error_message",
    [
        ("get_meeting", "requests.get", "Meeting not found"),
        ("get_upcoming_meetings", "requests.get", "Failed to fetch upcoming meetings"),
        ("list_meetings", "requests.get", "Failed to list meetings"),
        ("get_meeting_recordings", "requests.get", "No recordings found"),
        ("delete_meeting", "requests.delete", "Meeting deletion failed"),
    ],
)
def test_api_methods_request_failure(zoom_tools, method_name, mock_func, error_message):
    """Test API methods handle request failures gracefully"""
    with patch.object(ZoomTools, "get_access_token", return_value="test_token"), patch(mock_func) as mock_request:
        mock_request.side_effect = requests.RequestException(error_message)

        method = getattr(zoom_tools, method_name)
        if method_name == "delete_meeting":
            result = method("123456789", schedule_for_reminder=True)
        else:
            result = method("123456789" if "meeting" in method_name else "me")

        error_response = json.loads(result)
        assert "error" in error_response
        assert error_message in str(error_response["error"])
