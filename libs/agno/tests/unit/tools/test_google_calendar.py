"""Unit tests for Google Calendar Tools."""

import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch
from zoneinfo import ZoneInfoNotFoundError

import pytest
from google.oauth2.credentials import Credentials

from agno.tools.google.calendar import GoogleCalendarTools


@pytest.fixture
def mock_credentials():
    mock_creds = Mock(spec=Credentials)
    mock_creds.valid = True
    mock_creds.expired = False
    mock_creds.to_json.return_value = '{"token": "test_token"}'
    return mock_creds


@pytest.fixture
def mock_calendar_service():
    mock_service = MagicMock()
    return mock_service


@pytest.fixture
def calendar_tools(mock_credentials, mock_calendar_service):
    with (
        patch("googleapiclient.discovery.build") as mock_build,
        patch("agno.tools.google.calendar.authenticate", lambda func: func),
    ):
        mock_build.return_value = mock_calendar_service
        tools = GoogleCalendarTools(creds=mock_credentials)
        tools._service = mock_calendar_service
        return tools


@pytest.fixture
def calendar_tools_all(mock_credentials, mock_calendar_service):
    """Instance with ALL tools enabled including write tools."""
    with (
        patch("googleapiclient.discovery.build") as mock_build,
        patch("agno.tools.google.calendar.authenticate", lambda func: func),
    ):
        mock_build.return_value = mock_calendar_service
        tools = GoogleCalendarTools(
            creds=mock_credentials,
            quick_add_event=True,
            move_event=True,
            respond_to_event=True,
        )
        tools._service = mock_calendar_service
        return tools


class TestGoogleCalendarToolsInitialization:
    def test_init_defaults(self):
        tools = GoogleCalendarTools()
        assert tools.calendar_id == "primary"
        assert tools.creds is None
        assert tools.service is None

    def test_init_with_credentials_path(self):
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

    def test_init_with_custom_calendar_id(self):
        tools = GoogleCalendarTools(calendar_id="custom@example.com")
        assert tools.calendar_id == "custom@example.com"

    def test_init_default_tools_registered(self):
        tools = GoogleCalendarTools()
        tool_names = [func.name for func in tools.functions.values()]
        expected_defaults = [
            "list_events",
            "get_event",
            "create_event",
            "update_event",
            "delete_event",
            "fetch_all_events",
            "find_available_slots",
            "list_calendars",
            "check_availability",
            "get_event_attendees",
            "search_events",
        ]
        for name in expected_defaults:
            assert name in tool_names, f"{name} should be registered by default"
        # These should NOT be registered by default
        assert "quick_add_event" not in tool_names
        assert "move_event" not in tool_names
        assert "respond_to_event" not in tool_names

    def test_init_all_tools_registered(self):
        tools = GoogleCalendarTools(
            quick_add_event=True,
            move_event=True,
            respond_to_event=True,
        )
        tool_names = [func.name for func in tools.functions.values()]
        assert len(tool_names) == 14

    def test_init_selective_tools(self):
        tools = GoogleCalendarTools(
            list_events=True,
            get_event=True,
            create_event=False,
            update_event=False,
            delete_event=False,
            fetch_all_events=False,
            find_available_slots=False,
            list_calendars=False,
            check_availability=False,
            get_event_attendees=False,
            search_events=False,
        )
        tool_names = [func.name for func in tools.functions.values()]
        assert tool_names == ["list_events", "get_event"]

    def test_init_include_tools_pattern(self):
        tools = GoogleCalendarTools(include_tools=["list_events", "get_event"])
        tool_names = [func.name for func in tools.functions.values()]
        assert "list_events" in tool_names
        assert "get_event" in tool_names

    def test_init_service_account_params(self):
        tools = GoogleCalendarTools(
            service_account_path="/path/to/key.json",
            delegated_user="user@example.com",
        )
        assert tools._auth.service_account_path == "/path/to/key.json"
        assert tools._auth.delegated_user == "user@example.com"

    def test_init_login_hint(self):
        tools = GoogleCalendarTools(login_hint="user@example.com")
        assert tools._auth.login_hint == "user@example.com"


class TestBackwardCompat:
    def test_oauth_port_stored(self):
        tools = GoogleCalendarTools(oauth_port=9090)
        assert tools.oauth_port == 9090

    def test_oauth_port_default(self):
        tools = GoogleCalendarTools()
        assert tools.oauth_port == 8080

    def test_allow_update_enables_write_tools(self):
        tools = GoogleCalendarTools(
            allow_update=True,
            create_event=False,
            update_event=False,
            delete_event=False,
        )
        tool_names = [func.name for func in tools.functions.values()]
        assert "create_event" in tool_names
        assert "update_event" in tool_names
        assert "delete_event" in tool_names


