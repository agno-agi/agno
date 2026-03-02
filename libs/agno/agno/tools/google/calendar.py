import datetime
import json
import uuid
from functools import wraps
from os import getenv
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_info

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import Resource, build
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
        except Exception as e:
            log_error(f"An error occurred: {e}")
        return func(self, *args, **kwargs)

    return wrapper


class GoogleCalendarTools(Toolkit):
    # Default scopes for Google Calendar API access
    DEFAULT_SCOPES = {
        "read": "https://www.googleapis.com/auth/calendar.readonly",
        "write": "https://www.googleapis.com/auth/calendar",
    }

    service: Optional[Resource]

    def __init__(
        self,
        scopes: Optional[List[str]] = None,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = "token.json",
        access_token: Optional[str] = None,
        calendar_id: str = "primary",
        oauth_port: int = 8080,
        allow_update: bool = False,
        **kwargs,
    ):
        self.creds: Optional[Credentials] = None
        self.service: Optional[Resource] = None
        self.calendar_id: str = calendar_id
        self.oauth_port: int = oauth_port
        self.access_token = access_token
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.allow_update = allow_update
        self.scopes = scopes or []

        super().__init__(
            name="google_calendar_tools",
            tools=[
                self.list_events,
                self.create_event,
                self.update_event,
                self.delete_event,
                self.fetch_all_events,
                self.find_available_slots,
                self.list_calendars,
            ],
            **kwargs,
        )
        if not self.scopes:
            # Add read permission by default
            self.scopes.append(self.DEFAULT_SCOPES["read"])
            # Add write permission if allow_update is True
            if self.allow_update:
                self.scopes.append(self.DEFAULT_SCOPES["write"])

        # Validate that required scopes are present for requested operations
        if self.allow_update and self.DEFAULT_SCOPES["write"] not in self.scopes:
            raise ValueError(f"The scope {self.DEFAULT_SCOPES['write']} is required for write operations")
        if self.DEFAULT_SCOPES["read"] not in self.scopes and self.DEFAULT_SCOPES["write"] not in self.scopes:
            raise ValueError(
                f"Either {self.DEFAULT_SCOPES['read']} or {self.DEFAULT_SCOPES['write']} is required for read operations"
            )

    def _auth(self) -> None:
        """
        Authenticate with Google Calendar API
        """
        if self.creds and self.creds.valid:
            return

        token_file = Path(self.token_path or "token.json")
        creds_file = Path(self.credentials_path or "credentials.json")

        if token_file.exists():
            self.creds = Credentials.from_authorized_user_file(str(token_file), self.DEFAULT_SCOPES)

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                client_config = {
                    "installed": {
                        "client_id": getenv("GOOGLE_CLIENT_ID"),
                        "client_secret": getenv("GOOGLE_CLIENT_SECRET"),
                        "project_id": getenv("GOOGLE_PROJECT_ID"),
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "redirect_uris": [getenv("GOOGLE_REDIRECT_URI", "http://localhost")],
                    }
                }
                # File based authentication
                if creds_file.exists():
                    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), self.scopes)
                else:
                    flow = InstalledAppFlow.from_client_config(client_config, self.scopes)
                # Opens up a browser window for OAuth authentication
                self.creds = flow.run_local_server(port=self.oauth_port)

        if self.creds:
            token_file.write_text(self.creds.to_json())
            log_debug("Successfully authenticated with Google Calendar API.")
            log_info(f"Token file path: {token_file}")

    @authenticate
    def list_events(self, limit: int = 10, start_date: Optional[str] = None) -> str:
        """
        List upcoming events from the user's Google Calendar.

        Args:
            limit (Optional[int]): Number of events to return, default value is 10
            start_date (Optional[str]): The start date to return events from in ISO format (YYYY-MM-DDTHH:MM:SS)

        Returns:
            str: JSON string containing the Google Calendar events or error message
        """
        if start_date is None:
            start_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
            log_debug(f"No start date provided, using current datetime: {start_date}")
        elif isinstance(start_date, str):
            try:
                start_date = datetime.datetime.fromisoformat(start_date).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                return json.dumps(
                    {"error": f"Invalid date format: {start_date}. Use ISO format (YYYY-MM-DDTHH:MM:SS)."}
                )

        try:
            service = cast(Resource, self.service)

            events_result = (
                service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=start_date,
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
            log_error(f"An error occurred: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def create_event(
        self,
        start_date: str,
        end_date: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        timezone: Optional[str] = "UTC",
        attendees: Optional[List[str]] = None,
        add_google_meet_link: Optional[bool] = False,
        notify_attendees: Optional[bool] = False,
    ) -> str:
        """
        Create a new event in the Google Calendar.

        Args:
            start_date (str): Start date and time of the event in ISO format (YYYY-MM-DDTHH:MM:SS)
            end_date (str): End date and time of the event in ISO format (YYYY-MM-DDTHH:MM:SS)
            title (Optional[str]): Title/summary of the event
            description (Optional[str]): Detailed description of the event
            location (Optional[str]): Location of the event
            timezone (Optional[str]): Timezone for the event (default: UTC)
            attendees (Optional[List[str]]): List of email addresses of the attendees
            add_google_meet_link (Optional[bool]): Whether to add a Google Meet video link to the event
            notify_attendees (Optional[bool]): Whether to send email notifications to attendees (default: False)

        Returns:
            str: JSON string containing the created Google Calendar event or error message
        """
        try:
            # Format attendees if provided
            attendees_list = [{"email": attendee} for attendee in attendees] if attendees else []

            # Convert ISO string to datetime and format as required
            try:
                start_time = datetime.datetime.fromisoformat(start_date).strftime("%Y-%m-%dT%H:%M:%S")
                end_time = datetime.datetime.fromisoformat(end_date).strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                return json.dumps({"error": "Invalid datetime format. Use ISO format (YYYY-MM-DDTHH:MM:SS)."})

            # Create event dictionary
            event: Dict[str, Any] = {
                "summary": title,
                "location": location,
                "description": description,
                "start": {"dateTime": start_time, "timeZone": timezone},
                "end": {"dateTime": end_time, "timeZone": timezone},
                "attendees": attendees_list,
            }

            # Add Google Meet link if requested
            if add_google_meet_link:
                event["conferenceData"] = {
                    "createRequest": {"requestId": str(uuid.uuid4()), "conferenceSolutionKey": {"type": "hangoutsMeet"}}
                }

            # Remove None values
            event = {k: v for k, v in event.items() if v is not None}

            # Determine sendUpdates value based on notify_attendees parameter
            send_updates = "all" if notify_attendees and attendees else "none"

            service = cast(Resource, self.service)

            event_result = (
                service.events()
                .insert(
                    calendarId=self.calendar_id,
                    body=event,
                    conferenceDataVersion=1 if add_google_meet_link else 0,
                    sendUpdates=send_updates,
                )
                .execute()
            )
            log_debug(f"Event created successfully in calendar {self.calendar_id}. Event ID: {event_result['id']}")
            return json.dumps(event_result)
        except HttpError as error:
            log_error(f"An error occurred: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def update_event(
        self,
        event_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        timezone: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        notify_attendees: Optional[bool] = False,
    ) -> str:
        """
        Update an existing event in the Google Calendar.

        Args:
            event_id (str): ID of the event to update
            title (Optional[str]): New title/summary of the event
            description (Optional[str]): New description of the event
            location (Optional[str]): New location of the event
            start_date (Optional[str]): New start date and time in ISO format (YYYY-MM-DDTHH:MM:SS)
            end_date (Optional[str]): New end date and time in ISO format (YYYY-MM-DDTHH:MM:SS)
            timezone (Optional[str]): New timezone for the event
            attendees (Optional[List[str]]): Updated list of attendee email addresses
            notify_attendees (Optional[bool]): Whether to send email notifications to attendees (default: False)

        Returns:
            str: JSON string containing the updated Google Calendar event or error message
        """
        try:
            service = cast(Resource, self.service)

            # First get the existing event to preserve its structure
            event = service.events().get(calendarId=self.calendar_id, eventId=event_id).execute()

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
            if start_date:
                try:
                    start_time = datetime.datetime.fromisoformat(start_date).strftime("%Y-%m-%dT%H:%M:%S")
                    event["start"]["dateTime"] = start_time
                    if timezone:
                        event["start"]["timeZone"] = timezone
                except ValueError:
                    return json.dumps({"error": f"Invalid start datetime format: {start_date}. Use ISO format."})

            if end_date:
                try:
                    end_time = datetime.datetime.fromisoformat(end_date).strftime("%Y-%m-%dT%H:%M:%S")
                    event["end"]["dateTime"] = end_time
                    if timezone:
                        event["end"]["timeZone"] = timezone
                except ValueError:
                    return json.dumps({"error": f"Invalid end datetime format: {end_date}. Use ISO format."})

            # Determine sendUpdates value based on notify_attendees parameter
            send_updates = "all" if notify_attendees and attendees else "none"

            # Update the event

            updated_event = (
                service.events()
                .update(calendarId=self.calendar_id, eventId=event_id, body=event, sendUpdates=send_updates)
                .execute()
            )

            log_debug(f"Event {event_id} updated successfully.")
            return json.dumps(updated_event)
        except HttpError as error:
            log_error(f"An error occurred while updating event: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def delete_event(self, event_id: str, notify_attendees: Optional[bool] = True) -> str:
        """
        Delete an event from the Google Calendar.

        Args:
            event_id (str): ID of the event to delete
            notify_attendees (Optional[bool]): Whether to send email notifications to attendees (default: False)

        Returns:
            str: JSON string containing success message or error message
        """
        try:
            # Determine sendUpdates value based on notify_attendees parameter
            send_updates = "all" if notify_attendees else "none"

            service = cast(Resource, self.service)

            service.events().delete(calendarId=self.calendar_id, eventId=event_id, sendUpdates=send_updates).execute()

            log_debug(f"Event {event_id} deleted successfully.")
            return json.dumps({"success": True, "message": f"Event {event_id} deleted successfully."})
        except HttpError as error:
            log_error(f"An error occurred while deleting event: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def fetch_all_events(
        self,
        max_results: int = 10,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        """
        Fetch all Google Calendar events in a given date range.

        Args:
            start_date (Optional[str]): The minimum date to include events from in ISO format (YYYY-MM-DDTHH:MM:SS).
            end_date (Optional[str]): The maximum date to include events up to in ISO format (YYYY-MM-DDTHH:MM:SS).

        Returns:
            str: JSON string containing all Google Calendar events or error message
        """
        try:
            service = cast(Resource, self.service)

            params = {
                "calendarId": self.calendar_id,
                "maxResults": min(max_results, 100),
                "singleEvents": True,
                "orderBy": "startTime",
            }

            # Set time parameters if provided
            if start_date:
                # Accept both string and already formatted ISO strings
                if isinstance(start_date, str):
                    try:
                        # Try to parse and reformat to ensure proper timezone format
                        dt = datetime.datetime.fromisoformat(start_date)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=datetime.timezone.utc)
                        params["timeMin"] = dt.isoformat()
                    except ValueError:
                        # If it's already a valid ISO string, use it directly
                        params["timeMin"] = start_date
                else:
                    params["timeMin"] = start_date

            if end_date:
                # Accept both string and already formatted ISO strings
                if isinstance(end_date, str):
                    try:
                        # Try to parse and reformat to ensure proper timezone format
                        dt = datetime.datetime.fromisoformat(end_date)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=datetime.timezone.utc)
                        params["timeMax"] = dt.isoformat()
                    except ValueError:
                        # If it's already a valid ISO string, use it directly
                        params["timeMax"] = end_date
                else:
                    params["timeMax"] = end_date

            # Handle pagination
            all_events = []
            page_token = None

            while True:
                if page_token:
                    params["pageToken"] = page_token

                events_result = service.events().list(**params).execute()
                all_events.extend(events_result.get("items", []))

                page_token = events_result.get("nextPageToken")
                if not page_token:
                    break

            log_debug(f"Fetched {len(all_events)} events from calendar: {self.calendar_id}")

            if not all_events:
                return json.dumps({"message": "No events found."})
            return json.dumps(all_events)
        except HttpError as error:
            log_error(f"An error occurred while fetching events: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def find_available_slots(
        self,
        start_date: str,
        end_date: str,
        duration_minutes: int = 30,
    ) -> str:
        """
        Find available time slots within a date range.

        This method fetches your actual calendar events to determine busy periods,
        then finds available slots within standard working hours (9 AM - 5 PM).

        Args:
            start_date (str): Start date to search from in ISO format (YYYY-MM-DD)
            end_date (str): End date to search to in ISO format (YYYY-MM-DD)
            duration_minutes (int): Length of the desired slot in minutes (default: 30 minutes)

        Returns:
            str: JSON string containing available Google Calendar time slots or error message
        """
        try:
            start_dt = datetime.datetime.fromisoformat(start_date)
            end_dt = datetime.datetime.fromisoformat(end_date)
            # Ensure dates are timezone-aware (use UTC if no timezone specified)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=datetime.timezone.utc)

            # Get working hours from user settings
            working_hours_json = self._get_working_hours()
            working_hours_data = json.loads(working_hours_json)

            if "error" not in working_hours_data:
                working_hours_start = working_hours_data["start_hour"]
                working_hours_end = working_hours_data["end_hour"]
                timezone = working_hours_data["timezone"]
                locale = working_hours_data["locale"]
                log_debug(
                    f"Using working hours from settings: {working_hours_start}:00-{working_hours_end}:00 ({locale})"
                )
            else:
                # Fallback defaults
                working_hours_start, working_hours_end = 9, 17
                timezone = "UTC"
                locale = "en"
                log_debug("Using default working hours: 9:00-17:00")

            # Fetch actual calendar events to determine busy periods
            events_json = self.fetch_all_events(start_date=start_date, end_date=end_date)
            events_data = json.loads(events_json)

            if "error" in events_data:
                return json.dumps({"error": events_data["error"]})

            events = events_data if isinstance(events_data, list) else events_data.get("items", [])

            # Extract busy periods from actual calendar events
            busy_periods = []
            for event in events:
                # Skip all-day events and transparent events
                if event.get("transparency") == "transparent":
                    continue

                start_info = event.get("start", {})
                end_info = event.get("end", {})

                # Only process timed events (not all-day)
                if "dateTime" in start_info and "dateTime" in end_info:
                    try:
                        start_time = datetime.datetime.fromisoformat(start_info["dateTime"].replace("Z", "+00:00"))
                        end_time = datetime.datetime.fromisoformat(end_info["dateTime"].replace("Z", "+00:00"))
                        busy_periods.append((start_time, end_time))
                    except (ValueError, KeyError) as e:
                        log_debug(f"Skipping invalid event: {e}")
                        continue

            # Generate available slots within working hours
            available_slots = []
            current_date = start_dt.replace(hour=working_hours_start, minute=0, second=0, microsecond=0)
            end_search = end_dt.replace(hour=working_hours_end, minute=0, second=0, microsecond=0)

            while current_date <= end_search:
                # Skip weekends if not in working hours
                if current_date.weekday() >= 5:  # Saturday=5, Sunday=6
                    current_date = (current_date + datetime.timedelta(days=1)).replace(
                        hour=working_hours_start, minute=0, second=0, microsecond=0
                    )
                    continue

                slot_end = current_date + datetime.timedelta(minutes=duration_minutes)

                # Check if this slot conflicts with any busy period
                is_available = True
                for busy_start, busy_end in busy_periods:
                    if not (slot_end <= busy_start or current_date >= busy_end):
                        is_available = False
                        break

                # Only add slots within working hours
                if is_available and slot_end.hour <= working_hours_end:
                    available_slots.append({"start": current_date.isoformat(), "end": slot_end.isoformat()})

                # Move to next slot (30-minute intervals)
                current_date += datetime.timedelta(minutes=30)

                # Skip to next day at working hours start if past working hours end
                if current_date.hour >= working_hours_end:
                    current_date = (current_date + datetime.timedelta(days=1)).replace(
                        hour=working_hours_start, minute=0, second=0, microsecond=0
                    )

            result = {
                "available_slots": available_slots,
                "duration_minutes": duration_minutes,
                "working_hours": {"start": f"{working_hours_start:02d}:00", "end": f"{working_hours_end:02d}:00"},
                "timezone": timezone,
                "locale": locale,
                "events_analyzed": len(busy_periods),
            }

            log_debug(f"Found {len(available_slots)} available slots")
            return json.dumps(result)

        except Exception as e:
            log_error(f"An error occurred while finding available slots: {e}")
            return json.dumps({"error": f"An error occurred: {str(e)}"})

    @authenticate
    def _get_working_hours(self) -> str:
        """
        Get working hours based on user's calendar settings and locale.

        Returns:
            str: JSON string containing working hours information
        """
        try:
            # Get all user settings
            settings_result = self.service.settings().list().execute()  # type: ignore
            settings = settings_result.get("items", [])

            # Process settings into a more usable format
            user_prefs = {}
            for setting in settings:
                user_prefs[setting["id"]] = setting["value"]

            # Extract relevant settings
            timezone = user_prefs.get("timezone", "UTC")
            locale = user_prefs.get("locale", "en")
            week_start = int(user_prefs.get("weekStart", "0"))  # 0=Sunday, 1=Monday, 6=Saturday
            hide_weekends = user_prefs.get("hideWeekends", "false") == "true"

            # Determine working hours based on locale/culture
            if locale.startswith(("es", "it", "pt")):  # Spain, Italy, Portugal
                start_hour, end_hour = 9, 18
            elif locale.startswith(("de", "nl", "dk", "se", "no")):  # Northern Europe
                start_hour, end_hour = 8, 17
            elif locale.startswith(("ja", "ko")):  # East Asia
                start_hour, end_hour = 9, 18
            else:  # Default US/International
                start_hour, end_hour = 9, 17

            working_hours = {
                "start_hour": start_hour,
                "end_hour": end_hour,
                "start_time": f"{start_hour:02d}:00",
                "end_time": f"{end_hour:02d}:00",
                "timezone": timezone,
                "locale": locale,
                "week_start": week_start,
                "hide_weekends": hide_weekends,
            }

            log_debug(f"Working hours for locale {locale}: {start_hour}:00-{end_hour}:00")
            return json.dumps(working_hours)

        except HttpError as error:
            log_error(f"An error occurred while getting working hours: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def list_calendars(self) -> str:
        """
        List all available Google Calendars for the authenticated user.

        Returns:
            str: JSON string containing available calendars with their IDs and names
        """
        try:
            calendar_list = self.service.calendarList().list().execute()  # type: ignore
            calendars = calendar_list.get("items", [])

            all_calendars = []
            for calendar in calendars:
                calendar_info = {
                    "id": calendar.get("id"),
                    "name": calendar.get("summary", "Unnamed Calendar"),
                    "description": calendar.get("description", ""),
                    "primary": calendar.get("primary", False),
                    "access_role": calendar.get("accessRole", "unknown"),
                    "color": calendar.get("backgroundColor", "#ffffff"),
                }
                all_calendars.append(calendar_info)

            log_debug(f"Found {len(all_calendars)} calendars for user")
            return json.dumps(
                {
                    "calendars": all_calendars,
                    "current_default": self.calendar_id,
                }
            )

        except HttpError as error:
            log_error(f"An error occurred while listing calendars: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})
