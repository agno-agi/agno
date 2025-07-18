"""Unit tests for Google Calendar Tools."""

import json
import os
import tempfile
from unittest.mock import Mock, mock_open, patch

import pytest

from agno.tools.googlecalendar import GoogleCalendarTokenTools, GoogleCalendarTools


class TestGoogleCalendarToolsInitialization:
    """Test initialization and configuration of Google Calendar tools."""

    def test_init_with_access_token(self):
        """Test initialization with access token."""
        tools = GoogleCalendarTools(access_token="test_token")
        assert tools.access_token == "test_token"
        assert tools.creds is not None
        assert tools.service is None

    def test_init_with_credentials_path(self):
        """Test initialization with credentials file path."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"installed": {"client_id": "test"}}, f)
            temp_file = f.name

        try:
            tools = GoogleCalendarTools(credentials_path=temp_file, token_path="./test_token.json")
            assert tools.credentials_path == temp_file
            assert tools.token_path == "./test_token.json"
            assert tools.creds is None
            assert tools.service is None
        finally:
            os.unlink(temp_file)

    def test_init_missing_credentials(self):
        """Test initialization without any credentials raises error."""
        with pytest.raises(ValueError, match="Either credentials path or access token is required"):
            GoogleCalendarTools()

    def test_init_invalid_credentials_path(self):
        """Test initialization with invalid credentials path raises error."""
        with pytest.raises(ValueError, match="Credentials Path is invalid"):
            GoogleCalendarTools(credentials_path="./nonexistent.json")

    def test_init_with_default_token_path(self):
        """Test initialization uses default token path when not provided."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"installed": {"client_id": "test"}}, f)
            temp_file = f.name

        try:
            with patch("agno.tools.googlecalendar.logger") as mock_logger:
                tools = GoogleCalendarTools(credentials_path=temp_file)
                assert tools.token_path == "token.json"
                mock_logger.warning.assert_called_once()
        finally:
            os.unlink(temp_file)

    def test_init_with_tool_flags(self):
        """Test initialization with specific tool flags."""
        tools = GoogleCalendarTools(
            access_token="test_token",
            list_events=False,
            create_event=True,
            update_event=False,
            delete_event=True,
            fetch_all_events=False,
            find_available_slots=True,
        )

        # Check that only enabled tools are registered
        tool_names = [func.name for func in tools.functions.values()]
        assert "create_event" in tool_names
        assert "delete_event" in tool_names
        assert "find_available_slots" in tool_names
        assert "list_events" not in tool_names
        assert "update_event" not in tool_names
        assert "fetch_all_events" not in tool_names


class TestGoogleCalendarTokenTools:
    """Test the token-based authentication class."""

    def test_token_tools_inheritance(self):
        """Test GoogleCalendarTokenTools inherits from GoogleCalendarTools."""
        tools = GoogleCalendarTokenTools(access_token="test_token")
        assert isinstance(tools, GoogleCalendarTools)
        assert tools.access_token == "test_token"