class TestScopeValidation:
    def test_default_scopes(self):
        tools = GoogleCalendarTools()
        assert tools.scopes == GoogleCalendarTools.default_scopes

    def test_read_only_tools_get_default_scopes(self):
        tools = GoogleCalendarTools(
            create_event=False,
            update_event=False,
            delete_event=False,
        )
        assert tools.scopes == GoogleCalendarTools.default_scopes

    def test_custom_scopes_write_validated(self):
        with pytest.raises(ValueError, match="required for write operations"):
            GoogleCalendarTools(
                scopes=["https://www.googleapis.com/auth/calendar.readonly"],
                create_event=True,
            )

    def test_custom_scopes_read_validated(self):
        with pytest.raises(ValueError, match="required for read operations"):
            GoogleCalendarTools(
                scopes=["https://www.googleapis.com/auth/calendar.events"],
                list_events=True,
                create_event=False,
                update_event=False,
                delete_event=False,
            )

    def test_custom_write_scope_covers_reads(self):
        tools = GoogleCalendarTools(
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        assert tools.scopes == ["https://www.googleapis.com/auth/calendar"]


class TestAuthentication:
    def test_auth_parameters_stored(self):
        tools = GoogleCalendarTools(
            credentials_path="test_creds.json",
            token_path="test_token.json",
            oauth_port=9090,
        )
        assert tools.credentials_path == "test_creds.json"
        assert tools.token_path == "test_token.json"
        assert tools.oauth_port == 9090

    def test_scopes_configuration(self):
        custom_scopes = ["https://www.googleapis.com/auth/calendar"]
        tools = GoogleCalendarTools(scopes=custom_scopes)
        assert tools.scopes == custom_scopes


class TestListEvents:
    def test_list_events_success(self, calendar_tools, mock_calendar_service):
        mock_events = [{"id": "1", "summary": "Test Event 1"}, {"id": "2", "summary": "Test Event 2"}]
        mock_calendar_service.events().list().execute.return_value = {"items": mock_events}

        result = calendar_tools.list_events(limit=2)
        result_data = json.loads(result)
        assert result_data["events"] == mock_events

    def test_list_events_no_events(self, calendar_tools, mock_calendar_service):
        mock_calendar_service.events().list().execute.return_value = {"items": []}
        result = calendar_tools.list_events()
        result_data = json.loads(result)
        assert result_data["message"] == "No upcoming events found."

    def test_list_events_with_start_date(self, calendar_tools, mock_calendar_service):
        mock_events = [{"id": "1", "summary": "Test Event"}]
        mock_calendar_service.events().list().execute.return_value = {"items": mock_events}
        result = calendar_tools.list_events(start_date="2025-07-19T10:00:00")
        assert json.loads(result)["events"] == mock_events
        assert mock_calendar_service.events().list.call_args.kwargs["timeMin"] == "2025-07-19T10:00:00.000000Z"

    def test_list_events_with_timezone_aware_start_date(self, calendar_tools, mock_calendar_service):
        mock_events = [{"id": "1", "summary": "Test Event"}]
        mock_calendar_service.events().list().execute.return_value = {"items": mock_events}
        result = calendar_tools.list_events(start_date="2026-07-01T10:00:00+02:00")
        assert json.loads(result)["events"] == mock_events
        assert mock_calendar_service.events().list.call_args.kwargs["timeMin"] == "2026-07-01T08:00:00.000000Z"

    def test_list_events_invalid_date_format(self, calendar_tools):
        result = calendar_tools.list_events(start_date="invalid-date")
        assert "error" in json.loads(result)

    def test_list_events_http_error(self, calendar_tools, mock_calendar_service):
        from googleapiclient.errors import HttpError

        mock_response = Mock()
        mock_response.status = 403
        mock_response.reason = "Forbidden"
        mock_calendar_service.events().list().execute.side_effect = HttpError(
            mock_response, b'{"error": {"message": "Forbidden"}}'
        )
        result = calendar_tools.list_events()
        assert "error" in json.loads(result)


class TestGetEvent:
    def test_get_event_success(self, calendar_tools, mock_calendar_service):
        mock_event = {"id": "test_id", "summary": "Test Event", "start": {"dateTime": "2025-07-19T10:00:00"}}
        mock_calendar_service.events().get().execute.return_value = mock_event

        result = calendar_tools.get_event(event_id="test_id")
        assert json.loads(result) == mock_event

    def test_get_event_not_found(self, calendar_tools, mock_calendar_service):
        from googleapiclient.errors import HttpError

        mock_response = Mock()
        mock_response.status = 404
        mock_response.reason = "Not Found"
        mock_calendar_service.events().get().execute.side_effect = HttpError(
            mock_response, b'{"error": {"message": "Not Found"}}'
        )
        result = calendar_tools.get_event(event_id="nonexistent")
        assert "error" in json.loads(result)


class TestCreateEvent:
    def test_create_event_success(self, calendar_tools, mock_calendar_service):
        mock_event = {"id": "test_id", "summary": "Test Event"}
        mock_calendar_service.events().insert().execute.return_value = mock_event

        result = calendar_tools.create_event(
            start_date="2025-07-19T10:00:00",
            end_date="2025-07-19T11:00:00",
            title="Test Event",
        )
        assert json.loads(result) == mock_event

    def test_create_event_with_attendees(self, calendar_tools, mock_calendar_service):
        mock_event = {"id": "test_id", "summary": "Test Event"}
        mock_calendar_service.events().insert().execute.return_value = mock_event

        result = calendar_tools.create_event(
            start_date="2025-07-19T10:00:00",
            end_date="2025-07-19T11:00:00",
            title="Test Event",
            attendees=["test1@example.com", "test2@example.com"],
        )
        assert json.loads(result) == mock_event

    def test_create_event_with_google_meet(self, calendar_tools, mock_calendar_service):
        mock_event = {"id": "test_id", "summary": "Test Event"}
        mock_calendar_service.events().insert().execute.return_value = mock_event

        result = calendar_tools.create_event(
            start_date="2025-07-19T10:00:00",
            end_date="2025-07-19T11:00:00",
            title="Test Event",
            add_google_meet_link=True,
        )
        assert json.loads(result) == mock_event
        call_args = mock_calendar_service.events().insert.call_args
        assert call_args[1]["conferenceDataVersion"] == 1

    def test_create_event_invalid_datetime(self, calendar_tools):
        result = calendar_tools.create_event(
            start_date="invalid-date", end_date="2025-07-19T11:00:00", title="Test Event"
        )
        assert "error" in json.loads(result)

    def test_create_event_timezone_aware_preserves_offset(self, calendar_tools, mock_calendar_service):
        mock_calendar_service.events().insert().execute.return_value = {"id": "test_id"}
        calendar_tools.create_event(
            start_date="2026-07-01T10:00:00+02:00",
            end_date="2026-07-01T11:00:00+02:00",
            title="Test Event",
            timezone="UTC",
        )
        body = mock_calendar_service.events().insert.call_args.kwargs["body"]
        assert body["start"]["dateTime"] == "2026-07-01T10:00:00+02:00"
        assert body["end"]["dateTime"] == "2026-07-01T11:00:00+02:00"

    def test_create_event_naive_datetime_left_for_timezone(self, calendar_tools, mock_calendar_service):
        mock_calendar_service.events().insert().execute.return_value = {"id": "test_id"}
        calendar_tools.create_event(
            start_date="2026-07-01T10:00:00",
            end_date="2026-07-01T11:00:00",
            title="Test Event",
            timezone="America/New_York",
        )
        body = mock_calendar_service.events().insert.call_args.kwargs["body"]
        assert body["start"] == {"dateTime": "2026-07-01T10:00:00", "timeZone": "America/New_York"}


class TestUpdateEvent:
    def test_update_event_success(self, calendar_tools, mock_calendar_service):
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
        assert json.loads(result)["summary"] == "New Title"

    def test_update_event_datetime(self, calendar_tools, mock_calendar_service):
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
        assert "error" not in json.loads(result)

    def test_update_event_timezone_aware_preserves_offset(self, calendar_tools, mock_calendar_service):
        existing_event = {
            "id": "test_id",
            "summary": "Test Event",
            "start": {"dateTime": "2025-07-19T10:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2025-07-19T11:00:00", "timeZone": "UTC"},
        }
        mock_calendar_service.events().get().execute.return_value = existing_event
        mock_calendar_service.events().update().execute.return_value = existing_event

        calendar_tools.update_event(
            event_id="test_id", start_date="2026-07-01T10:00:00+02:00", end_date="2026-07-01T11:00:00+02:00"
        )
        body = mock_calendar_service.events().update.call_args.kwargs["body"]
        assert body["start"]["dateTime"] == "2026-07-01T10:00:00+02:00"
        assert body["end"]["dateTime"] == "2026-07-01T11:00:00+02:00"

    def test_update_event_naive_datetime_left_for_timezone(self, calendar_tools, mock_calendar_service):
        existing_event = {
            "id": "test_id",
            "summary": "Test Event",
            "start": {"dateTime": "2025-07-19T10:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2025-07-19T11:00:00", "timeZone": "UTC"},
        }
        mock_calendar_service.events().get().execute.return_value = existing_event
        mock_calendar_service.events().update().execute.return_value = existing_event

        calendar_tools.update_event(
            event_id="test_id",
            start_date="2026-07-01T10:00:00",
            end_date="2026-07-01T11:00:00",
            timezone="America/New_York",
        )
        body = mock_calendar_service.events().update.call_args.kwargs["body"]
        assert body["start"] == {"dateTime": "2026-07-01T10:00:00", "timeZone": "America/New_York"}
        assert body["end"] == {"dateTime": "2026-07-01T11:00:00", "timeZone": "America/New_York"}


class TestDeleteEvent:
    def test_delete_event_success(self, calendar_tools, mock_calendar_service):
        mock_calendar_service.events().delete().execute.return_value = None

        result = calendar_tools.delete_event(event_id="test_id")
        result_data = json.loads(result)
        assert result_data["success"] is True
        assert "deleted successfully" in result_data["message"]


class TestFetchAllEvents:
    def test_fetch_all_events_success(self, calendar_tools, mock_calendar_service):
        mock_events = [{"id": "1", "summary": "Event 1"}, {"id": "2", "summary": "Event 2"}]
        mock_calendar_service.events().list().execute.return_value = {"items": mock_events, "nextPageToken": None}

        result = calendar_tools.fetch_all_events()
        assert json.loads(result) == mock_events

    def test_fetch_all_events_with_pagination(self, calendar_tools, mock_calendar_service):
        page1 = [{"id": "1", "summary": "Event 1"}]
        page2 = [{"id": "2", "summary": "Event 2"}]

        mock_calendar_service.events().list().execute.side_effect = [
            {"items": page1, "nextPageToken": "token2"},
            {"items": page2, "nextPageToken": None},
        ]

        result = calendar_tools.fetch_all_events()
        result_data = json.loads(result)
        assert len(result_data) == 2


class TestFindAvailableSlots:
    @pytest.mark.parametrize(
        ("duration_minutes", "end_hour", "expected_last_end", "expected_count"),
        [
            (30, 17, "17:00:00", 16),
            (45, 17, "16:45:00", 15),
            (60, 17, "17:00:00", 15),
            (480, 17, "17:00:00", 1),
            (481, 17, None, 0),
            (1500, 17, None, 0),
            (45, 18, "17:45:00", 17),
        ],
    )
    @patch.object(GoogleCalendarTools, "fetch_all_events")
    @patch.object(GoogleCalendarTools, "_get_working_hours")
    def test_available_slots_end_within_working_hours(
        self,
        mock_working_hours,
        mock_fetch,
        calendar_tools,
        duration_minutes,
        end_hour,
        expected_last_end,
        expected_count,
    ):
        mock_working_hours.return_value = json.dumps(
            {"start_hour": 9, "end_hour": end_hour, "timezone": "UTC", "locale": "en"}
        )
        mock_fetch.return_value = json.dumps([])

        result = json.loads(
            calendar_tools.find_available_slots("2026-10-02", "2026-10-02", duration_minutes=duration_minutes)
        )

        slots = result["available_slots"]
        assert len(slots) == expected_count
        if expected_last_end is not None:
            assert slots[-1]["end"] == f"2026-10-02T{expected_last_end}+00:00"
        for slot in slots:
            start = datetime.fromisoformat(slot["start"])
            end = datetime.fromisoformat(slot["end"])
            assert end <= start.replace(hour=end_hour, minute=0, second=0, microsecond=0)

    @patch.object(GoogleCalendarTools, "fetch_all_events")
    @patch.object(GoogleCalendarTools, "_get_working_hours")
    def test_find_available_slots_success(self, mock_working_hours, mock_fetch, calendar_tools):
        mock_working_hours.return_value = json.dumps(
            {"start_hour": 9, "end_hour": 17, "timezone": "UTC", "locale": "en"}
        )
        mock_fetch.return_value = json.dumps([])

        result = calendar_tools.find_available_slots(
            start_date="2025-07-21", end_date="2025-07-21", duration_minutes=30
        )
        result_data = json.loads(result)
        assert "available_slots" in result_data
        assert "working_hours" in result_data
        assert isinstance(result_data["available_slots"], list)

    @patch.object(GoogleCalendarTools, "fetch_all_events")
    @patch.object(GoogleCalendarTools, "_get_working_hours")
    def test_find_available_slots_with_busy_times(self, mock_working_hours, mock_fetch, calendar_tools):
        mock_working_hours.return_value = json.dumps(
            {"start_hour": 9, "end_hour": 17, "timezone": "UTC", "locale": "en"}
        )
        existing_events = [
            {"start": {"dateTime": "2025-07-19T10:30:00+00:00"}, "end": {"dateTime": "2025-07-19T11:30:00+00:00"}}
        ]
        mock_fetch.return_value = json.dumps(existing_events)

        result = calendar_tools.find_available_slots(
            start_date="2025-07-19", end_date="2025-07-19", duration_minutes=30
        )
        result_data = json.loads(result)
        assert result_data["events_analyzed"] == 1

    @patch.object(GoogleCalendarTools, "fetch_all_events")
    @patch.object(GoogleCalendarTools, "_get_working_hours")
    def test_find_available_slots_guarantees_slots(self, mock_working_hours, mock_fetch, calendar_tools):
        mock_working_hours.return_value = json.dumps(
            {"start_hour": 9, "end_hour": 17, "timezone": "UTC", "locale": "en"}
        )
        mock_fetch.return_value = json.dumps([])

        result = calendar_tools.find_available_slots(
            start_date="2025-07-21", end_date="2025-07-21", duration_minutes=30
        )
        result_data = json.loads(result)
        assert result_data["events_analyzed"] == 0
        assert len(result_data["available_slots"]) >= 10

    @patch.object(GoogleCalendarTools, "_get_working_hours")
    def test_find_available_slots_single_day_queries_working_hours(
        self, mock_working_hours, calendar_tools, mock_calendar_service
    ):
        mock_working_hours.return_value = json.dumps(
            {"start_hour": 9, "end_hour": 17, "timezone": "UTC", "locale": "en"}
        )
        mock_calendar_service.events().list().execute.return_value = {"items": []}

        calendar_tools.find_available_slots(start_date="2026-10-02", end_date="2026-10-02", duration_minutes=60)

        params = mock_calendar_service.events().list.call_args.kwargs
        assert params["timeMin"] == "2026-10-02T09:00:00+00:00"
        assert params["timeMax"] == "2026-10-02T17:00:00+00:00"

    @patch.object(GoogleCalendarTools, "_get_working_hours")
    def test_find_available_slots_blocks_busy_event_on_last_day(
        self, mock_working_hours, calendar_tools, mock_calendar_service
    ):
        mock_working_hours.return_value = json.dumps(
            {"start_hour": 9, "end_hour": 17, "timezone": "UTC", "locale": "en"}
        )
        busy_event = {
            "start": {"dateTime": "2026-10-02T14:00:00+00:00"},
            "end": {"dateTime": "2026-10-02T15:00:00+00:00"},
        }

        def execute_list_request():
            params = mock_calendar_service.events().list.call_args.kwargs
            time_min = datetime.fromisoformat(params["timeMin"])
            time_max = datetime.fromisoformat(params["timeMax"])
            event_start = datetime.fromisoformat(busy_event["start"]["dateTime"])
            event_end = datetime.fromisoformat(busy_event["end"]["dateTime"])
            if event_end > time_min and event_start < time_max:
                return {"items": [busy_event]}
            return {"items": []}

        mock_calendar_service.events().list().execute.side_effect = execute_list_request

        result = json.loads(calendar_tools.find_available_slots("2026-10-01", "2026-10-02", duration_minutes=60))

        assert result["events_analyzed"] == 1
        assert "2026-10-02T14:00:00+00:00" not in [slot["start"] for slot in result["available_slots"]]

    def test_find_available_slots_invalid_date(self, calendar_tools):
        result = calendar_tools.find_available_slots(
            start_date="invalid-date", end_date="2025-07-19", duration_minutes=60
        )
        assert "error" in json.loads(result)

    @staticmethod
    def _find_slots(calendar_tools, tz, start, end, *, hours=(9, 17), duration=30, events=None):
        working_hours = json.dumps({"start_hour": hours[0], "end_hour": hours[1], "timezone": tz, "locale": "en"})
        with (
            patch.object(GoogleCalendarTools, "_get_working_hours", return_value=working_hours),
            patch.object(GoogleCalendarTools, "fetch_all_events", return_value=json.dumps(events or [])) as mock_fetch,
        ):
            result = json.loads(calendar_tools.find_available_slots(start, end, duration))
        return result, mock_fetch

    @pytest.mark.parametrize(
        ("tz", "offset"),
        [
            ("UTC", "+00:00"),
            ("Asia/Kolkata", "+05:30"),
            ("Asia/Kathmandu", "+05:45"),
            ("America/Los_Angeles", "-07:00"),
            ("Pacific/Auckland", "+13:00"),
        ],
    )
    def test_find_available_slots_uses_user_timezone(self, calendar_tools, tz, offset):
        result, _ = self._find_slots(calendar_tools, tz, "2026-10-27", "2026-10-27")

        slots = result["available_slots"]
        assert result["timezone"] == tz
        assert len(slots) == 16
        assert slots[0]["start"] == f"2026-10-27T09:00:00{offset}"
        assert slots[-1]["end"] == f"2026-10-27T17:00:00{offset}"

    def test_find_available_slots_local_day_can_start_on_previous_utc_day(self, calendar_tools):
        result, _ = self._find_slots(calendar_tools, "Pacific/Auckland", "2026-10-26", "2026-10-26")

        first = result["available_slots"][0]["start"]
        assert first == "2026-10-26T09:00:00+13:00"
        assert datetime.fromisoformat(first).astimezone(timezone.utc).weekday() == 6

    def test_find_available_slots_fetches_scanned_local_window(self, calendar_tools):
        result, mock_fetch = self._find_slots(calendar_tools, "Asia/Kolkata", "2026-10-27", "2026-10-28")

        mock_fetch.assert_called_once_with(start_date="2026-10-27T09:00:00+05:30", end_date="2026-10-28T17:00:00+05:30")
        assert result["available_slots"][-1]["end"] == "2026-10-28T17:00:00+05:30"

    def test_find_available_slots_busy_event_in_other_offset(self, calendar_tools):
        # 06:30-07:30 at -04:00 is 16:00-17:00 in Asia/Kolkata
        events = [
            {"start": {"dateTime": "2026-10-27T06:30:00-04:00"}, "end": {"dateTime": "2026-10-27T07:30:00-04:00"}}
        ]

        result, _ = self._find_slots(
            calendar_tools, "Asia/Kolkata", "2026-10-27", "2026-10-27", duration=60, events=events
        )

        starts = [slot["start"] for slot in result["available_slots"]]
        assert result["events_analyzed"] == 1
        assert "2026-10-27T15:00:00+05:30" in starts
        assert "2026-10-27T15:30:00+05:30" not in starts
        assert "2026-10-27T16:00:00+05:30" not in starts

    def test_find_available_slots_offset_changes_between_days(self, calendar_tools):
        # US daylight saving ends on Sunday 2026-11-01; Friday is -07:00 and Monday is -08:00
        result, mock_fetch = self._find_slots(calendar_tools, "America/Los_Angeles", "2026-10-30", "2026-11-02")

        starts = [slot["start"] for slot in result["available_slots"]]
        assert starts[0] == "2026-10-30T09:00:00-07:00"
        assert "2026-11-02T09:00:00-08:00" in starts
        assert not any(start.startswith(("2026-10-31", "2026-11-01")) for start in starts)
        mock_fetch.assert_called_once_with(start_date="2026-10-30T09:00:00-07:00", end_date="2026-11-02T17:00:00-08:00")

    def test_find_available_slots_skips_nonexistent_local_times(self, calendar_tools):
        # Israel springs forward 02:00 -> 03:00 on Friday 2026-03-27, so 02:xx does not exist
        result, _ = self._find_slots(
            calendar_tools, "Asia/Jerusalem", "2026-03-27", "2026-03-27", hours=(1, 5), duration=60
        )

        slots = result["available_slots"]
        assert [slot["start"] for slot in slots] == [
            "2026-03-27T01:00:00+02:00",
            "2026-03-27T01:30:00+02:00",
            "2026-03-27T03:00:00+03:00",
            "2026-03-27T03:30:00+03:00",
            "2026-03-27T04:00:00+03:00",
        ]
        assert slots[0]["end"] == "2026-03-27T03:00:00+03:00"

    @pytest.mark.parametrize(
        ("start", "end", "first_slot"),
        [
            # 23:00 at -04:00 is already Tuesday 08:30 in Asia/Kolkata
            ("2026-10-26T23:00:00-04:00", "2026-10-26T23:00:00-04:00", "2026-10-27T09:00:00+05:30"),
            # no offset: the wall-clock date is taken as-is
            ("2026-10-27T15:30:00", "2026-10-27T15:30:00", "2026-10-27T09:00:00+05:30"),
        ],
    )
    def test_find_available_slots_timestamp_uses_user_local_date(self, calendar_tools, start, end, first_slot):
        result, _ = self._find_slots(calendar_tools, "Asia/Kolkata", start, end)

        assert result["available_slots"][0]["start"] == first_slot

    def test_find_available_slots_timestamp_on_user_weekend(self, calendar_tools):
        # Friday 20:00 at -07:00 is Saturday 08:30 in Asia/Kolkata
        result, _ = self._find_slots(
            calendar_tools, "Asia/Kolkata", "2026-10-30T20:00:00-07:00", "2026-10-30T20:00:00-07:00"
        )

        assert result["available_slots"] == []

    def test_find_available_slots_unknown_timezone_falls_back_to_utc(self, calendar_tools):
        with patch("agno.tools.google.calendar.log_warning") as mock_warning:
            result, _ = self._find_slots(calendar_tools, "Not/AZone", "2026-10-27", "2026-10-27")

        mock_warning.assert_called_once()
        assert "Could not load timezone 'Not/AZone'" in mock_warning.call_args.args[0]
        assert "using UTC" in mock_warning.call_args.args[0]
        assert result["timezone"] == "UTC"
        assert result["available_slots"][0]["start"] == "2026-10-27T09:00:00+00:00"
        assert all(slot["end"].endswith("+00:00") for slot in result["available_slots"])

    def test_find_available_slots_without_timezone_database(self, calendar_tools):
        # Windows without the tzdata package cannot resolve any zone, not even "UTC"
        with (
            patch("agno.tools.google.calendar.ZoneInfo", side_effect=ZoneInfoNotFoundError("no tzdata")),
            patch("agno.tools.google.calendar.log_warning") as mock_warning,
        ):
            result, _ = self._find_slots(calendar_tools, "Asia/Kolkata", "2026-10-27", "2026-10-27")

        mock_warning.assert_called_once()
        assert "Could not load timezone 'Asia/Kolkata'" in mock_warning.call_args.args[0]
        assert "using UTC" in mock_warning.call_args.args[0]
        assert result["timezone"] == "UTC"
        assert result["available_slots"][0]["start"] == "2026-10-27T09:00:00+00:00"
        assert all(slot["end"].endswith("+00:00") for slot in result["available_slots"])


class TestListCalendars:
    def test_list_calendars_success(self, calendar_tools, mock_calendar_service):
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
            ]
        }
        mock_calendar_service.calendarList().list().execute.return_value = mock_calendars

        result = calendar_tools.list_calendars()
        result_data = json.loads(result)
        assert "calendars" in result_data
        assert len(result_data["calendars"]) == 1
        assert result_data["current_default"] == "primary"

    def test_list_calendars_http_error(self, calendar_tools, mock_calendar_service):
        from googleapiclient.errors import HttpError

        mock_response = Mock()
        mock_response.status = 403
        mock_response.reason = "Forbidden"
        mock_calendar_service.calendarList().list().execute.side_effect = HttpError(
            mock_response, b'{"error": {"message": "Forbidden"}}'
        )
        result = calendar_tools.list_calendars()
        assert "error" in json.loads(result)


