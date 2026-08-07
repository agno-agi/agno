import json
from base64 import b64encode
from datetime import datetime, timedelta
from os import getenv
from typing import Any, Callable, Dict, List, Optional

import requests

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_exception, log_info, log_warning


class ZoomTools(Toolkit):
    """Toolkit for scheduling and managing Zoom meetings.

    Args:
        account_id: Zoom account ID. Falls back to ZOOM_ACCOUNT_ID env var.
        client_id: OAuth client ID. Falls back to ZOOM_CLIENT_ID env var.
        client_secret: OAuth client secret. Falls back to ZOOM_CLIENT_SECRET env var.
        schedule_meeting: Enable schedule_meeting tool. Defaults to False (creates meeting).
        get_upcoming_meetings: Enable get_upcoming_meetings tool. Defaults to True.
        list_meetings: Enable list_meetings tool. Defaults to True.
        get_meeting_recordings: Enable get_meeting_recordings tool. Defaults to False (token heavy).
        delete_meeting: Enable delete_meeting tool. Defaults to False (destructive).
        get_meeting: Enable get_meeting tool. Defaults to True.
        all: Enable all tools. Defaults to False.
        timeout: Request timeout in seconds. Defaults to 30.
    """

    def __init__(
        self,
        account_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        schedule_meeting: bool = False,
        get_upcoming_meetings: bool = True,
        list_meetings: bool = True,
        get_meeting_recordings: bool = False,
        delete_meeting: bool = False,
        get_meeting: bool = True,
        all: bool = False,
        timeout: int = 30,
        **kwargs,
    ):
        self.account_id = account_id or getenv("ZOOM_ACCOUNT_ID")
        self.client_id = client_id or getenv("ZOOM_CLIENT_ID")
        self.client_secret = client_secret or getenv("ZOOM_CLIENT_SECRET")
        self.__access_token = None
        self.__token_expiry = None

        if not self.account_id or not self.client_id or not self.client_secret:
            log_error(
                "ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, and ZOOM_CLIENT_SECRET must be set either through parameters or environment variables."
            )

        tools: List[Callable] = []
        if all or schedule_meeting:
            tools.append(self.schedule_meeting)
        if all or get_upcoming_meetings:
            tools.append(self.get_upcoming_meetings)
        if all or list_meetings:
            tools.append(self.list_meetings)
        if all or get_meeting_recordings:
            tools.append(self.get_meeting_recordings)
        if all or delete_meeting:
            tools.append(self.delete_meeting)
        if all or get_meeting:
            tools.append(self.get_meeting)

        super().__init__(
            name="zoom_tools",
            tools=tools,
            instructions="Use this tool to schedule and manage Zoom meetings. You can schedule meetings by providing a topic, start time, and duration.",
            timeout=timeout,
            **kwargs,
        )

    def get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary.

        Returns:
            The current access token or empty string if token generation fails.
        """
        # Check if we have a valid token
        if self.__access_token and self.__token_expiry and datetime.now() < self.__token_expiry:
            return self.__access_token

        # Generate new token
        try:
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
            }

            # Create base64 encoded auth string
            auth_string = b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            headers["Authorization"] = f"Basic {auth_string}"

            data: Dict[str, Any] = {
                "grant_type": "account_credentials",
                "account_id": self.account_id,
            }

            response = requests.post("https://zoom.us/oauth/token", headers=headers, data=data, timeout=self.timeout)
            response.raise_for_status()

            token_data = response.json()
            self.__access_token = token_data["access_token"]
            # Set expiry time slightly before actual expiry to ensure token validity
            self.__token_expiry = datetime.now() + timedelta(seconds=token_data["expires_in"] - 60)  # type: ignore

            log_debug("Successfully generated new Zoom access token")
            return self.__access_token  # type: ignore

        except requests.RequestException:
            log_exception("Failed to generate Zoom access token")
            self.__access_token = None
            self.__token_expiry = None
            return ""

    def schedule_meeting(self, topic: str, start_time: str, duration: int, timezone: str = "UTC") -> str:
        """Schedule a new Zoom meeting.

        Args:
            topic: The topic or title of the meeting.
            start_time: The start time in ISO 8601 format.
            duration: The duration in minutes.
            timezone: The timezone (e.g., "America/New_York"). Defaults to "UTC".

        Returns:
            JSON with scheduled meeting details or error.
        """
        log_debug(f"Attempting to schedule meeting: {topic} in timezone: {timezone}")
        token = self.get_access_token()
        if not token:
            log_error("Unable to obtain access token.")
            return json.dumps({"error": "Failed to obtain access token"})

        url = "https://api.zoom.us/v2/users/me/meetings"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        data: Dict[str, Any] = {
            "topic": topic,
            "type": 2,
            "start_time": start_time,
            "duration": duration,
            "timezone": timezone,
            "settings": {
                "host_video": True,
                "participant_video": True,
                "join_before_host": False,
                "mute_upon_entry": False,
                "watermark": True,
                "audio": "voip",
                "auto_recording": "none",
            },
        }

        try:
            response = requests.post(url, json=data, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            meeting_info = response.json()

            result = {
                "message": "Meeting scheduled successfully!",
                "meeting_id": meeting_info["id"],
                "topic": meeting_info["topic"],
                "start_time": meeting_info["start_time"],
                "duration": meeting_info["duration"],
                "join_url": meeting_info["join_url"],
            }
            log_info(f"Meeting scheduled successfully. ID: {meeting_info['id']}")
            return json.dumps(result, indent=2)
        except requests.RequestException as e:
            log_exception("Error scheduling meeting")
            return json.dumps({"error": str(e)})

    def get_upcoming_meetings(self, user_id: str = "me") -> str:
        """Get upcoming meetings for a user.

        Args:
            user_id: The user ID or 'me' for authenticated user. Defaults to 'me'.

        Returns:
            JSON with upcoming meetings or error.
        """
        log_debug(f"Fetching upcoming meetings for user: {user_id}")
        token = self.get_access_token()
        if not token:
            log_error("Unable to obtain access token.")
            return json.dumps({"error": "Failed to obtain access token"})

        url = f"https://api.zoom.us/v2/users/{user_id}/meetings"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"type": "upcoming", "page_size": str(30)}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=self.timeout)  # type: ignore
            response.raise_for_status()
            meetings = response.json()

            result = {"message": "Upcoming meetings retrieved successfully", "meetings": meetings.get("meetings", [])}
            log_info(f"Retrieved {len(result['meetings'])} upcoming meetings")
            return json.dumps(result, indent=2)
        except requests.RequestException as e:
            log_exception("Error fetching upcoming meetings")
            return json.dumps({"error": str(e)})

    def list_meetings(self, user_id: str = "me", type: str = "scheduled") -> str:
        """List meetings for a user.

        Args:
            user_id: The user ID or 'me' for authenticated user. Defaults to 'me'.
            type: Meeting type - "scheduled", "live", "upcoming", or "previous".

        Returns:
            JSON with meetings list or error.
        """
        log_debug(f"Fetching meetings for user: {user_id}")
        token = self.get_access_token()
        if not token:
            log_error("Unable to obtain access token.")
            return json.dumps({"error": "Failed to obtain access token"})

        url = f"https://api.zoom.us/v2/users/{user_id}/meetings"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"type": type}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=self.timeout)
            response.raise_for_status()
            meetings = response.json()

            result = {
                "message": "Meetings retrieved successfully",
                "page_count": meetings.get("page_count", 0),
                "page_number": meetings.get("page_number", 1),
                "page_size": meetings.get("page_size", 30),
                "total_records": meetings.get("total_records", 0),
                "meetings": meetings.get("meetings", []),
            }
            log_info(f"Retrieved {len(result['meetings'])} meetings")
            return json.dumps(result, indent=2)
        except requests.RequestException as e:
            log_exception("Error fetching meetings")
            return json.dumps({"error": str(e)})

    def get_meeting_recordings(
        self, meeting_id: str, include_download_token: bool = False, token_ttl: Optional[int] = None
    ) -> str:
        """Get recordings for a meeting.

        Args:
            meeting_id: The meeting ID or UUID.
            include_download_token: Include download access token. Defaults to False.
            token_ttl: Download token TTL in seconds (max 604800).

        Returns:
            JSON with recordings info or error.
        """
        log_debug(f"Fetching recordings for meeting: {meeting_id}")
        token = self.get_access_token()
        if not token:
            log_error("Unable to obtain access token.")
            return json.dumps({"error": "Failed to obtain access token"})

        url = f"https://api.zoom.us/v2/meetings/{meeting_id}/recordings"
        headers = {"Authorization": f"Bearer {token}"}

        # Build query parameters
        params = {}
        if include_download_token:
            params["include_fields"] = "download_access_token"
            if token_ttl is not None:
                if 0 <= token_ttl <= 604800:
                    params["ttl"] = str(token_ttl)  # Convert to string if necessary
                else:
                    log_warning("Invalid TTL value. Must be between 0 and 604800 seconds.")

        try:
            response = requests.get(url, headers=headers, params=params, timeout=self.timeout)
            response.raise_for_status()
            recordings = response.json()

            result = {
                "message": "Meeting recordings retrieved successfully",
                "meeting_id": str(recordings.get("id", "")),
                "uuid": recordings.get("uuid", ""),
                "host_id": recordings.get("host_id", ""),
                "topic": recordings.get("topic", ""),
                "start_time": recordings.get("start_time", ""),
                "duration": recordings.get("duration", 0),
                "total_size": recordings.get("total_size", 0),
                "recording_count": recordings.get("recording_count", 0),
                "recording_files": recordings.get("recording_files", []),
            }

            log_info(f"Retrieved {result['recording_count']} recording files")
            return json.dumps(result, indent=2)
        except requests.RequestException as e:
            log_exception("Error fetching meeting recordings")
            return json.dumps({"error": str(e)})

    def delete_meeting(self, meeting_id: str, schedule_for_reminder: bool = True) -> str:
        """Delete a scheduled Zoom meeting.

        Args:
            meeting_id: The ID of the meeting to delete.
            schedule_for_reminder: Send cancellation email to registrants. Defaults to True.

        Returns:
            JSON with deletion status or error.
        """
        log_debug(f"Attempting to delete meeting: {meeting_id}")
        token = self.get_access_token()
        if not token:
            log_error("Unable to obtain access token.")
            return json.dumps({"error": "Failed to obtain access token"})

        url = f"https://api.zoom.us/v2/meetings/{meeting_id}"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"schedule_for_reminder": schedule_for_reminder}

        try:
            response = requests.delete(url, headers=headers, params=params, timeout=self.timeout)
            response.raise_for_status()

            # Zoom returns 204 No Content for successful deletion
            if response.status_code == 204:
                result = {"message": "Meeting deleted successfully!", "meeting_id": meeting_id}
                log_info(f"Meeting {meeting_id} deleted successfully")
            else:
                result = response.json()

            return json.dumps(result, indent=2)
        except requests.RequestException as e:
            log_exception("Error deleting meeting")
            return json.dumps({"error": str(e)})

    def get_meeting(self, meeting_id: str) -> str:
        """Get details of a specific Zoom meeting.

        Args:
            meeting_id: The ID of the meeting to retrieve.

        Returns:
            JSON with meeting details or error.
        """
        log_debug(f"Fetching details for meeting: {meeting_id}")
        token = self.get_access_token()
        if not token:
            log_error("Unable to obtain access token.")
            return json.dumps({"error": "Failed to obtain access token"})

        url = f"https://api.zoom.us/v2/meetings/{meeting_id}"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            response = requests.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            meeting_info = response.json()

            result = {
                "message": "Meeting details retrieved successfully",
                "meeting_id": str(meeting_info.get("id", "")),
                "topic": meeting_info.get("topic", ""),
                "type": meeting_info.get("type", ""),
                "start_time": meeting_info.get("start_time", ""),
                "duration": meeting_info.get("duration", 0),
                "timezone": meeting_info.get("timezone", ""),
                "created_at": meeting_info.get("created_at", ""),
                "join_url": meeting_info.get("join_url", ""),
                "settings": meeting_info.get("settings", {}),
            }

            log_info(f"Retrieved details for meeting ID: {meeting_id}")
            return json.dumps(result, indent=2)
        except requests.RequestException as e:
            log_exception("Error fetching meeting details")
            return json.dumps({"error": str(e)})
