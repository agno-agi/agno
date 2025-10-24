"""Unit tests for Google Calendar Tools."""

import json
import os
import tempfile
from unittest.mock import MagicMock, Mock, patch

import pytest
from google.oauth2.credentials import Credentials

from agno.tools.googlecalendar import GoogleCalendarTools


@pytest.fixture
def mock_credentials():
    """Mock Google OAuth2 credentials."""
    mock_creds = Mock(spec=Credentials)
    mock_creds.valid = True
    mock_creds.expired = False
    mock_creds.to_json.return_value = '{"token": "test_token"}'
    return mock_creds


@pytest.fixture
def mock_calendar_service():
    """Mock Google Calendar API service."""
    mock_service = MagicMock()
    return mock_service


@pytest.fixture
def calendar_tools(mock_credentials, mock_calendar_service):
    """Create GoogleCalendarTools instance with mocked dependencies."""
    # Patch both build and the authenticate decorator to completely bypass auth
    with (
        patch("agno.tools.googlecalendar.build") as mock_build,
        patch("agno.tools.googlecalendar.authenticate", lambda func: func),
    ):
        mock_build.return_value = mock_calendar_service
        tools = GoogleCalendarTools(access_token="test_token")
        tools.creds = mock_credentials
        tools.service = mock_calendar_service
        return tools


