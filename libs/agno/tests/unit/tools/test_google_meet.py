import json
from unittest.mock import MagicMock

import pytest

from agno.tools.google.meet import GoogleMeetTools


@pytest.fixture
def mock_service():
    service = MagicMock()
    return service


@pytest.fixture
def meet_tools(mock_service):
    tools = GoogleMeetTools(creds=MagicMock(valid=True))
    tools.service = mock_service
    return tools


class TestInit:
    def test_default_tools_registered(self):
        tools = GoogleMeetTools(creds=MagicMock(valid=True))
        names = list(tools.functions.keys())
        assert "create_meeting_space" in names
        assert "get_meeting_space" in names
        assert "list_conference_records" in names
        assert "list_participants" in names
        assert "list_recordings" in names
        assert "list_transcripts" in names

    def test_destructive_tool_disabled_by_default(self):
        tools = GoogleMeetTools(creds=MagicMock(valid=True))
        assert "end_active_conference" not in tools.functions

    def test_destructive_tool_requires_confirmation_when_enabled(self):
        tools = GoogleMeetTools(creds=MagicMock(valid=True), end_active_conference=True)
        assert "end_active_conference" in tools.functions
        func = tools.functions["end_active_conference"]
        assert func.requires_confirmation is True

    def test_selective_enable(self):
        tools = GoogleMeetTools(
            creds=MagicMock(valid=True),
            create_meeting_space=True,
            get_meeting_space=False,
            list_conference_records=False,
            get_conference_record=False,
            list_participants=False,
            list_recordings=False,
            list_transcripts=False,
            list_transcript_entries=False,
        )
        assert list(tools.functions.keys()) == ["create_meeting_space"]

    def test_default_scopes_applied(self):
        tools = GoogleMeetTools(creds=MagicMock(valid=True))
        assert "https://www.googleapis.com/auth/meetings.space.created" in tools.scopes
        assert "https://www.googleapis.com/auth/meetings.space.readonly" in tools.scopes

    def test_custom_scopes_rejected_when_write_tool_enabled(self):
        with pytest.raises(ValueError, match="meetings.space.created"):
            GoogleMeetTools(
                creds=MagicMock(valid=True),
                scopes=["https://www.googleapis.com/auth/meetings.space.readonly"],
                create_meeting_space=True,
            )

    def test_custom_instructions_override(self):
        custom = "Use these tools carefully."
        tools = GoogleMeetTools(creds=MagicMock(valid=True), instructions=custom)
        assert tools.instructions == custom

    def test_default_instructions_present(self):
        tools = GoogleMeetTools(creds=MagicMock(valid=True))
        assert "Google Meet" in tools.instructions


class TestCreateMeetingSpace:
    def test_success(self, meet_tools, mock_service):
        mock_service.spaces().create().execute.return_value = {
            "name": "spaces/abc123",
            "meetingUri": "https://meet.google.com/abc-defg-hij",
            "meetingCode": "abc-defg-hij",
            "config": {"accessType": "TRUSTED"},
        }
        result = meet_tools.create_meeting_space()
        parsed = json.loads(result)
        assert parsed["name"] == "spaces/abc123"
        assert parsed["meeting_uri"] == "https://meet.google.com/abc-defg-hij"
        assert parsed["meeting_code"] == "abc-defg-hij"

    def test_http_error_returns_json_error(self, meet_tools, mock_service):
        from googleapiclient.errors import HttpError

        http_error = HttpError(resp=MagicMock(status=403), content=b'{"error": "forbidden"}')
        mock_service.spaces().create().execute.side_effect = http_error
        result = meet_tools.create_meeting_space()
        parsed = json.loads(result)
        assert "error" in parsed

    def test_unexpected_error_returns_json_error(self, meet_tools, mock_service):
        mock_service.spaces().create().execute.side_effect = RuntimeError("boom")
        result = meet_tools.create_meeting_space()
        parsed = json.loads(result)
        assert "error" in parsed
        assert "boom" in parsed["error"]


