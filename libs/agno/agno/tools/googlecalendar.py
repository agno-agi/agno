import datetime
import json
import os.path
from functools import wraps

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
    from googleapiclient.errors import HttpError  # type: ignore
except ImportError:
    raise ImportError(
        "Google client library for Python not found , install it using `pip install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )
from typing import List, Optional

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def authenticated(func):
    """Decorator to ensure authentication before executing the method."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        # Ensure credentials are valid
        if os.path.exists(self.token_path):
            self.creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.creds_path, SCOPES)
                self.creds = flow.run_local_server(port=0)
                # Save the credentials for future use
            with open(self.token_path, "w") as token:
                token.write(self.creds.to_json())

            # Initialize the Google Calendar service
        try:
            self.service = build("calendar", "v3", credentials=self.creds)
        except HttpError as error:
            logger.error(f"An error occurred while creating the service: {error}")
            raise

        # Ensure the service is available
        if not self.service:
            raise ValueError("Google Calendar service could not be initialized.")

        return func(self, *args, **kwargs)

    return wrapper


class GoogleCalendarTools(Toolkit):
    def __init__(self, credentials_path: Optional[str] = None, token_path: Optional[str] = None, **kwargs):
        """
        Google Calendar Tool.

        :param credentials_path: Path of the file credentials.json file which contains OAuth 2.0 Client ID. A client ID is used to identify a single app to Google's OAuth servers. If your app runs on multiple platforms, you must create a separate client ID for each platform. Refer doc https://developers.google.com/calendar/api/quickstart/python#authorize_credentials_for_a_desktop_application
        :param token_path: Path of the file token.json which stores the user's access and refresh tokens, and is created automatically when the authorization flow completes for the first time.

        """
        super().__init__(name="google_calendar_tools", **kwargs)

        if not credentials_path:
            logger.error(
                "Google Calendar Tool : Please Provide Valid Credentials Path , You can refer https://developers.google.com/calendar/api/quickstart/python#authorize_credentials_for_a_desktop_application to create your credentials"
            )
            raise ValueError("Credential path is required")
        elif not os.path.exists(credentials_path):
            logger.error(
                "Google Calendar Tool : Credential file Path is invalid , please provide the full path of the credentials json file"
            )
            raise ValueError("Credentials Path is invalid")

        if not token_path:
            logger.warning(
                f"Google Calendar Tool : Token path is not provided, using {os.getcwd()}/token.json as default path"
            )
            token_path = "token.json"

        self.creds = None
        self.service = None
        self.token_path = token_path
        self.creds_path = credentials_path
        self.register(self.list_events)
        self.register(self.create_event)

    @authenticated
    def list_events(self, limit: int = 10, date_from: str = datetime.date.today().isoformat()) -> str:
        """
        List events from the user's primary calendar.

        Args:
            limit (Optional[int]): Number of events to return , default value is 10
            date_from (str) : the start date to return events from in date isoformat. Defaults to current datetime.

        """
        if date_from is None:
            date_from = datetime.datetime.now(datetime.timezone.utc).isoformat()
        elif isinstance(date_from, str):
            date_from = datetime.datetime.fromisoformat(date_from).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        try:
            if self.service:
                events_result = (
                    self.service.events()
                    .list(
                        calendarId="primary",
                        timeMin=date_from,
                        maxResults=limit,
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute()
                )
                events = events_result.get("items", [])
                if not events:
                    return json.dumps({"error": "No upcoming events found."})
                return json.dumps(events)
            else:
                return json.dumps({"error": "authentication issue"})
        except HttpError as error:
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticated
    def create_event(
        self,
        start_datetime: str,
        end_datetime: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        timezone: Optional[str] = None,
        attendees: List[str] = [],
    ) -> str:
        """
        Create a new event in the user's primary calendar.

        Args:
            title (Optional[str]): Title of the Event
            description (Optional[str]) : Detailed description of the event
            location (Optional[str]) : Location of the event
            start_datetime (Optional[str]) : start date and time of the event
            end_datetime (Optional[str]) : end date and time of the event
            attendees (Optional[List[str]]) : List of emails of the attendees
        """

        attendees_list = [{"email": attendee} for attendee in attendees] if attendees else []

        start_time = datetime.datetime.fromisoformat(start_datetime).strftime("%Y-%m-%dT%H:%M:%S")

        end_time = datetime.datetime.fromisoformat(end_datetime).strftime("%Y-%m-%dT%H:%M:%S")
        try:
            event = {
                "summary": title,
                "location": location,
                "description": description,
                "start": {"dateTime": start_time, "timeZone": timezone},
                "end": {"dateTime": end_time, "timeZone": timezone},
                "attendees": attendees_list,
            }
            if self.service:
                event_result = self.service.events().insert(calendarId="primary", body=event).execute()
                return json.dumps(event_result)
            else:
                return json.dumps({"error": "authentication issue"})
        except HttpError as error:
            logger.error(f"An error occurred: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})