class TestGoogleCalendarToolsInitialization:
    """Test initialization and configuration of Google Calendar tools."""

    def test_init_with_access_token(self):
        """Test initialization with access token."""
        tools = GoogleCalendarTools(access_token="test_token")
        assert tools.access_token == "test_token"
        assert tools.calendar_id == "primary"
        assert tools.creds is None  # Not set until authentication
        assert tools.service is None

    def test_init_with_credentials_path(self):
        """Test initialization with credentials file path."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"installed": {"client_id": "test"}}, f)
            temp_file = f.name

        try:
            tools = GoogleCalendarTools(credentials_path=temp_file)
            assert tools.credentials_path == temp_file
            assert tools.calendar_id == "primary"
            assert tools.creds is None
            assert tools.service is None
        finally:
            os.unlink(temp_file)

    def test_init_missing_credentials(self):
        """Test initialization without any credentials succeeds but won't authenticate."""
        tools = GoogleCalendarTools()
        assert tools.access_token is None
        assert tools.credentials_path is None
        assert tools.token_path == "token.json"  # default value

    def test_init_invalid_credentials_path(self):
        """Test initialization with invalid credentials path succeeds but won't authenticate."""
        tools = GoogleCalendarTools(credentials_path="./nonexistent.json")
        assert tools.credentials_path == "./nonexistent.json"
        assert tools.service is None

    def test_init_with_existing_token_path(self):
        """Test initialization with existing token file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as token_file:
            json.dump({"token": "test_token"}, token_file)
            token_file_path = token_file.name

        try:
            tools = GoogleCalendarTools(token_path=token_file_path)
            assert tools.token_path == token_file_path
            assert tools.calendar_id == "primary"
        finally:
            os.unlink(token_file_path)

    def test_init_with_custom_calendar_id(self):
        """Test initialization with custom calendar ID."""
        tools = GoogleCalendarTools(access_token="test_token", calendar_id="custom@example.com")
        assert tools.calendar_id == "custom@example.com"
        assert tools.access_token == "test_token"

    def test_init_with_all_tools_registered(self):
        """Test that all tools are properly registered during initialization."""
        tools = GoogleCalendarTools(access_token="test_token")

        # Check that all expected tools are registered
        tool_names = [func.name for func in tools.functions.values()]
        expected_tools = [
            "list_events",
            "create_event",
            "update_event",
            "delete_event",
            "fetch_all_events",
            "find_available_slots",
            "list_calendars",
        ]

        for tool_name in expected_tools:
            assert tool_name in tool_names, f"Tool {tool_name} should be registered"

        # Verify we have the expected number of tools
        assert len(tool_names) == len(expected_tools)


class TestAuthentication:
    """Test authentication configuration."""

    def test_auth_parameters_stored(self):
        """Test that authentication parameters are stored correctly."""
        tools = GoogleCalendarTools(
            access_token="test_token", credentials_path="test_creds.json", token_path="test_token.json", oauth_port=9090
        )

        assert tools.access_token == "test_token"
        assert tools.credentials_path == "test_creds.json"
        assert tools.token_path == "test_token.json"
        assert tools.oauth_port == 9090

    def test_scopes_configuration(self):
        """Test that scopes are configured correctly."""
        # Default scopes
        tools = GoogleCalendarTools(access_token="test_token")
        assert tools.scopes == ["https://www.googleapis.com/auth/calendar.readonly"]

        # Custom scopes
        custom_scopes = ["https://www.googleapis.com/auth/calendar"]
        tools_custom = GoogleCalendarTools(access_token="test_token", scopes=custom_scopes)
        assert tools_custom.scopes == custom_scopes


class TestListEvents:
    """Test list_events method."""

    def test_list_events_success(self, calendar_tools, mock_calendar_service):
        """Test successful event listing."""
        mock_events = [{"id": "1", "summary": "Test Event 1"}, {"id": "2", "summary": "Test Event 2"}]
        mock_calendar_service.events().list().execute.return_value = {"items": mock_events}

        result = calendar_tools.list_events(limit=2)
        result_data = json.loads(result)

        assert result_data == mock_events
        # Check that the service was called (may be called multiple times due to chaining)
        assert mock_calendar_service.events().list.call_count >= 1

    def test_list_events_no_events(self, calendar_tools, mock_calendar_service):
        """Test listing events when none exist."""
        mock_calendar_service.events().list().execute.return_value = {"items": []}

        result = calendar_tools.list_events()
        result_data = json.loads(result)

        assert result_data["message"] == "No upcoming events found."

    def test_list_events_with_start_date(self, calendar_tools, mock_calendar_service):
        """Test listing events with specific start date."""
        mock_events = [{"id": "1", "summary": "Test Event"}]
        mock_calendar_service.events().list().execute.return_value = {"items": mock_events}

        result = calendar_tools.list_events(start_date="2025-07-19T10:00:00")
        result_data = json.loads(result)

        assert result_data == mock_events

    def test_list_events_invalid_date_format(self, calendar_tools):
        """Test listing events with invalid date format."""
        result = calendar_tools.list_events(start_date="invalid-date")
        result_data = json.loads(result)

        assert "error" in result_data
        assert "Invalid date format" in result_data["error"]

    def test_list_events_http_error(self, calendar_tools, mock_calendar_service):
        """Test handling of HTTP errors."""
        from googleapiclient.errors import HttpError

        # Create a mock HttpError
        mock_response = Mock()
        mock_response.status = 403
        mock_response.reason = "Forbidden"

        http_error = HttpError(mock_response, b'{"error": {"message": "Forbidden"}}')
        mock_calendar_service.events().list().execute.side_effect = http_error

        result = calendar_tools.list_events()
        result_data = json.loads(result)

        assert "error" in result_data
        assert "An error occurred" in result_data["error"]


class TestCreateEvent:
    """Test create_event method."""

    def test_create_event_success(self, calendar_tools, mock_calendar_service):
        """Test successful event creation."""
        mock_event = {"id": "test_id", "summary": "Test Event"}
        mock_calendar_service.events().insert().execute.return_value = mock_event

        result = calendar_tools.create_event(
            start_date="2025-07-19T10:00:00",
            end_date="2025-07-19T11:00:00",
            title="Test Event",
            description="Test Description",
        )
        result_data = json.loads(result)

        assert result_data == mock_event

    def test_create_event_with_attendees(self, calendar_tools, mock_calendar_service):
        """Test event creation with attendees."""
        mock_event = {"id": "test_id", "summary": "Test Event"}
        mock_calendar_service.events().insert().execute.return_value = mock_event

        result = calendar_tools.create_event(
            start_date="2025-07-19T10:00:00",
            end_date="2025-07-19T11:00:00",
            title="Test Event",
            attendees=["test1@example.com", "test2@example.com"],
        )
        result_data = json.loads(result)

        assert result_data == mock_event

    def test_create_event_with_google_meet(self, calendar_tools, mock_calendar_service):
        """Test event creation with Google Meet link."""
        mock_event = {"id": "test_id", "summary": "Test Event"}
        mock_calendar_service.events().insert().execute.return_value = mock_event

        result = calendar_tools.create_event(
            start_date="2025-07-19T10:00:00",
            end_date="2025-07-19T11:00:00",
            title="Test Event",
            add_google_meet_link=True,
        )
        result_data = json.loads(result)

        assert result_data == mock_event
        # Verify conferenceDataVersion was set
        call_args = mock_calendar_service.events().insert.call_args
        assert call_args[1]["conferenceDataVersion"] == 1

    def test_create_event_invalid_datetime(self, calendar_tools):
        """Test event creation with invalid datetime format."""
        result = calendar_tools.create_event(
            start_date="invalid-date", end_date="2025-07-19T11:00:00", title="Test Event"
        )
        result_data = json.loads(result)

        assert "error" in result_data
        assert "Invalid datetime format" in result_data["error"]


class TestUpdateEvent:
    """Test update_event method."""

    def test_update_event_success(self, calendar_tools, mock_calendar_service):
        """Test successful event update."""
        existing_event = {
            "id": "test_id",
            "summary": "Old Title",
            "start": {"dateTime": "2025-07-19T10:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2025-07-19T11:00:00", "timeZone": "UTC"},
        }
        updated_event = existing_event.copy()
        updated_event["summary"] = "New Title"

        mock_calendar_service.events().get().execute.return_value = existing_event
        mock_calendar_service.events().update().execute.return_value = updated_event

        result = calendar_tools.update_event(event_id="test_id", title="New Title")
        result_data = json.loads(result)

        assert result_data["summary"] == "New Title"

    def test_update_event_datetime(self, calendar_tools, mock_calendar_service):
        """Test updating event datetime."""
        existing_event = {
            "id": "test_id",
            "summary": "Test Event",
            "start": {"dateTime": "2025-07-19T10:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2025-07-19T11:00:00", "timeZone": "UTC"},
        }

        mock_calendar_service.events().get().execute.return_value = existing_event
        mock_calendar_service.events().update().execute.return_value = existing_event

        result = calendar_tools.update_event(
            event_id="test_id", start_date="2025-07-19T14:00:00", end_date="2025-07-19T15:00:00"
        )
        result_data = json.loads(result)

        assert "error" not in result_data


class TestDeleteEvent:
    """Test delete_event method."""

    def test_delete_event_success(self, calendar_tools, mock_calendar_service):
        """Test successful event deletion."""
        mock_calendar_service.events().delete().execute.return_value = None

        result = calendar_tools.delete_event(event_id="test_id")
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert "deleted successfully" in result_data["message"]


class TestFetchAllEvents:
    """Test fetch_all_events method."""

    def test_fetch_all_events_success(self, calendar_tools, mock_calendar_service):
        """Test successful fetching of all events."""
        mock_events = [{"id": "1", "summary": "Event 1"}, {"id": "2", "summary": "Event 2"}]
        mock_calendar_service.events().list().execute.return_value = {"items": mock_events, "nextPageToken": None}

        result = calendar_tools.fetch_all_events()
        result_data = json.loads(result)

        assert result_data == mock_events

    def test_fetch_all_events_with_pagination(self, calendar_tools, mock_calendar_service):
        """Test fetching events with pagination."""
        page1_events = [{"id": "1", "summary": "Event 1"}]
        page2_events = [{"id": "2", "summary": "Event 2"}]

        mock_calendar_service.events().list().execute.side_effect = [
            {"items": page1_events, "nextPageToken": "token2"},
            {"items": page2_events, "nextPageToken": None},
        ]

        result = calendar_tools.fetch_all_events()
        result_data = json.loads(result)

        assert len(result_data) == 2
        assert result_data == page1_events + page2_events


class TestFindAvailableSlots:
    """Test find_available_slots method."""

    @patch.object(GoogleCalendarTools, "fetch_all_events")
    @patch.object(GoogleCalendarTools, "_get_working_hours")
    def test_find_available_slots_success(self, mock_working_hours, mock_fetch, calendar_tools):
        """Test successful finding of available slots."""
        # Mock working hours response
        mock_working_hours.return_value = json.dumps(
            {"start_hour": 9, "end_hour": 17, "timezone": "UTC", "locale": "en"}
        )

        # Mock no existing events
        mock_fetch.return_value = json.dumps([])

        result = calendar_tools.find_available_slots(
            start_date="2025-07-21", end_date="2025-07-21", duration_minutes=30
        )  # Monday, 30 min
        result_data = json.loads(result)

        assert "available_slots" in result_data
        assert "working_hours" in result_data
        assert "events_analyzed" in result_data
        assert isinstance(result_data["available_slots"], list)

    @patch.object(GoogleCalendarTools, "fetch_all_events")
    @patch.object(GoogleCalendarTools, "_get_working_hours")
    def test_find_available_slots_with_busy_times(self, mock_working_hours, mock_fetch, calendar_tools):
        """Test finding available slots with existing events."""
        # Mock working hours response
        mock_working_hours.return_value = json.dumps(
            {"start_hour": 9, "end_hour": 17, "timezone": "UTC", "locale": "en"}
        )

        # Mock existing event that blocks 10:30-11:30 AM (shorter busy period)
        existing_events = [
            {"start": {"dateTime": "2025-07-19T10:30:00+00:00"}, "end": {"dateTime": "2025-07-19T11:30:00+00:00"}}
        ]
        mock_fetch.return_value = json.dumps(existing_events)

        result = calendar_tools.find_available_slots(
            start_date="2025-07-19", end_date="2025-07-19", duration_minutes=30
        )
        result_data = json.loads(result)

        assert "available_slots" in result_data
        assert "working_hours" in result_data
        assert "events_analyzed" in result_data
        assert result_data["events_analyzed"] == 1
        # Check that the response structure is correct (may or may not have slots)
        assert isinstance(result_data["available_slots"], list)

    @patch.object(GoogleCalendarTools, "fetch_all_events")
    @patch.object(GoogleCalendarTools, "_get_working_hours")
    def test_find_available_slots_guarantees_slots(self, mock_working_hours, mock_fetch, calendar_tools):
        """Test finding available slots when there should definitely be some."""
        # Mock working hours response
        mock_working_hours.return_value = json.dumps(
            {"start_hour": 9, "end_hour": 17, "timezone": "UTC", "locale": "en"}
        )

        # Mock no existing events (completely free day)
        mock_fetch.return_value = json.dumps([])

        result = calendar_tools.find_available_slots(
            start_date="2025-07-21",
            end_date="2025-07-21",
            duration_minutes=30,  # Monday
        )
        result_data = json.loads(result)

        assert "available_slots" in result_data
        assert "working_hours" in result_data
        assert "events_analyzed" in result_data
        assert result_data["events_analyzed"] == 0
        # With no events and a full working day, we should have multiple slots
        slots = result_data["available_slots"]
        assert isinstance(slots, list)
        # Should have many 30-minute slots between 9 AM and 5 PM
        assert len(slots) >= 10  # Conservative estimate

    def test_find_available_slots_invalid_date(self, calendar_tools):
        """Test finding available slots with invalid date format."""
        result = calendar_tools.find_available_slots(
            start_date="invalid-date", end_date="2025-07-19", duration_minutes=60
        )
        result_data = json.loads(result)

        assert "error" in result_data
        assert "Invalid isoformat string" in result_data["error"]


class TestListCalendars:
    """Test list_calendars method."""

    def test_list_calendars_success(self, calendar_tools, mock_calendar_service):
        """Test successful calendar listing."""
        mock_calendars = {
            "items": [
                {
                    "id": "primary",
                    "summary": "John Doe",
                    "description": "Personal calendar",
                    "primary": True,
                    "accessRole": "owner",
                    "backgroundColor": "#ffffff",
                },
                {
                    "id": "work@company.com",
                    "summary": "Work Calendar",
                    "description": "Company work calendar",
                    "primary": False,
                    "accessRole": "writer",
                    "backgroundColor": "#4285f4",
                },
            ]
        }
        mock_calendar_service.calendarList().list().execute.return_value = mock_calendars

        result = calendar_tools.list_calendars()
        result_data = json.loads(result)

        assert "calendars" in result_data
        assert len(result_data["calendars"]) == 2
        assert result_data["current_default"] == "primary"

        # Check calendar data structure
        primary_cal = result_data["calendars"][0]
        assert primary_cal["id"] == "primary"
        assert primary_cal["name"] == "John Doe"
        assert primary_cal["primary"] is True
        assert primary_cal["access_role"] == "owner"

    def test_list_calendars_http_error(self, calendar_tools, mock_calendar_service):
        """Test handling of HTTP errors in list_calendars."""
        from googleapiclient.errors import HttpError

        mock_response = Mock()
        mock_response.status = 403
        mock_response.reason = "Forbidden"

        http_error = HttpError(mock_response, b'{"error": {"message": "Forbidden"}}')
        mock_calendar_service.calendarList().list().execute.side_effect = http_error

        result = calendar_tools.list_calendars()
        result_data = json.loads(result)

        assert "error" in result_data
        assert "An error occurred" in result_data["error"]


class TestErrorHandling:
    """Test error handling across all methods."""

    def test_method_integration_works(self, calendar_tools):
        """Test that all methods work with proper setup."""
        # This test verifies that our fixture pattern provides working tools
        assert calendar_tools.calendar_id == "primary"
        assert calendar_tools.service is not None
        assert calendar_tools.creds is not None