class TestQuickAddEvent:
    def test_quick_add_success(self, calendar_tools_all, mock_calendar_service):
        mock_event = {"id": "qa_id", "summary": "Lunch with Sarah tomorrow noon"}
        mock_calendar_service.events().quickAdd().execute.return_value = mock_event

        result = calendar_tools_all.quick_add_event(text="Lunch with Sarah tomorrow noon")
        assert json.loads(result) == mock_event

    def test_quick_add_http_error(self, calendar_tools_all, mock_calendar_service):
        from googleapiclient.errors import HttpError

        mock_response = Mock()
        mock_response.status = 400
        mock_response.reason = "Bad Request"
        mock_calendar_service.events().quickAdd().execute.side_effect = HttpError(
            mock_response, b'{"error": {"message": "Bad Request"}}'
        )
        result = calendar_tools_all.quick_add_event(text="invalid")
        assert "error" in json.loads(result)


class TestCheckAvailability:
    def test_check_availability_success(self, calendar_tools, mock_calendar_service):
        mock_result = {
            "calendars": {
                "alice@example.com": {"busy": [{"start": "2025-07-19T10:00:00Z", "end": "2025-07-19T11:00:00Z"}]},
                "bob@example.com": {"busy": []},
            }
        }
        mock_calendar_service.freebusy().query().execute.return_value = mock_result

        result = calendar_tools.check_availability(
            attendee_emails=["alice@example.com", "bob@example.com"],
            start_date="2025-07-19T09:00:00",
            end_date="2025-07-19T17:00:00",
        )
        result_data = json.loads(result)
        assert "availability" in result_data
        assert result_data["availability"]["alice@example.com"]["is_free"] is False
        assert result_data["availability"]["bob@example.com"]["is_free"] is True

    def test_check_availability_all_busy(self, calendar_tools, mock_calendar_service):
        mock_result = {
            "calendars": {
                "alice@example.com": {"busy": [{"start": "2025-07-19T09:00:00Z", "end": "2025-07-19T17:00:00Z"}]},
            }
        }
        mock_calendar_service.freebusy().query().execute.return_value = mock_result

        result = calendar_tools.check_availability(
            attendee_emails=["alice@example.com"],
            start_date="2025-07-19T09:00:00",
            end_date="2025-07-19T17:00:00",
        )
        result_data = json.loads(result)
        assert result_data["availability"]["alice@example.com"]["is_free"] is False
        assert len(result_data["availability"]["alice@example.com"]["busy_periods"]) == 1

    def test_check_availability_invalid_dates(self, calendar_tools):
        result = calendar_tools.check_availability(
            attendee_emails=["test@example.com"],
            start_date="not-a-date",
            end_date="2025-07-19T17:00:00",
        )
        assert "error" in json.loads(result)


