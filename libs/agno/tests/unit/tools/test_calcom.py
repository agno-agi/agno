"""Unit tests for CalComTools class."""

from unittest.mock import Mock, patch

from agno.tools.calcom import CalComTools


def _mock_response(status_code=200, data=None, text="OK"):
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.json.return_value = data or {}
    return response


def test_init_uses_default_timeout():
    tools = CalComTools(api_key="test_api_key", event_type_id=123)

    assert tools.timeout == 30


def test_get_available_slots_uses_configured_timeout():
    tools = CalComTools(api_key="test_api_key", event_type_id=123, timeout=7)
    response = _mock_response(data={"data": {"slots": {"2026-01-01": [{"time": "2026-01-01T15:00:00Z"}]}}})

    with patch("agno.tools.calcom.requests.get", return_value=response) as mock_get:
        result = tools.get_available_slots("2026-01-01", "2026-01-02")

    assert "Available slots" in result
    mock_get.assert_called_once()
    assert mock_get.call_args.kwargs["timeout"] == 7


def test_create_booking_uses_configured_timeout():
    tools = CalComTools(api_key="test_api_key", event_type_id=123, timeout=7)
    response = _mock_response(status_code=201, data={"data": {"start": "2026-01-01T15:00:00Z", "uid": "abc123"}})

    with patch("agno.tools.calcom.requests.post", return_value=response) as mock_post:
        result = tools.create_booking("2026-01-01T15:00:00+00:00", "Ada", "ada@example.com")

    assert "Booking created successfully" in result
    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs["timeout"] == 7


def test_get_upcoming_bookings_uses_configured_timeout():
    tools = CalComTools(api_key="test_api_key", event_type_id=123, timeout=7)
    response = _mock_response(data={"data": []})

    with patch("agno.tools.calcom.requests.get", return_value=response) as mock_get:
        result = tools.get_upcoming_bookings("ada@example.com")

    assert result == "No upcoming bookings found."
    mock_get.assert_called_once()
    assert mock_get.call_args.kwargs["timeout"] == 7


def test_reschedule_booking_uses_configured_timeout():
    tools = CalComTools(api_key="test_api_key", event_type_id=123, timeout=7)
    response = _mock_response(status_code=201, data={"data": {"start": "2026-01-01T16:00:00Z", "uid": "def456"}})

    with patch("agno.tools.calcom.requests.post", return_value=response) as mock_post:
        result = tools.reschedule_booking("abc123", "2026-01-01T16:00:00+00:00", "Need a later slot")

    assert "Booking rescheduled" in result
    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs["timeout"] == 7


def test_cancel_booking_uses_configured_timeout():
    tools = CalComTools(api_key="test_api_key", event_type_id=123, timeout=7)
    response = _mock_response()

    with patch("agno.tools.calcom.requests.post", return_value=response) as mock_post:
        result = tools.cancel_booking("abc123", "Plans changed")

    assert result == "Booking cancelled successfully."
    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs["timeout"] == 7