class TestAuthentication:
    """Test authentication methods."""

    @patch("agno.tools.googlecalendar.Credentials")
    @patch("agno.tools.googlecalendar.build")
    def test_auth_with_token(self, mock_build, mock_credentials):
        """Test authentication with access token."""
        mock_service = Mock()
        mock_build.return_value = mock_service

        tools = GoogleCalendarTools(access_token="test_token")
        tools._auth()

        # Token-based auth should return early
        assert tools.service is None

    @patch("agno.tools.googlecalendar.os.path.exists")
    @patch("agno.tools.googlecalendar.Credentials.from_authorized_user_file")
    @patch("agno.tools.googlecalendar.build")
    def test_auth_with_existing_token_file(self, mock_build, mock_from_file, mock_exists):
        """Test authentication with existing token file."""
        mock_exists.return_value = True
        mock_creds = Mock()
        mock_creds.valid = True
        mock_from_file.return_value = mock_creds
        mock_service = Mock()
        mock_build.return_value = mock_service

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"installed": {"client_id": "test"}}, f)
            temp_file = f.name

        try:
            tools = GoogleCalendarTools(credentials_path=temp_file, token_path="./test_token.json")
            tools._auth()

            mock_from_file.assert_called_once_with("./test_token.json", ["https://www.googleapis.com/auth/calendar"])
            assert tools.creds == mock_creds
        finally:
            os.unlink(temp_file)

    @patch("agno.tools.googlecalendar.InstalledAppFlow.from_client_secrets_file")
    @patch("builtins.open", new_callable=mock_open)
    def test_auth_with_oauth_flow(self, mock_file, mock_flow):
        """Test authentication with OAuth flow."""
        mock_flow_instance = Mock()
        mock_creds = Mock()
        mock_creds.valid = True
        mock_creds.to_json.return_value = '{"token": "test"}'
        mock_flow_instance.run_local_server.return_value = mock_creds
        mock_flow.return_value = mock_flow_instance

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"installed": {"client_id": "test"}}, f)
            temp_file = f.name

        try:
            tools = GoogleCalendarTools(credentials_path=temp_file, token_path="./test_token.json")
            tools.creds = None  # Simulate no existing credentials
            tools._auth()

            mock_flow.assert_called_once()
            mock_flow_instance.run_local_server.assert_called_once()
            assert tools.creds == mock_creds
        finally:
            os.unlink(temp_file)


class TestListEvents:
    """Test list_events method."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("agno.tools.googlecalendar.build"):
            self.tools = GoogleCalendarTools(access_token="test_token")
            self.mock_service = Mock()
            self.tools.service = self.mock_service

    def test_list_events_success(self):
        """Test successful event listing."""
        mock_events = [{"id": "1", "summary": "Test Event 1"}, {"id": "2", "summary": "Test Event 2"}]
        self.mock_service.events().list().execute.return_value = {"items": mock_events}

        result = self.tools.list_events(limit=2)
        result_data = json.loads(result)

        assert result_data == mock_events
        # Check that the service was called (may be called multiple times due to chaining)
        assert self.mock_service.events().list.call_count >= 1

    def test_list_events_no_events(self):
        """Test listing events when none exist."""
        self.mock_service.events().list().execute.return_value = {"items": []}

        result = self.tools.list_events()
        result_data = json.loads(result)

        assert result_data["message"] == "No upcoming events found."

    def test_list_events_with_date_from(self):
        """Test listing events with specific start date."""
        mock_events = [{"id": "1", "summary": "Test Event"}]
        self.mock_service.events().list().execute.return_value = {"items": mock_events}

        result = self.tools.list_events(date_from="2025-07-19T10:00:00")
        result_data = json.loads(result)

        assert result_data == mock_events

    def test_list_events_invalid_date_format(self):
        """Test listing events with invalid date format."""
        result = self.tools.list_events(date_from="invalid-date")
        result_data = json.loads(result)

        assert "error" in result_data
        assert "Invalid date format" in result_data["error"]

    def test_list_events_http_error(self):
        """Test handling of HTTP errors."""
        from googleapiclient.errors import HttpError

        # Create a mock HttpError
        mock_response = Mock()
        mock_response.status = 403
        mock_response.reason = "Forbidden"

        http_error = HttpError(mock_response, b'{"error": {"message": "Forbidden"}}')
        self.mock_service.events().list().execute.side_effect = http_error

        result = self.tools.list_events()
        result_data = json.loads(result)

        assert "error" in result_data
        assert "An error occurred" in result_data["error"]

    def test_list_events_no_service(self):
        """Test list_events when service is not initialized."""
        # Create tools instance and mock the build to return None
        with patch("agno.tools.googlecalendar.build", return_value=None):
            tools = GoogleCalendarTools(access_token="test_token")

            # Make sure service stays None
            tools.service = None

            result = tools.list_events()
            result_data = json.loads(result)

            assert result_data["error"] == "Google Calendar service not initialized"


class TestCreateEvent:
    """Test create_event method."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("agno.tools.googlecalendar.build"):
            self.tools = GoogleCalendarTools(access_token="test_token")
            self.mock_service = Mock()
            self.tools.service = self.mock_service

    def test_create_event_success(self):
        """Test successful event creation."""
        mock_event = {"id": "test_id", "summary": "Test Event"}
        self.mock_service.events().insert().execute.return_value = mock_event

        result = self.tools.create_event(
            start_datetime="2025-07-19T10:00:00",
            end_datetime="2025-07-19T11:00:00",
            title="Test Event",
            description="Test Description",
        )
        result_data = json.loads(result)

        assert result_data == mock_event

    def test_create_event_with_attendees(self):
        """Test event creation with attendees."""
        mock_event = {"id": "test_id", "summary": "Test Event"}
        self.mock_service.events().insert().execute.return_value = mock_event

        result = self.tools.create_event(
            start_datetime="2025-07-19T10:00:00",
            end_datetime="2025-07-19T11:00:00",
            title="Test Event",
            attendees=["test1@example.com", "test2@example.com"],
        )
        result_data = json.loads(result)

        assert result_data == mock_event

    def test_create_event_with_google_meet(self):
        """Test event creation with Google Meet link."""
        mock_event = {"id": "test_id", "summary": "Test Event"}
        self.mock_service.events().insert().execute.return_value = mock_event

        result = self.tools.create_event(
            start_datetime="2025-07-19T10:00:00",
            end_datetime="2025-07-19T11:00:00",
            title="Test Event",
            add_google_meet_link=True,
        )
        result_data = json.loads(result)

        assert result_data == mock_event
        # Verify conferenceDataVersion was set
        call_args = self.mock_service.events().insert.call_args
        assert call_args[1]["conferenceDataVersion"] == 1

    def test_create_event_invalid_datetime(self):
        """Test event creation with invalid datetime format."""
        result = self.tools.create_event(
            start_datetime="invalid-date", end_datetime="2025-07-19T11:00:00", title="Test Event"
        )
        result_data = json.loads(result)

        assert "error" in result_data
        assert "Invalid datetime format" in result_data["error"]