class TestSearchEvents:
    def test_search_success(self, calendar_tools, mock_calendar_service):
        mock_events = [{"id": "1", "summary": "Team Standup"}]
        mock_calendar_service.events().list().execute.return_value = {"items": mock_events}

        result = calendar_tools.search_events(query="standup")
        assert json.loads(result)["events"] == mock_events

    def test_search_no_results(self, calendar_tools, mock_calendar_service):
        mock_calendar_service.events().list().execute.return_value = {"items": []}

        result = calendar_tools.search_events(query="nonexistent")
        assert "message" in json.loads(result)

    def test_search_with_date_range(self, calendar_tools, mock_calendar_service):
        mock_events = [{"id": "1", "summary": "Meeting"}]
        mock_calendar_service.events().list().execute.return_value = {"items": mock_events}

        result = calendar_tools.search_events(
            query="meeting",
            start_date="2025-07-01T00:00:00",
            end_date="2025-07-31T23:59:59",
        )
        assert json.loads(result)["events"] == mock_events


class TestMoveEvent:
    def test_move_event_success(self, calendar_tools_all, mock_calendar_service):
        mock_event = {"id": "test_id", "summary": "Moved Event"}
        mock_calendar_service.events().move().execute.return_value = mock_event

        result = calendar_tools_all.move_event(
            event_id="test_id",
            destination_calendar_id="work@example.com",
        )
        assert json.loads(result) == mock_event

    def test_move_event_http_error(self, calendar_tools_all, mock_calendar_service):
        from googleapiclient.errors import HttpError

        mock_response = Mock()
        mock_response.status = 404
        mock_response.reason = "Not Found"
        mock_calendar_service.events().move().execute.side_effect = HttpError(
            mock_response, b'{"error": {"message": "Not Found"}}'
        )
        result = calendar_tools_all.move_event(
            event_id="nonexistent",
            destination_calendar_id="work@example.com",
        )
        assert "error" in json.loads(result)


