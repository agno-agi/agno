import json
from base64 import b64encode
from datetime import datetime, timedelta
from os import getenv
from typing import Optional

import requests

from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_info, logger


class ZoomTools(Toolkit):
    def __init__(
        self,
        account_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        **kwargs,
    ):
        """
        Initialize the ZoomTool.

        Args:
            account_id (str): The Zoom account ID for authentication. If not provided, will use ZOOM_ACCOUNT_ID env var.
            client_id (str): The client ID for authentication. If not provided, will use ZOOM_CLIENT_ID env var.
            client_secret (str): The client secret for authentication. If not provided, will use ZOOM_CLIENT_SECRET env var.
            name (str): The name of the tool. Defaults to "zoom_tool".
        """
        super().__init__(name="zoom_tool", **kwargs)

        # Get credentials from env vars if not provided
        self.account_id = account_id or getenv("ZOOM_ACCOUNT_ID")
        self.client_id = client_id or getenv("ZOOM_CLIENT_ID")
        self.client_secret = client_secret or getenv("ZOOM_CLIENT_SECRET")
        self.__access_token = None  # Made private
        self.__token_expiry = None  # Track token expiration

        if not self.account_id or not self.client_id or not self.client_secret:
            logger.error(
                "ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, and ZOOM_CLIENT_SECRET must be set either through parameters or environment variables."
            )

        # Register functions
        self.register(self.schedule_meeting)
        self.register(self.get_upcoming_meetings)
        self.register(self.list_meetings)
        self.register(self.get_meeting_recordings)
        self.register(self.delete_meeting)
        self.register(self.get_meeting)

    def get_access_token(self) -> str:
        """
        Get a valid access token, refreshing if necessary using Zoom's Server-to-Server OAuth.

        Returns:
            str: The current access token or empty string if token generation fails.
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

            data = {
                "grant_type": "account_credentials",
                "account_id": self.account_id,
            }

            response = requests.post("https://zoom.us/oauth/token", headers=headers, data=data)
            response.raise_for_status()

            token_data = response.json()
            self.__access_token = token_data["access_token"]
            # Set expiry time slightly before actual expiry to ensure token validity
            self.__token_expiry = datetime.now() + timedelta(seconds=token_data["expires_in"] - 60)  # type: ignore

            log_debug("Successfully generated new Zoom access token")
            return self.__access_token  # type: ignore

        except requests.RequestException as e:
            logger.error(f"Failed to generate Zoom access token: {e}")
            self.__access_token = None
            self.__token_expiry = None
            return ""

    def schedule_meeting(self, topic: str, start_time: str, duration: int, timezone: str = "UTC") -> str:
        """
        Schedule a new Zoom meeting.

        Args:
            topic (str): The topic or title of the meeting.
            start_time (str): The start time of the meeting in ISO 8601 format.
            duration (int): The duration of the meeting in minutes.
            timezone (str): The timezone for the meeting (e.g., "America/New_York", "Asia/Tokyo").

        Returns:
            A JSON-formatted string containing the response from Zoom API with the scheduled meeting details,
            or an error message if the scheduling fails.
        """
        log_debug(f"Attempting to schedule meeting: {topic} in timezone: {timezone}")
        token = self.get_access_token()
        if not token:
            logger.error("Unable to obtain access token.")
            return json.dumps({"error": "Failed to obtain access token"})

        url = "https://api.zoom.us/v2/users/me/meetings"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        data = {
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
            response = requests.post(url, json=data, headers=headers)
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
            logger.error(f"Error scheduling meeting: {e}")
            return json.dumps({"error": str(e)})

    def get_upcoming_meetings(self, user_id: str = "me") -> str:
        """
        Get a list of upcoming meetings for a specified user.

        Args:
            user_id (str): The user ID or 'me' for the authenticated user. Defaults to 'me'.

        Returns:
            A JSON-formatted string containing the upcoming meetings information,
            or an error message if the request fails.
        """
        log_debug(f"Fetching upcoming meetings for user: {user_id}")
        token = self.get_access_token()
        if not token:
            logger.error("Unable to obtain access token.")
            return json.dumps({"error": "Failed to obtain access token"})

        url = f"https://api.zoom.us/v2/users/{user_id}/meetings"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"type": "upcoming", "page_size": str(30)}

        try:
            response = requests.get(url, headers=headers, params=params)  # type: ignore
            response.raise_for_status()
            meetings = response.json()

            result = {"message": "Upcoming meetings retrieved successfully", "meetings": meetings.get("meetings", [])}
            log_info(f"Retrieved {len(result['meetings'])} upcoming meetings")
            return json.dumps(result, indent=2)
        except requests.RequestException as e:
            logger.error(f"Error fetching upcoming meetings: {e}")
            return json.dumps({"error": str(e)})

    def list_meetings(self, user_id: str = "me", type: str = "scheduled") -> str:
        """
        List all meetings for a specified user.

        Args:
            user_id (str): The user ID or 'me' for the authenticated user. Defaults to 'me'.
            type (str): The type of meetings to return. Options are:
                       "scheduled" - All valid scheduled meetings
                       "live" - All live meetings
                       "upcoming" - All upcoming meetings
                       "previous" - All previous meetings
                       Defaults to "scheduled".

        Returns:
            A JSON-formatted string containing the meetings information,
            or an error message if the request fails.
        """
        log_debug(f"Fetching meetings for user: {user_id}")
        token = self.get_access_token()
        if not token:
            logger.error("Unable to obtain access token.")
            return json.dumps({"error": "Failed to obtain access token"})

        url = f"https://api.zoom.us/v2/users/{user_id}/meetings"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"type": type}

        try:
            response = requests.get(url, headers=headers, params=params)
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
            logger.error(f"Error fetching meetings: {e}")
            return json.dumps({"error": str(e)})

    def get_meeting_recordings(
        self, meeting_id: str, include_download_token: bool = False, token_ttl: Optional[int] = None
    ) -> str:
        """
        Get all recordings for a specific meeting.

        Args:
            meeting_id (str): The meeting ID or UUID to get recordings for.
            include_download_token (bool): Whether to include download access token in response.
            token_ttl (int, optional): Time to live for download token in seconds (max 604800).

        Returns:
            A JSON-formatted string containing the meeting recordings information,
            or an error message if the request fails.
        """
        log_debug(f"Fetching recordings for meeting: {meeting_id}")
        token = self.get_access_token()
        if not token:
            logger.error("Unable to obtain access token.")
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
                    logger.warning("Invalid TTL value. Must be between 0 and 604800 seconds.")

        try:
            response = requests.get(url, headers=headers, params=params)
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
            logger.error(f"Error fetching meeting recordings: {e}")
            return json.dumps({"error": str(e)})

    def delete_meeting(self, meeting_id: str, schedule_for_reminder: bool = True) -> str:
        """
        Delete a scheduled Zoom meeting.

        Args:
            meeting_id (str): The ID of the meeting to delete
            schedule_for_reminder (bool): Send cancellation email to registrants.
                                          Defaults to True.

        Returns:
            A JSON-formatted string containing the response status,
            or an error message if the deletion fails.
        """
        log_debug(f"Attempting to delete meeting: {meeting_id}")
        token = self.get_access_token()
        if not token:
            logger.error("Unable to obtain access token.")
            return json.dumps({"error": "Failed to obtain access token"})

        url = f"https://api.zoom.us/v2/meetings/{meeting_id}"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"schedule_for_reminder": schedule_for_reminder}

        try:
            response = requests.delete(url, headers=headers, params=params)
            response.raise_for_status()

            # Zoom returns 204 No Content for successful deletion
            if response.status_code == 204:
                result = {"message": "Meeting deleted successfully!", "meeting_id": meeting_id}
                log_info(f"Meeting {meeting_id} deleted successfully")
            else:
                result = response.json()

            return json.dumps(result, indent=2)
        except requests.RequestException as e:
            logger.error(f"Error deleting meeting: {e}")
            return json.dumps({"error": str(e)})

    def get_meeting(self, meeting_id: str) -> str:
        """
        Get the details of a specific Zoom meeting.

        Args:
            meeting_id (str): The ID of the meeting to retrieve

        Returns:
            A JSON-formatted string containing the meeting details,
            or an error message if the request fails.
        """
        log_debug(f"Fetching details for meeting: {meeting_id}")
        token = self.get_access_token()
        if not token:
            logger.error("Unable to obtain access token.")
            return json.dumps({"error": "Failed to obtain access token"})

        url = f"https://api.zoom.us/v2/meetings/{meeting_id}"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            response = requests.get(url, headers=headers)
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
            logger.error(f"Error fetching meeting details: {e}")
            return json.dumps({"error": str(e)})

    def instructions(self) -> str:
        """
        Provide instructions for using the ZoomTool.

        Returns:
            A string containing instructions on how to use the ZoomTool.
        """
        return "Use this tool to schedule and manage Zoom meetings. You can schedule meetings by providing a topic, start time, and duration."