class TestUpdateEvent:
    """Test update_event method."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("agno.tools.googlecalendar.build"):
            self.tools = GoogleCalendarTools(access_token="test_token")
            self.mock_service = Mock()
            self.tools.service = self.mock_service

    def test_update_event_success(self):
        """Test successful event update."""
        existing_event = {
            "id": "test_id",
            "summary": "Old Title",
            "start": {"dateTime": "2025-07-19T10:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2025-07-19T11:00:00", "timeZone": "UTC"},
        }
        updated_event = existing_event.copy()
        updated_event["summary"] = "New Title"

        self.mock_service.events().get().execute.return_value = existing_event
        self.mock_service.events().update().execute.return_value = updated_event

        result = self.tools.update_event(event_id="test_id", title="New Title")
        result_data = json.loads(result)

        assert result_data["summary"] == "New Title"

    def test_update_event_datetime(self):
        """Test updating event datetime."""
        existing_event = {
            "id": "test_id",
            "summary": "Test Event",
            "start": {"dateTime": "2025-07-19T10:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2025-07-19T11:00:00", "timeZone": "UTC"},
        }

        self.mock_service.events().get().execute.return_value = existing_event
        self.mock_service.events().update().execute.return_value = existing_event

        result = self.tools.update_event(
            event_id="test_id", start_datetime="2025-07-19T14:00:00", end_datetime="2025-07-19T15:00:00"
        )
        result_data = json.loads(result)

        assert "error" not in result_data


class TestDeleteEvent:
    """Test delete_event method."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("agno.tools.googlecalendar.build"):
            self.tools = GoogleCalendarTools(access_token="test_token")
            self.mock_service = Mock()
            self.tools.service = self.mock_service

    def test_delete_event_success(self):
        """Test successful event deletion."""
        self.mock_service.events().delete().execute.return_value = None

        result = self.tools.delete_event(event_id="test_id")
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert "deleted successfully" in result_data["message"]