class TestGetMeetingSpace:
    def test_success(self, meet_tools, mock_service):
        mock_service.spaces().get().execute.return_value = {
            "name": "spaces/abc123",
            "meetingUri": "https://meet.google.com/abc-defg-hij",
        }
        result = meet_tools.get_meeting_space("spaces/abc123")
        parsed = json.loads(result)
        assert parsed["name"] == "spaces/abc123"

    def test_passes_name_to_api(self, meet_tools, mock_service):
        mock_service.spaces().get.reset_mock()
        mock_service.spaces().get().execute.return_value = {"name": "spaces/xyz"}
        meet_tools.get_meeting_space("spaces/xyz")
        # The mocked chain records the kwargs on the final get() call
        call_args = mock_service.spaces().get.call_args_list
        assert any(call.kwargs.get("name") == "spaces/xyz" for call in call_args)


class TestListConferenceRecords:
    def test_success(self, meet_tools, mock_service):
        mock_service.conferenceRecords().list().execute.return_value = {
            "conferenceRecords": [
                {"name": "conferenceRecords/1", "startTime": "2026-04-10T10:00:00Z"},
                {"name": "conferenceRecords/2", "startTime": "2026-04-09T14:00:00Z"},
            ]
        }
        result = meet_tools.list_conference_records()
        parsed = json.loads(result)
        assert len(parsed["conference_records"]) == 2

    def test_filter_parameter_passed(self, meet_tools, mock_service):
        mock_service.conferenceRecords().list.reset_mock()
        mock_service.conferenceRecords().list().execute.return_value = {"conferenceRecords": []}
        meet_tools.list_conference_records(filter='space.meeting_code="abc"', page_size=10)
        call_args = mock_service.conferenceRecords().list.call_args_list
        assert any(
            call.kwargs.get("filter") == 'space.meeting_code="abc"' and call.kwargs.get("pageSize") == 10
            for call in call_args
        )


class TestListParticipants:
    def test_success(self, meet_tools, mock_service):
        mock_service.conferenceRecords().participants().list().execute.return_value = {
            "participants": [
                {"name": "conferenceRecords/1/participants/p1", "earliestStartTime": "2026-04-10T10:00:00Z"},
            ],
            "totalSize": 1,
        }
        result = meet_tools.list_participants("conferenceRecords/1")
        parsed = json.loads(result)
        assert len(parsed["participants"]) == 1
        assert parsed["total_size"] == 1


class TestListRecordings:
    def test_success(self, meet_tools, mock_service):
        mock_service.conferenceRecords().recordings().list().execute.return_value = {
            "recordings": [
                {
                    "name": "conferenceRecords/1/recordings/r1",
                    "state": "FILE_GENERATED",
                    "driveDestination": {"file": "drive/file/id"},
                }
            ]
        }
        result = meet_tools.list_recordings("conferenceRecords/1")
        parsed = json.loads(result)
        assert len(parsed["recordings"]) == 1

    def test_empty_recordings(self, meet_tools, mock_service):
        mock_service.conferenceRecords().recordings().list().execute.return_value = {}
        result = meet_tools.list_recordings("conferenceRecords/1")
        parsed = json.loads(result)
        assert parsed["recordings"] == []


class TestListTranscripts:
    def test_success(self, meet_tools, mock_service):
        mock_service.conferenceRecords().transcripts().list().execute.return_value = {
            "transcripts": [{"name": "conferenceRecords/1/transcripts/t1", "state": "ENDED"}]
        }
        result = meet_tools.list_transcripts("conferenceRecords/1")
        parsed = json.loads(result)
        assert len(parsed["transcripts"]) == 1


class TestListTranscriptEntries:
    def test_success(self, meet_tools, mock_service):
        mock_service.conferenceRecords().transcripts().entries().list().execute.return_value = {
            "transcriptEntries": [
                {"text": "Hello team", "startTime": "2026-04-10T10:00:05Z", "languageCode": "en-US"},
            ]
        }
        result = meet_tools.list_transcript_entries("conferenceRecords/1/transcripts/t1")
        parsed = json.loads(result)
        assert len(parsed["transcript_entries"]) == 1
        assert parsed["transcript_entries"][0]["text"] == "Hello team"


class TestEndActiveConference:
    def test_success(self):
        tools = GoogleMeetTools(creds=MagicMock(valid=True), end_active_conference=True)
        tools.service = MagicMock()
        tools.service.spaces().endActiveConference().execute.return_value = {}
        result = tools.end_active_conference("spaces/abc123")
        parsed = json.loads(result)
        assert parsed["ended"] is True
        assert parsed["name"] == "spaces/abc123"
