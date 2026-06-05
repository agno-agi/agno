"""
GoogleMeetTools — Create Meet spaces and read conference records, recordings, and transcripts.

Setup:
1. Install dependencies:
   `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`

2. Enable the Google Meet API in Google Cloud Console:
   https://console.cloud.google.com/apis/library/meet.googleapis.com

3. Create OAuth 2.0 credentials and download `credentials.json`, OR set env vars:
   - GOOGLE_CLIENT_ID
   - GOOGLE_CLIENT_SECRET
   - GOOGLE_PROJECT_ID
   - GOOGLE_REDIRECT_URI (optional, defaults to http://localhost)

4. Required OAuth scopes (declared in DEFAULT_SCOPES):
   - meetings.space.created — create and read spaces created by your app
   - meetings.space.readonly — read any space the user has access to
   - drive.readonly — download recording and transcript files from Drive

   Scopes for recordings/transcripts require workspace admin to enable recording
   and a meeting participant to start it during the call.

Notes:
- Recordings and transcripts take several minutes to generate after a meeting ends.
- Conference record listing is filtered to meetings where the user is the organizer.
- Ending an active conference is destructive and disabled by default; enable with
  `end_active_conference=True` and it will require confirmation before running.
"""

import json
import textwrap
from typing import TYPE_CHECKING, Any, List, Optional

from agno.tools.google.auth import google_authenticate
from agno.tools.google.base import GoogleToolkit
from agno.utils.log import log_debug, log_error

if TYPE_CHECKING:
    from agno.tools.google.auth import GoogleAuth

try:
    from googleapiclient.discovery import Resource, build
    from googleapiclient.errors import HttpError