class TestFetchAllEvents:
    """Test fetch_all_events method."""

    def setup_method(self):
        """Set up test fixtures."""
        with patch("agno.tools.googlecalendar.build"):
            self.tools = GoogleCalendarTools(access_token="test_token")
            self.mock_service = Mock()
            self.tools.service = self.mock_service

    def test_fetch_all_events_success(self):
        """Test successful fetching of all events."""
        mock_events = [{"id": "1", "summary": "Event 1"}, {"id": "2", "summary": "Event 2"}]
        self.mock_service.events().list().execute.return_value = {"items": mock_events, "nextPageToken": None}

        result = self.tools.fetch_all_events()
        result_data = json.loads(result)

        assert result_data == mock_events

    def test_fetch_all_events_with_pagination(self):
        """Test fetching events with pagination."""
        page1_events = [{"id": "1", "summary": "Event 1"}]
        page2_events = [{"id": "2", "summary": "Event 2"}]

        self.mock_service.events().list().execute.side_effect = [
            {"items": page1_events, "nextPageToken": "token2"},
            {"items": page2_events, "nextPageToken": None},
        ]

        result = self.tools.fetch_all_events()
        result_data = json.loads(result)

        assert len(result_data) == 2
        assert result_data == page1_events + page2_events


class TestFindAvailableSlots:
    """Test find_available_slots method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.tools = GoogleCalendarTools(access_token="test_token")
        self.mock_service = Mock()
        self.tools.service = self.mock_service

    @patch.object(GoogleCalendarTools, "fetch_all_events")
    def test_find_available_slots_success(self, mock_fetch):
        """Test successful finding of available slots."""
        # Mock no existing events
        mock_fetch.return_value = json.dumps([])

        result = self.tools.find_available_slots(start_date="2025-07-19", end_date="2025-07-19", duration_minutes=60)
        result_data = json.loads(result)

        assert "available_slots" in result_data
        assert isinstance(result_data["available_slots"], list)

    @patch.object(GoogleCalendarTools, "fetch_all_events")
    def test_find_available_slots_with_busy_times(self, mock_fetch):
        """Test finding available slots with existing events."""
        # Mock existing event that blocks 10-11 AM
        existing_events = [
            {"start": {"dateTime": "2025-07-19T10:00:00+00:00"}, "end": {"dateTime": "2025-07-19T11:00:00+00:00"}}
        ]
        mock_fetch.return_value = json.dumps(existing_events)

        result = self.tools.find_available_slots(
            start_date="2025-07-19", end_date="2025-07-19", duration_minutes=60, start_hour=9, end_hour=17
        )
        result_data = json.loads(result)

        assert "available_slots" in result_data
        # Should have slots before 10 AM and after 11 AM
        slots = result_data["available_slots"]
        assert len(slots) > 0

    def test_find_available_slots_invalid_date(self):
        """Test finding available slots with invalid date format."""
        result = self.tools.find_available_slots(start_date="invalid-date", end_date="2025-07-19", duration_minutes=60)
        result_data = json.loads(result)

        assert "error" in result_data
        assert "Invalid date format" in result_data["error"]


class TestErrorHandling:
    """Test error handling across all methods."""

    def test_methods_without_service_initialization(self):
        """Test that all methods handle missing service gracefully."""
        # Mock build to return None so service stays None
        with patch("agno.tools.googlecalendar.build", return_value=None):
            tools = GoogleCalendarTools(access_token="test_token")
            tools.service = None

            methods_to_test = [
                ("list_events", []),
                ("create_event", ["2025-07-19T10:00:00", "2025-07-19T11:00:00"]),
                ("update_event", ["test_id"]),
                ("delete_event", ["test_id"]),
                ("fetch_all_events", []),
            ]

            for method_name, args in methods_to_test:
                method = getattr(tools, method_name)
                result = method(*args)
                result_data = json.loads(result)

                assert "error" in result_data
                assert "not initialized" in result_data["error"]
