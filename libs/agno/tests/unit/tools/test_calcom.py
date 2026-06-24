"""Unit tests for CalComTools class."""

from unittest.mock import Mock, patch

import pytest

from agno.tools.calcom import CalComTools


@pytest.fixture
def mock_requests():
    """Mock the requests module."""
    with patch("agno.tools.calcom.requests") as mock_req:
        yield mock_req


@pytest.fixture
def calcom_tools():
    """Create a CalComTools instance."""
    return CalComTools(api_key="test_key", event_type_id=123, user_timezone="UTC")


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================


def test_init_with_params():
    """Test initialization with parameters."""
    tools = CalComTools(api_key="my_key", event_type_id=42, user_timezone="Asia/Kolkata", timeout=60)
    assert tools.api_key == "my_key"
    assert tools.event_type_id == 42
    assert tools.user_timezone == "Asia/Kolkata"
    assert tools.timeout == 60


def test_init_default_timeout():
    """Test initialization uses default timeout of 30s."""
    tools = CalComTools(api_key="key", event_type_id=1)
    assert tools.timeout == 30


def test_init_with_env_vars():
    """Test initialization with environment variables."""
    with patch.dict("os.environ", {"CALCOM_API_KEY": "env_key", "CALCOM_EVENT_TYPE_ID": "99"}):
        tools = CalComTools()
        assert tools.api_key == "env_key"
        assert tools.event_type_id == 99


def test_init_default_tools():
    """Test default initialization enables all tools."""
    tools = CalComTools(api_key="key", event_type_id=1)
    tool_names = [t.__name__ for t in tools.tools]
    assert "get_available_slots" in tool_names
    assert "create_booking" in tool_names
    assert "get_upcoming_bookings" in tool_names
    assert "reschedule_booking" in tool_names
    assert "cancel_booking" in tool_names


def test_init_selective_tools():
    """Test initialization with selective flags."""
    tools = CalComTools(
        api_key="key",
        event_type_id=1,
        enable_get_available_slots=True,
        enable_create_booking=False,
        enable_get_upcoming_bookings=False,
        enable_reschedule_booking=False,
        enable_cancel_booking=False,
    )
    tool_names = [t.__name__ for t in tools.tools]
    assert "get_available_slots" in tool_names
    assert "create_booking" not in tool_names


# ============================================================================
# TIMEOUT TESTS
# ============================================================================


def test_get_available_slots_passes_timeout(calcom_tools, mock_requests):
    """Test get_available_slots passes timeout to requests.get."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": {"slots": {}}}
    mock_requests.get.return_value = mock_response

    calcom_tools.get_available_slots("2026-01-01", "2026-01-02")

    mock_requests.get.assert_called_once()
    call_kwargs = mock_requests.get.call_args[1]
    assert call_kwargs["timeout"] == 30


def test_create_booking_passes_timeout(calcom_tools, mock_requests):
    """Test create_booking passes timeout to requests.post."""
    mock_response = Mock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"data": {"start": "2026-01-01T10:00:00Z", "uid": "abc123"}}
    mock_requests.post.return_value = mock_response

    calcom_tools.create_booking("2026-01-01T10:00:00Z", "Test User", "test@example.com")

    mock_requests.post.assert_called_once()
    call_kwargs = mock_requests.post.call_args[1]
    assert call_kwargs["timeout"] == 30


def test_get_upcoming_bookings_passes_timeout(calcom_tools, mock_requests):
    """Test get_upcoming_bookings passes timeout to requests.get."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": []}
    mock_requests.get.return_value = mock_response

    calcom_tools.get_upcoming_bookings()

    mock_requests.get.assert_called_once()
    call_kwargs = mock_requests.get.call_args[1]
    assert call_kwargs["timeout"] == 30


def test_reschedule_booking_passes_timeout(calcom_tools, mock_requests):
    """Test reschedule_booking passes timeout to requests.post."""
    mock_response = Mock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"data": {"start": "2026-01-02T10:00:00Z", "uid": "new123"}}
    mock_requests.post.return_value = mock_response

    calcom_tools.reschedule_booking("abc123", "2026-01-02T10:00:00Z", "conflict")

    mock_requests.post.assert_called_once()
    call_kwargs = mock_requests.post.call_args[1]
    assert call_kwargs["timeout"] == 30


def test_cancel_booking_passes_timeout(calcom_tools, mock_requests):
    """Test cancel_booking passes timeout to requests.post."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_requests.post.return_value = mock_response

    calcom_tools.cancel_booking("abc123", "no longer needed")

    mock_requests.post.assert_called_once()
    call_kwargs = mock_requests.post.call_args[1]
    assert call_kwargs["timeout"] == 30


def test_custom_timeout_is_used(mock_requests):
    """Test custom timeout value is passed to HTTP calls."""
    tools = CalComTools(api_key="key", event_type_id=1, timeout=120)

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": {"slots": {}}}
    mock_requests.get.return_value = mock_response

    tools.get_available_slots("2026-01-01", "2026-01-02")

    call_kwargs = mock_requests.get.call_args[1]
    assert call_kwargs["timeout"] == 120


# ============================================================================
# FUNCTIONAL TESTS
# ============================================================================


def test_get_available_slots_success(calcom_tools, mock_requests):
    """Test get_available_slots returns formatted slots."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {"slots": {"2026-01-01": [{"time": "2026-01-01T10:00:00Z"}, {"time": "2026-01-01T11:00:00Z"}]}}
    }
    mock_requests.get.return_value = mock_response

    result = calcom_tools.get_available_slots("2026-01-01", "2026-01-01")

    assert "Available slots:" in result


def test_get_available_slots_failure(calcom_tools, mock_requests):
    """Test get_available_slots handles API failure."""
    mock_response = Mock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"
    mock_requests.get.return_value = mock_response

    result = calcom_tools.get_available_slots("2026-01-01", "2026-01-02")

    assert "Failed to fetch slots" in result


def test_get_available_slots_exception(calcom_tools, mock_requests):
    """Test get_available_slots handles exceptions."""
    mock_requests.get.side_effect = Exception("Connection refused")

    result = calcom_tools.get_available_slots("2026-01-01", "2026-01-02")

    assert "Error:" in result


def test_create_booking_success(calcom_tools, mock_requests):
    """Test create_booking returns confirmation."""
    mock_response = Mock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"data": {"start": "2026-01-01T10:00:00Z", "uid": "booking-123"}}
    mock_requests.post.return_value = mock_response

    result = calcom_tools.create_booking("2026-01-01T10:00:00Z", "Alice", "alice@example.com")

    assert "Booking created successfully" in result
    assert "booking-123" in result


def test_get_upcoming_bookings_empty(calcom_tools, mock_requests):
    """Test get_upcoming_bookings with no results."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": []}
    mock_requests.get.return_value = mock_response

    result = calcom_tools.get_upcoming_bookings()

    assert "No upcoming bookings found" in result


def test_cancel_booking_success(calcom_tools, mock_requests):
    """Test cancel_booking returns success."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_requests.post.return_value = mock_response

    result = calcom_tools.cancel_booking("uid-123", "changed plans")

    assert "Booking cancelled successfully" in result