except ImportError:
    raise ImportError(
        "`google-api-python-client` not installed. Please install using "
        "`pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )


MEET_INSTRUCTIONS = textwrap.dedent("""\
    You have access to Google Meet tools for creating meeting spaces and reading past meeting data.

    ## Tool Selection
    - Use create_meeting_space for a fresh meeting URL the user can share
    - Use get_meeting_space when you have a space name or meeting code and need details
    - Use list_conference_records to find past meetings organized by the user
    - Use list_participants, list_recordings, or list_transcripts AFTER you have a conference record name
    - Recording and transcript URIs point to files in Drive — you may need Drive tools to download them

    ## Resource Name Formats
    - Space: `spaces/{space_id}` or a meeting code like `abc-defg-hij`
    - Conference record: `conferenceRecords/{conference_id}`
    - Child resources: `conferenceRecords/{id}/recordings/{id}`, `.../transcripts/{id}`, etc.
    """)


authenticate = google_authenticate("meet")


class GoogleMeetTools(GoogleToolkit):
    api_name = "meet"
    api_version = "v2"
    google_service_name = "meet"
    default_scopes = [
        "https://www.googleapis.com/auth/meetings.space.created",
        "https://www.googleapis.com/auth/meetings.space.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    def __init__(
        self,
        scopes: Optional[List[str]] = None,
        creds: Optional[Any] = None,
        token_path: Optional[str] = None,
        credentials_path: Optional[str] = None,
        auth: Optional["GoogleAuth"] = None,
        service_account_path: Optional[str] = None,
        delegated_user: Optional[str] = None,
        oauth_port: int = 0,
        login_hint: Optional[str] = None,
        create_meeting_space: bool = True,
        get_meeting_space: bool = True,
        list_conference_records: bool = True,
        get_conference_record: bool = True,
        list_participants: bool = True,
        list_recordings: bool = True,
        list_transcripts: bool = True,
        list_transcript_entries: bool = True,
        end_active_conference: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs,
    ):
        super().__init__(
            scopes=scopes,
            creds=creds,
            token_path=token_path,
            credentials_path=credentials_path,
            auth=auth,
            service_account_path=service_account_path,
            delegated_user=delegated_user,
            oauth_port=oauth_port,
            login_hint=login_hint,
            **kwargs,
        )

        self.instructions = instructions if instructions is not None else MEET_INSTRUCTIONS

        tools: List[Any] = []

        if create_meeting_space:
            tools.append(self.create_meeting_space)
        if get_meeting_space:
            tools.append(self.get_meeting_space)
        if list_conference_records:
            tools.append(self.list_conference_records)
        if get_conference_record:
            tools.append(self.get_conference_record)
        if list_participants:
            tools.append(self.list_participants)
        if list_recordings:
            tools.append(self.list_recordings)
        if list_transcripts:
            tools.append(self.list_transcripts)
        if list_transcript_entries:
            tools.append(self.list_transcript_entries)
        if end_active_conference:
            tools.append(self.end_active_conference)

        confirm = kwargs.pop("requires_confirmation_tools", None) or []
        if end_active_conference and "end_active_conference" not in confirm:
            confirm.append("end_active_conference")

        super().__init__(
            name="google_meet_tools",
            tools=tools,
            instructions=self.instructions,
            add_instructions=add_instructions,
            requires_confirmation_tools=confirm,
            **kwargs,
        )

        # Writing scope (space.created) is required when creating spaces or ending conferences
        write_tools = {"create_meeting_space", "end_active_conference"}
        if any(name in self.functions for name in write_tools):
            if "https://www.googleapis.com/auth/meetings.space.created" not in self.scopes:
                raise ValueError(
                    "Scope 'meetings.space.created' is required to create meeting spaces or end conferences."
                )

    @authenticate
    def create_meeting_space(self) -> str:
        """Create a new Google Meet space and return a shareable meeting URL.

        The meeting space is owned by the authenticated user. The returned meeting_uri
        is a stable link users can join at any time.

        Returns:
            JSON string with the space name, meeting_uri, and meeting_code, or an error.
        """
        try:
            log_debug("Creating Google Meet space")
            space = self.service.spaces().create(body={}).execute()  # type: ignore
            return json.dumps(
                {
                    "name": space.get("name"),
                    "meeting_uri": space.get("meetingUri"),
                    "meeting_code": space.get("meetingCode"),
                    "config": space.get("config", {}),
                }
            )
        except HttpError as e:
            log_error(f"Google Meet error creating space: {e}")
            return json.dumps({"error": f"Google Meet error creating space: {e}"})
        except Exception as e:
            log_error(f"Unexpected error creating Meet space: {e}")
            return json.dumps({"error": f"Unexpected error creating Meet space: {e}"})

    @authenticate
    def get_meeting_space(self, name: str) -> str:
        """Get details for an existing Google Meet space.

        Args:
            name: Space resource name (e.g. "spaces/abc123") or meeting code (e.g. "abc-defg-hij").

        Returns:
            JSON string with the space details including meeting_uri, meeting_code, and config,
            or an error.
        """
        try:
            log_debug(f"Fetching Meet space: {name}")
            space = self.service.spaces().get(name=name).execute()  # type: ignore
            return json.dumps(space)
        except HttpError as e:
            log_error(f"Google Meet error fetching space {name}: {e}")
            return json.dumps({"error": f"Google Meet error fetching space: {e}"})
        except Exception as e:
            log_error(f"Unexpected error fetching Meet space {name}: {e}")
            return json.dumps({"error": f"Unexpected error fetching Meet space: {e}"})

    @authenticate
    def list_conference_records(self, filter: Optional[str] = None, page_size: int = 25) -> str:
        """List past Google Meet conferences organized by the authenticated user.

        Results are ordered by start time, most recent first. Only conferences where
        the user is the organizer are returned.

        Args:
            filter: Optional filter expression. Example: 'space.meeting_code="abc-defg-hij"'.
            page_size: Maximum number of records to return. Defaults to 25.

        Returns:
            JSON string with a list of conference records (name, start_time, end_time, space),
            or an error.
        """
        try:
            log_debug(f"Listing conference records (filter={filter}, page_size={page_size})")
            request = self.service.conferenceRecords().list(filter=filter, pageSize=page_size)  # type: ignore
            response = request.execute()
            return json.dumps(
                {
                    "conference_records": response.get("conferenceRecords", []),
                    "next_page_token": response.get("nextPageToken"),
                }
            )
        except HttpError as e:
            log_error(f"Google Meet error listing conference records: {e}")
            return json.dumps({"error": f"Google Meet error listing conference records: {e}"})
        except Exception as e:
            log_error(f"Unexpected error listing conference records: {e}")
            return json.dumps({"error": f"Unexpected error listing conference records: {e}"})

    @authenticate
    def get_conference_record(self, name: str) -> str:
        """Get details for a specific past Google Meet conference.

        Args:
            name: Conference record name in the format "conferenceRecords/{conference_id}".

        Returns:
            JSON string with the conference record details, or an error.
        """
        try:
            log_debug(f"Fetching conference record: {name}")
            record = self.service.conferenceRecords().get(name=name).execute()  # type: ignore
            return json.dumps(record)
        except HttpError as e:
            log_error(f"Google Meet error fetching conference record {name}: {e}")
            return json.dumps({"error": f"Google Meet error fetching conference record: {e}"})
        except Exception as e:
            log_error(f"Unexpected error fetching conference record {name}: {e}")
            return json.dumps({"error": f"Unexpected error fetching conference record: {e}"})

    @authenticate
    def list_participants(self, parent: str, page_size: int = 100) -> str:
        """List participants of a past Google Meet conference.

        Args:
            parent: Conference record name in the format "conferenceRecords/{conference_id}".
            page_size: Maximum number of participants to return. Defaults to 100.

        Returns:
            JSON string with a list of participants (name, earliest_start_time, latest_end_time),
            or an error.
        """
        try:
            log_debug(f"Listing participants for {parent}")
            response = (
                self.service.conferenceRecords().participants().list(parent=parent, pageSize=page_size).execute()  # type: ignore
            )
            return json.dumps(
                {
                    "participants": response.get("participants", []),
                    "next_page_token": response.get("nextPageToken"),
                    "total_size": response.get("totalSize"),
                }
            )
        except HttpError as e:
            log_error(f"Google Meet error listing participants for {parent}: {e}")
            return json.dumps({"error": f"Google Meet error listing participants: {e}"})
        except Exception as e:
            log_error(f"Unexpected error listing participants for {parent}: {e}")
            return json.dumps({"error": f"Unexpected error listing participants: {e}"})

    @authenticate
    def list_recordings(self, parent: str) -> str:
        """List recordings for a past Google Meet conference.

        Recordings are produced asynchronously and may take several minutes to appear
        after the meeting ends. A conference must have recording enabled and started
        during the call for recordings to exist.

        Args:
            parent: Conference record name in the format "conferenceRecords/{conference_id}".

        Returns:
            JSON string with a list of recordings (name, drive_destination, state,
            start_time, end_time), or an error.
        """
        try:
            log_debug(f"Listing recordings for {parent}")
            response = self.service.conferenceRecords().recordings().list(parent=parent).execute()  # type: ignore
            return json.dumps(
                {
                    "recordings": response.get("recordings", []),
                    "next_page_token": response.get("nextPageToken"),
                }
            )
        except HttpError as e:
            log_error(f"Google Meet error listing recordings for {parent}: {e}")
            return json.dumps({"error": f"Google Meet error listing recordings: {e}"})
        except Exception as e:
            log_error(f"Unexpected error listing recordings for {parent}: {e}")
            return json.dumps({"error": f"Unexpected error listing recordings: {e}"})

    @authenticate
    def list_transcripts(self, parent: str) -> str:
        """List transcripts for a past Google Meet conference.

        Transcripts are produced asynchronously and may take several minutes to appear
        after the meeting ends.

        Args:
            parent: Conference record name in the format "conferenceRecords/{conference_id}".

        Returns:
            JSON string with a list of transcripts (name, docs_destination, state,
            start_time, end_time), or an error.
        """
        try:
            log_debug(f"Listing transcripts for {parent}")
            response = self.service.conferenceRecords().transcripts().list(parent=parent).execute()  # type: ignore
            return json.dumps(
                {
                    "transcripts": response.get("transcripts", []),
                    "next_page_token": response.get("nextPageToken"),
                }
            )
        except HttpError as e:
            log_error(f"Google Meet error listing transcripts for {parent}: {e}")
            return json.dumps({"error": f"Google Meet error listing transcripts: {e}"})
        except Exception as e:
            log_error(f"Unexpected error listing transcripts for {parent}: {e}")
            return json.dumps({"error": f"Unexpected error listing transcripts: {e}"})

    @authenticate
    def list_transcript_entries(self, parent: str, page_size: int = 100) -> str:
        """List transcript entries (individual spoken lines) for a Meet transcript.

        Args:
            parent: Transcript resource name in the format
                "conferenceRecords/{conference_id}/transcripts/{transcript_id}".
            page_size: Maximum number of entries to return. Defaults to 100.

        Returns:
            JSON string with a list of transcript entries (text, start_time, end_time,
            participant, language_code), or an error.
        """
        try:
            log_debug(f"Listing transcript entries for {parent}")
            response = (
                self.service.conferenceRecords()  # type: ignore
                .transcripts()
                .entries()
                .list(parent=parent, pageSize=page_size)
                .execute()
            )
            return json.dumps(
                {
                    "transcript_entries": response.get("transcriptEntries", []),
                    "next_page_token": response.get("nextPageToken"),
                }
            )
        except HttpError as e:
            log_error(f"Google Meet error listing transcript entries for {parent}: {e}")
            return json.dumps({"error": f"Google Meet error listing transcript entries: {e}"})
        except Exception as e:
            log_error(f"Unexpected error listing transcript entries for {parent}: {e}")
            return json.dumps({"error": f"Unexpected error listing transcript entries: {e}"})

    @authenticate
    def end_active_conference(self, name: str) -> str:
        """End the active conference on a meeting space. Cannot be undone.

        Disconnects all participants from the ongoing conference. The meeting space
        remains valid and can be reused later.

        Args:
            name: Space resource name in the format "spaces/{space_id}".

        Returns:
            JSON string confirming the action, or an error.
        """
        try:
            log_debug(f"Ending active conference on space {name}")
            self.service.spaces().endActiveConference(name=name).execute()  # type: ignore
            return json.dumps({"ended": True, "name": name})
        except HttpError as e:
            log_error(f"Google Meet error ending conference on {name}: {e}")
            return json.dumps({"error": f"Google Meet error ending conference: {e}"})
        except Exception as e:
            log_error(f"Unexpected error ending conference on {name}: {e}")
            return json.dumps({"error": f"Unexpected error ending conference: {e}"})