class TestGetEventAttendees:
    def test_get_attendees_success(self, calendar_tools, mock_calendar_service):
        mock_event = {
            "id": "test_id",
            "summary": "Team Meeting",
            "attendees": [
                {"email": "alice@example.com", "displayName": "Alice", "responseStatus": "accepted"},
                {"email": "bob@example.com", "displayName": "Bob", "responseStatus": "tentative", "optional": True},
            ],
        }
        mock_calendar_service.events().get().execute.return_value = mock_event

        result = calendar_tools.get_event_attendees(event_id="test_id")
        result_data = json.loads(result)
        assert result_data["total"] == 2
        assert result_data["attendees"][0]["email"] == "alice@example.com"
        assert result_data["attendees"][0]["response_status"] == "accepted"
        assert result_data["attendees"][1]["optional"] is True

    def test_get_attendees_no_attendees(self, calendar_tools, mock_calendar_service):
        mock_event = {"id": "test_id", "summary": "Solo Event"}
        mock_calendar_service.events().get().execute.return_value = mock_event

        result = calendar_tools.get_event_attendees(event_id="test_id")
        result_data = json.loads(result)
        assert result_data["total"] == 0
        assert result_data["attendees"] == []


class TestRespondToEvent:
    def test_respond_accepted(self, calendar_tools_all, mock_calendar_service):
        mock_calendar_service.calendarList().get().execute.return_value = {"id": "me@example.com"}
        mock_calendar_service.events().get().execute.return_value = {
            "id": "test_id",
            "attendees": [
                {"email": "me@example.com", "responseStatus": "needsAction"},
                {"email": "other@example.com", "responseStatus": "accepted"},
            ],
        }
        mock_calendar_service.events().patch().execute.return_value = {"id": "test_id"}

        result = calendar_tools_all.respond_to_event(event_id="test_id", response="accepted")
        assert "error" not in json.loads(result)

    def test_respond_declined(self, calendar_tools_all, mock_calendar_service):
        mock_calendar_service.calendarList().get().execute.return_value = {"id": "me@example.com"}
        mock_calendar_service.events().get().execute.return_value = {
            "id": "test_id",
            "attendees": [{"email": "me@example.com", "responseStatus": "needsAction"}],
        }
        mock_calendar_service.events().patch().execute.return_value = {"id": "test_id"}

        result = calendar_tools_all.respond_to_event(event_id="test_id", response="declined")
        assert "error" not in json.loads(result)

    def test_respond_invalid_response(self, calendar_tools_all):
        result = calendar_tools_all.respond_to_event(event_id="test_id", response="maybe")
        assert "error" in json.loads(result)
        assert "Invalid response" in json.loads(result)["error"]

    def test_respond_user_not_in_attendees(self, calendar_tools_all, mock_calendar_service):
        mock_calendar_service.calendarList().get().execute.return_value = {"id": "me@example.com"}
        mock_calendar_service.events().get().execute.return_value = {
            "id": "test_id",
            "attendees": [{"email": "other@example.com", "responseStatus": "accepted"}],
        }
        mock_calendar_service.events().patch().execute.return_value = {"id": "test_id"}

        result = calendar_tools_all.respond_to_event(event_id="test_id", response="accepted")
        # Should add user to attendees
        assert "error" not in json.loads(result)


class TestErrorHandling:
    def test_method_integration_works(self, calendar_tools):
        assert calendar_tools.calendar_id == "primary"
        assert calendar_tools.service is not None
        assert calendar_tools.creds is not None
