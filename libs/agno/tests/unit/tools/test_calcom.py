"""Unit tests for CalComTools class."""

from unittest.mock import patch, Mock

import pytest

from agno.tools.calcom import CalComTools


@pytest.fixture
def mock_requests():
    with patch("agno.tools.calcom.requests") as mock:
        yield mock


@pytest.fixture
def calcom_tools():
    return CalComTools(api_key="test_key", event_type_id=42, user_timezone="Asia/Kolkata")


def test_default_timeout(calcom_tools):
    """CalComTools stores the default timeout of 30 seconds."""
    assert calcom_tools.timeout == 30


def test_custom_timeout():
    """CalComTools stores a custom timeout value."""
    tools = CalComTools(api_key="test_key", event_type_id=1, timeout=90)
    assert tools.timeout == 90


def test_get_available_slots_passes_timeout(calcom_tools, mock_requests):
    """get_available_slots forwards self.timeout to requests.get."""
    calcom_tools.timeout = 55
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": {"slots": {}}}
    mock_requests.get.return_value = mock_response

    calcom_tools.get_available_slots("2026-07-01", "2026-07-07")

    _, kwargs = mock_requests.get.call_args
    assert kwargs["timeout"] == 55


def test_create_booking_passes_timeout(calcom_tools, mock_requests):
    """create_booking forwards self.timeout to requests.post."""
    calcom_tools.timeout = 20
    mock_response = Mock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"data": {"start": "2026-07-01T10:00:00Z", "uid": "booking-uid-123"}}
    mock_requests.post.return_value = mock_response

    calcom_tools.create_booking("2026-07-01T10:00:00Z", "Test User", "test@example.com")

    _, kwargs = mock_requests.post.call_args
    assert kwargs["timeout"] == 20


def test_get_upcoming_bookings_passes_timeout(calcom_tools, mock_requests):
    """get_upcoming_bookings forwards self.timeout to requests.get."""
    calcom_tools.timeout = 35
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": []}
    mock_requests.get.return_value = mock_response

    calcom_tools.get_upcoming_bookings()

    _, kwargs = mock_requests.get.call_args
    assert kwargs["timeout"] == 35


def test_reschedule_booking_passes_timeout(calcom_tools, mock_requests):
    """reschedule_booking forwards self.timeout to requests.post."""
    calcom_tools.timeout = 25
    mock_response = Mock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"data": {"start": "2026-07-02T10:00:00Z", "uid": "new-uid"}}
    mock_requests.post.return_value = mock_response

    calcom_tools.reschedule_booking("old-uid", "2026-07-02T10:00:00+00:00", "Need to shift")

    _, kwargs = mock_requests.post.call_args
    assert kwargs["timeout"] == 25


def test_cancel_booking_passes_timeout(calcom_tools, mock_requests):
    """cancel_booking forwards self.timeout to requests.post."""
    calcom_tools.timeout = 18
    mock_response = Mock()
    mock_response.status_code = 200
    mock_requests.post.return_value = mock_response

    calcom_tools.cancel_booking("booking-uid", "No longer needed")

    _, kwargs = mock_requests.post.call_args
    assert kwargs["timeout"] == 18
