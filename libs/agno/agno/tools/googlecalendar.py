import datetime
import json
import os.path
import uuid
from functools import wraps
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    raise ImportError(
        "Google client libraries not found, Please install using `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def authenticate(func):
    """Decorator to ensure authentication before executing the method."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            if not self.creds or not self.creds.valid:
                self._auth()
            if not self.service:
                self.service = build("calendar", "v3", credentials=self.creds)
        except Exception:
            # If authentication fails, let the method handle the missing service
            pass
        return func(self, *args, **kwargs)

    return wrapper


class GoogleCalendarTools(Toolkit):
    """
    Enhanced Google Calendar Tools supporting both file-based and token-based authentication.
    """

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
        access_token: Optional[str] = None,
        list_events: bool = True,
        create_event: bool = True,
        update_event: bool = True,
        delete_event: bool = True,
        fetch_all_events: bool = True,
        find_available_slots: bool = True,
        port: int = 8080,
        **kwargs,
    ):
        """
        Initialize Google Calendar Tools with either file-based or token-based authentication.

        Args:
            credentials_path (Optional[str]): Path to the credentials.json file for OAuth 2.0 flow
            token_path (Optional[str]): Path to store/retrieve the token.json file
            access_token (Optional[str]): Direct OAuth 2.0 access token for token-based authentication
            list_events (bool): Enable listing events. Defaults to True.
            create_event (bool): Enable creating events. Defaults to True.
            update_event (bool): Enable updating events. Defaults to True.
            delete_event (bool): Enable deleting events. Defaults to True.
            fetch_all_events (bool): Enable fetching all events. Defaults to True.
            find_available_slots (bool): Enable finding available time slots. Defaults to True.
        """

        self.creds: Optional[Credentials] = None
        self.service: Optional[Any] = None  # Google Calendar service object

        # Token-based authentication
        if access_token:
            self.access_token = access_token
            self.creds = Credentials(access_token)
        # File-based authentication
        elif credentials_path:
            if not os.path.exists(credentials_path):
                logger.error(
                    "Google Calendar Tool: Credential file path is invalid, please provide the full path of the credentials json file"
                )
                raise ValueError("Credentials Path is invalid")

            if not token_path:
                logger.warning(
                    f"Google Calendar Tool: Token path is not provided, using {os.getcwd()}/token.json as default path"
                )
                token_path = "token.json"

            self.credentials_path = credentials_path
            self.token_path = token_path
        else:
            logger.error("Google Calendar Tool: Please provide either valid credentials path or access token")
            raise ValueError("Either credentials path or access token is required")

        # Build tools list
        tools: List[Any] = []
        if list_events:
            tools.append(self.list_events)
        if create_event:
            tools.append(self.create_event)
        if update_event:
            tools.append(self.update_event)
        if delete_event:
            tools.append(self.delete_event)
        if fetch_all_events:
            tools.append(self.fetch_all_events)
        if find_available_slots:
            tools.append(self.find_available_slots)

        super().__init__(name="google_calendar_tools", tools=tools, **kwargs)

    def _auth(self) -> None:
        """Authenticate with Google Calendar API"""
        # Handle token-based authentication
        if hasattr(self, "access_token"):
            return

        # Handle file-based authentication
        if hasattr(self, "token_path") and os.path.exists(self.token_path):
            self.creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                # Try common ports that should be configured in Google Cloud Console
                ports_to_try = [8080, 8000, 9000, 8090, 8888]

                for port in ports_to_try:
                    try:
                        logger.info(f"Attempting OAuth authentication on port {port}")
                        self.creds = flow.run_local_server(port=port)
                        break
                    except OSError as e:
                        if "Address already in use" in str(e):
                            logger.warning(f"Port {port} is in use, trying next port...")
                            continue
                        else:
                            raise e
                else:
                    # If all common ports fail, use random port but warn user
                    logger.warning(
                        "All common ports in use, using random port. You may need to add this redirect URI to Google Cloud Console."
                    )
                    self.creds = flow.run_local_server(port=0)

                # Save the credentials for future use
                with open(self.token_path, "w") as token:
                    token.write(self.creds.to_json())

    @authenticate
    def list_events(self, limit: int = 10, date_from: Optional[str] = None, calendar_id: str = "primary") -> str:
        """
        List events from the user's calendar.

        Args:
            limit (Optional[int]): Number of events to return, default value is 10
            date_from (Optional[str]): The start date to return events from in date isoformat. Defaults to current datetime.
            calendar_id (Optional[str]): Calendar ID to fetch events from. Default is 'primary'.

        Returns:
            str: JSON string containing the events or error message
        """
        if date_from is None:
            date_from = datetime.datetime.now(datetime.timezone.utc).isoformat()
        elif isinstance(date_from, str):
            try:
                date_from = datetime.datetime.fromisoformat(date_from).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                return json.dumps({"error": f"Invalid date format: {date_from}. Use ISO format (YYYY-MM-DDTHH:MM:SS)."})

        try:
            if not self.service:
                return json.dumps({"error": "Google Calendar service not initialized"})

            events_result = (
                self.service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=date_from,
                    maxResults=limit,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            events = events_result.get("items", [])
            if not events:
                return json.dumps({"message": "No upcoming events found."})
            return json.dumps(events)
        except HttpError as error:
            logger.error(f"An error occurred: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def create_event(
        self,
        start_datetime: str,
        end_datetime: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        timezone: Optional[str] = "UTC",
        attendees: Optional[List[str]] = None,
        calendar_id: str = "primary",
        send_updates: str = "none",
        visibility: str = "default",
        transparency: str = "opaque",
        recurrence: Optional[List[str]] = None,
        reminders: Optional[Dict] = None,
        add_google_meet_link: Optional[bool] = False,
    ) -> str:
        """
        Create a new event in the calendar.

        Args:
            start_datetime (str): Start date and time of the event (ISO format)
            end_datetime (str): End date and time of the event (ISO format)
            title (Optional[str]): Title/summary of the Event
            description (Optional[str]): Detailed description of the event
            location (Optional[str]): Location of the event
            timezone (Optional[str]): Timezone for the event
            attendees (Optional[List[str]]): List of emails of the attendees
            calendar_id (Optional[str]): Calendar ID to create event in. Default is 'primary'.
            send_updates (Optional[str]): What kind of updates to send attendees ("all", "externalOnly", "none")
            visibility (Optional[str]): Visibility of the event ("default", "public", "private")
            transparency (Optional[str]): Whether the event blocks time ("opaque", "transparent")
            recurrence (Optional[List[str]]): Recurrence rules for repeating events
            reminders (Optional[Dict]): Reminder settings for the event
            add_google_meet_link (Optional[bool]): Whether to add a google meet link to the event

        Returns:
            str: JSON string containing the created event or error message
        """
        try:
            # Format attendees if provided
            attendees_list = [{"email": attendee} for attendee in attendees] if attendees else []

            # Convert ISO string to datetime and format as required
            try:
                start_time = datetime.datetime.fromisoformat(start_datetime).strftime("%Y-%m-%dT%H:%M:%S")
                end_time = datetime.datetime.fromisoformat(end_datetime).strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                return json.dumps({"error": "Invalid datetime format. Use ISO format (YYYY-MM-DDTHH:MM:SS)."})

            # Create event dictionary
            event = {
                "summary": title,
                "location": location,
                "description": description,
                "start": {"dateTime": start_time, "timeZone": timezone},
                "end": {"dateTime": end_time, "timeZone": timezone},
                "attendees": attendees_list,
                "recurrence": recurrence,
                "reminders": reminders,
                "visibility": visibility if visibility != "default" else None,
                "transparency": transparency if transparency != "opaque" else None,
            }

            # Add Google Meet link if requested
            if add_google_meet_link:
                event["conferenceData"] = {
                    "createRequest": {"requestId": str(uuid.uuid4()), "conferenceSolutionKey": {"type": "hangoutsMeet"}}
                }

            # Remove None values
            event = {k: v for k, v in event.items() if v is not None}

            if not self.service:
                return json.dumps({"error": "Google Calendar service not initialized"})

            event_result = (
                self.service.events()
                .insert(
                    calendarId=calendar_id,
                    body=event,
                    sendUpdates=send_updates,
                    conferenceDataVersion=1 if add_google_meet_link else 0,
                )
                .execute()
            )
            logger.info(f"Event created successfully in calendar {calendar_id}. Event ID: {event_result['id']}")
            return json.dumps(event_result)
        except HttpError as error:
            logger.error(f"An error occurred: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def update_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
        title: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        start_datetime: Optional[str] = None,
        end_datetime: Optional[str] = None,
        timezone: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        send_updates: str = "none",
    ) -> str:
        """
        Update an existing event in the calendar.

        Args:
            event_id (str): ID of the event to update
            calendar_id (Optional[str]): Calendar ID containing the event. Default is 'primary'.
            title (Optional[str]): New title/summary of the event
            description (Optional[str]): New description of the event
            location (Optional[str]): New location of the event
            start_datetime (Optional[str]): New start date and time (ISO format)
            end_datetime (Optional[str]): New end date and time (ISO format)
            timezone (Optional[str]): New timezone for the event
            attendees (Optional[List[str]]): Updated list of attendee emails
            send_updates (Optional[str]): What kind of updates to send attendees

        Returns:
            str: JSON string containing the updated event or error message
        """
        try:
            if not self.service:
                return json.dumps({"error": "Google Calendar service not initialized"})

            # First get the existing event to preserve its structure
            event = self.service.events().get(calendarId=calendar_id, eventId=event_id).execute()

            # Update only the fields that are provided
            if title is not None:
                event["summary"] = title
            if description is not None:
                event["description"] = description
            if location is not None:
                event["location"] = location
            if attendees is not None:
                event["attendees"] = [{"email": attendee} for attendee in attendees]

            # Handle datetime updates
            if start_datetime:
                try:
                    start_time = datetime.datetime.fromisoformat(start_datetime).strftime("%Y-%m-%dT%H:%M:%S")
                    event["start"]["dateTime"] = start_time
                    if timezone:
                        event["start"]["timeZone"] = timezone
                except ValueError:
                    return json.dumps({"error": f"Invalid start datetime format: {start_datetime}. Use ISO format."})

            if end_datetime:
                try:
                    end_time = datetime.datetime.fromisoformat(end_datetime).strftime("%Y-%m-%dT%H:%M:%S")
                    event["end"]["dateTime"] = end_time
                    if timezone:
                        event["end"]["timeZone"] = timezone
                except ValueError:
                    return json.dumps({"error": f"Invalid end datetime format: {end_datetime}. Use ISO format."})

            # Update the event
            updated_event = (
                self.service.events()
                .update(calendarId=calendar_id, eventId=event_id, body=event, sendUpdates=send_updates)
                .execute()
            )

            logger.info(f"Event {event_id} updated successfully.")
            return json.dumps(updated_event)
        except HttpError as error:
            logger.error(f"An error occurred while updating event: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def delete_event(self, event_id: str, calendar_id: str = "primary", send_updates: str = "none") -> str:
        """
        Delete an event from the calendar.

        Args:
            event_id (str): ID of the event to delete
            calendar_id (Optional[str]): Calendar ID containing the event. Default is 'primary'.
            send_updates (Optional[str]): What kind of updates to send attendees

        Returns:
            str: JSON string containing success message or error message
        """
        try:
            if not self.service:
                return json.dumps({"error": "Google Calendar service not initialized"})

            self.service.events().delete(calendarId=calendar_id, eventId=event_id, sendUpdates=send_updates).execute()

            logger.info(f"Event {event_id} deleted successfully.")
            return json.dumps({"success": True, "message": f"Event {event_id} deleted successfully."})
        except HttpError as error:
            logger.error(f"An error occurred while deleting event: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def fetch_all_events(
        self,
        calendar_id: str = "primary",
        max_results: int = 250,
        include_past: bool = True,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
    ) -> str:
        """
        Fetch all events, including past events if specified.

        Args:
            calendar_id (Optional[str]): Calendar ID to fetch events from. Default is 'primary'.
            max_results (Optional[int]): Maximum number of results per page. Default is 250.
            include_past (Optional[bool]): Whether to include past events. Default is True.
            time_min (Optional[str]): The minimum time to include events from (ISO format).
            time_max (Optional[str]): The maximum time to include events up to (ISO format).

        Returns:
            str: JSON string containing all events or error message
        """
        try:
            if not self.service:
                return json.dumps({"error": "Google Calendar service not initialized"})

            params = {
                "calendarId": calendar_id,
                "maxResults": min(max_results, 2500),
                "singleEvents": True,
                "orderBy": "startTime",
            }

            # Set time parameters if provided
            if time_min:
                # Accept both string and already formatted ISO strings
                if isinstance(time_min, str):
                    try:
                        # Try to parse and reformat to ensure proper timezone format
                        dt = datetime.datetime.fromisoformat(time_min)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=datetime.timezone.utc)
                        params["timeMin"] = dt.isoformat()
                    except ValueError:
                        # If it's already a valid ISO string, use it directly
                        params["timeMin"] = time_min
                else:
                    params["timeMin"] = time_min
            elif not include_past:
                params["timeMin"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

            if time_max:
                # Accept both string and already formatted ISO strings
                if isinstance(time_max, str):
                    try:
                        # Try to parse and reformat to ensure proper timezone format
                        dt = datetime.datetime.fromisoformat(time_max)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=datetime.timezone.utc)
                        params["timeMax"] = dt.isoformat()
                    except ValueError:
                        # If it's already a valid ISO string, use it directly
                        params["timeMax"] = time_max
                else:
                    params["timeMax"] = time_max

            # Handle pagination
            all_events = []
            page_token = None

            while True:
                if page_token:
                    params["pageToken"] = page_token

                events_result = self.service.events().list(**params).execute()
                all_events.extend(events_result.get("items", []))

                page_token = events_result.get("nextPageToken")
                if not page_token:
                    break

            logger.info(f"Fetched {len(all_events)} events from calendar: {calendar_id}")

            if not all_events:
                return json.dumps({"message": "No events found."})
            return json.dumps(all_events)
        except HttpError as error:
            logger.error(f"An error occurred while fetching events: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def find_available_slots(
        self,
        start_date: str,
        end_date: str,
        duration_minutes: int = 60,
        calendar_id: str = "primary",
        start_hour: int = 9,
        end_hour: int = 17,
        timezone: str = "UTC",
    ) -> str:
        """
        Find available time slots within a date range.

        Args:
            start_date (str): Start date to search from (ISO format date)
            end_date (str): End date to search to (ISO format date)
            duration_minutes (int): Length of the desired slot in minutes
            calendar_id (str): Calendar ID to check
            start_hour (int): Start of working hours (24-hour format)
            end_hour (int): End of working hours (24-hour format)
            timezone (str): Timezone for the search

        Returns:
            str: JSON string containing available slots or error message
        """
        try:
            # Convert string dates to datetime objects
            try:
                start_dt = datetime.datetime.fromisoformat(start_date)
                end_dt = datetime.datetime.fromisoformat(end_date)

                # Set the time to the beginning and end of the day with timezone
                start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=0)

                # Ensure timezone awareness for Google Calendar API
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=datetime.timezone.utc)

            except ValueError:
                return json.dumps({"error": "Invalid date format. Use ISO format (YYYY-MM-DD)."})

            # Get all events in the date range with proper RFC3339 format
            events_json = self.fetch_all_events(
                calendar_id=calendar_id, time_min=start_dt.isoformat(), time_max=end_dt.isoformat()
            )

            events_data = json.loads(events_json)
            if "error" in events_data:
                return json.dumps({"error": events_data["error"]})

            events = events_data if isinstance(events_data, list) else events_data.get("items", [])

            # Process events to get busy times
            busy_times = []
            for event in events:
                # Skip events with transparency=transparent (non-blocking)
                if event.get("transparency") == "transparent":
                    continue

                start = event.get("start", {})
                end = event.get("end", {})

                # Handle all-day events
                if "date" in start:
                    start_time = datetime.datetime.fromisoformat(start["date"])
                    end_time = datetime.datetime.fromisoformat(end["date"])
                else:
                    # Handle regular events
                    start_time = datetime.datetime.fromisoformat(start.get("dateTime", "").replace("Z", "+00:00"))
                    end_time = datetime.datetime.fromisoformat(end.get("dateTime", "").replace("Z", "+00:00"))

                busy_times.append((start_time, end_time))

            # Find available slots
            available_slots = []
            current_date = start_dt

            while current_date <= end_dt:
                # Set working hours for the day
                day_start = current_date.replace(hour=start_hour, minute=0, second=0)
                day_end = current_date.replace(hour=end_hour, minute=0, second=0)

                # Create potential slots
                slot_start = day_start
                while slot_start < day_end:
                    slot_end = slot_start + datetime.timedelta(minutes=duration_minutes)
                    if slot_end > day_end:
                        break

                    # Check if slot overlaps with any busy time
                    is_available = True
                    for busy_start, busy_end in busy_times:
                        # If there's any overlap, mark as unavailable
                        if not (slot_end <= busy_start or slot_start >= busy_end):
                            is_available = False
                            break

                    if is_available:
                        available_slots.append({"start": slot_start.isoformat(), "end": slot_end.isoformat()})

                    # Move to next potential slot (30-minute increments)
                    slot_start += datetime.timedelta(minutes=30)

                # Move to next day
                current_date += datetime.timedelta(days=1)

            return json.dumps(
                {"available_slots": available_slots, "timezone": timezone, "duration_minutes": duration_minutes}
            )

        except Exception as e:
            logger.error(f"An error occurred while finding available slots: {e}")
            return json.dumps({"error": f"An error occurred: {str(e)}"})


class GoogleCalendarTokenTools(GoogleCalendarTools):
    """
    Backward compatibility class for token-based authentication.
    """

    def __init__(self, access_token: str, **kwargs):
        """
        Initialize with access token for backward compatibility.

        Args:
            access_token (str): OAuth 2.0 access token
        """
        super().__init__(access_token=access_token, **kwargs)
