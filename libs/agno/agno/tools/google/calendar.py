import datetime
import json
import textwrap
import uuid
from os import getenv
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, cast

from agno.tools import Toolkit
from agno.tools.google.auth import google_authenticate
from agno.utils.log import log_debug, log_error, log_info

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import Resource, build
    from googleapiclient.errors import HttpError
except ImportError:
    raise ImportError(
        "Google client libraries not found. Install using "
        "`pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )


CALENDAR_INSTRUCTIONS = textwrap.dedent("""\
    You have access to Google Calendar tools for managing events and scheduling.

    ## Date/Time Formats
    - All dates use ISO format: YYYY-MM-DDTHH:MM:SS
    - Always specify timezone when creating events

    ## Tips
    - Use get_event to fetch full details before updating an event
    - Use check_availability to check multiple people's schedules at once
    - Use quick_add_event for simple events from natural language descriptions
    - Use search_events for full-text search across event fields
    - Event IDs from list_events can be used with get_event, update_event, delete_event""")


authenticate = google_authenticate("calendar")


class GoogleCalendarTools(Toolkit):
    DEFAULT_SCOPES = [
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar",
    ]

    def __init__(
        self,
        creds: Optional[Union[Credentials, ServiceAccountCredentials]] = None,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = "token.json",
        service_account_path: Optional[str] = None,
        delegated_user: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        oauth_port: int = 8080,
        login_hint: Optional[str] = None,
        calendar_id: str = "primary",
        allow_update: Optional[bool] = None,
        list_events: bool = True,
        get_event: bool = True,
        fetch_all_events: bool = True,
        find_available_slots: bool = True,
        list_calendars: bool = True,
        check_availability: bool = True,
        get_event_attendees: bool = True,
        search_events: bool = True,
        create_event: bool = True,
        update_event: bool = True,
        delete_event: bool = True,
        quick_add_event: bool = False,
        move_event: bool = False,
        respond_to_event: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs,
    ):
        """Initialize GoogleCalendarTools with authentication and tool selection.

        Args:
            creds: Pre-fetched credentials to skip a new auth flow.
            credentials_path: Path to OAuth credentials JSON file.
            token_path: Path to cached token file. Created on first auth.
            service_account_path: Path to service account JSON key. When set, OAuth is skipped.
            delegated_user: Email to impersonate via domain-wide delegation. Optional for Calendar.
            scopes: Custom OAuth scopes. If None, uses DEFAULT_SCOPES.
            oauth_port: Port for OAuth local redirect server (default: 8080).
            login_hint: Email to pre-select in the OAuth consent screen.
            calendar_id: Calendar to operate on. Defaults to "primary".
            instructions: Custom instructions for the toolkit. If None, uses default.
            add_instructions: Whether to inject instructions into the agent system prompt.
        """
        if allow_update:
            create_event = True
            update_event = True
            delete_event = True

        if instructions is None:
            self.instructions = CALENDAR_INSTRUCTIONS
        else:
            self.instructions = instructions

        self.creds = creds
        self.service: Optional[Resource] = None
        self.calendar_id = calendar_id
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service_account_path = service_account_path
        self.delegated_user = delegated_user
        self.scopes = scopes or self.DEFAULT_SCOPES
        self.oauth_port = oauth_port
        self.login_hint = login_hint
        # Cached email for respond_to_event
        self._user_email: Optional[str] = None
        tools: List[Any] = []

        if list_events:
            tools.append(self.list_events)
        if get_event:
            tools.append(self.get_event)
        if fetch_all_events:
            tools.append(self.fetch_all_events)
        if find_available_slots:
            tools.append(self.find_available_slots)
        if list_calendars:
            tools.append(self.list_calendars)
        if check_availability:
            tools.append(self.check_availability)
        if get_event_attendees:
            tools.append(self.get_event_attendees)
        if search_events:
            tools.append(self.search_events)

        if create_event:
            tools.append(self.create_event)
        if update_event:
            tools.append(self.update_event)
        if delete_event:
            tools.append(self.delete_event)
        if quick_add_event:
            tools.append(self.quick_add_event)
        if move_event:
            tools.append(self.move_event)
        if respond_to_event:
            tools.append(self.respond_to_event)

        super().__init__(
            name="google_calendar_tools",
            tools=tools,
            instructions=self.instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

        # Validate that required scopes cover registered tools
        write_tools = {
            "create_event",
            "update_event",
            "delete_event",
            "quick_add_event",
            "move_event",
            "respond_to_event",
        }
        if any(t in self.functions for t in write_tools):
            if "https://www.googleapis.com/auth/calendar" not in self.scopes:
                raise ValueError("The scope https://www.googleapis.com/auth/calendar is required for write operations")

        read_tools = {
            "list_events",
            "get_event",
            "fetch_all_events",
            "find_available_slots",
            "list_calendars",
            "check_availability",
            "get_event_attendees",
            "search_events",
        }
        if any(t in self.functions for t in read_tools):
            # Write scope is a superset of read — either satisfies read operations
            read_scope = "https://www.googleapis.com/auth/calendar.readonly"
            write_scope = "https://www.googleapis.com/auth/calendar"
            if read_scope not in self.scopes and write_scope not in self.scopes:
                raise ValueError(f"The scope {read_scope} is required for read operations")

    def _build_service(self):
        return build("calendar", "v3", credentials=self.creds)

    def _auth(self) -> None:
        """Authenticate with Google Calendar API using service account (priority) or OAuth flow."""
        if self.creds and self.creds.valid:
            return

        # Service account authentication takes priority over OAuth
        service_account_path = self.service_account_path or getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        if service_account_path:
            delegated_user = self.delegated_user or getenv("GOOGLE_DELEGATED_USER")
            sa_creds = ServiceAccountCredentials.from_service_account_file(
                service_account_path,
                scopes=self.scopes,
            )
            # Calendar service accounts can optionally impersonate a user
            if delegated_user:
                sa_creds = sa_creds.with_subject(delegated_user)
            # Eagerly fetch token so creds.valid=True and @authenticate won't re-enter _auth
            sa_creds.refresh(Request())
            self.creds = sa_creds
            return

        # OAuth flow
        token_file = Path(self.token_path or "token.json")
        creds_file = Path(self.credentials_path or "credentials.json")

        if token_file.exists():
            try:
                self.creds = Credentials.from_authorized_user_file(str(token_file), self.scopes)
            except ValueError:
                # Token file missing refresh_token — fall through to re-auth
                self.creds = None

        if self.creds and self.creds.expired and self.creds.refresh_token:  # type: ignore[union-attr]
            try:
                self.creds.refresh(Request())
            except Exception:
                # Refresh token revoked or expired — fall through to re-auth
                self.creds = None

        if not self.creds or not self.creds.valid:
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
            if creds_file.exists():
                flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), self.scopes)
            else:
                flow = InstalledAppFlow.from_client_config(client_config, self.scopes)
            # prompt=consent forces Google to return a refresh_token every time
            oauth_kwargs: Dict[str, Any] = {"prompt": "consent"}
            if self.login_hint:
                oauth_kwargs["login_hint"] = self.login_hint
            oauth_kwargs["port"] = self.oauth_port
            self.creds = flow.run_local_server(**oauth_kwargs)

        # Save the credentials for future use
        if self.creds and self.creds.valid:
            token_file.write_text(self.creds.to_json())  # type: ignore[union-attr]
            log_debug("Successfully authenticated with Google Calendar API.")
            log_info(f"Token file path: {token_file}")

    @authenticate
    def list_events(self, limit: int = 10, start_date: Optional[str] = None) -> str:
        """
        List upcoming events from the user's Google Calendar.

        Args:
            limit (int): Number of events to return (default: 10)
            start_date (Optional[str]): Start date in ISO format (YYYY-MM-DDTHH:MM:SS). Defaults to now.

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
            start_date (str): Start date and time in ISO format (YYYY-MM-DDTHH:MM:SS)
            end_date (str): End date and time in ISO format (YYYY-MM-DDTHH:MM:SS)
            title (Optional[str]): Title/summary of the event
            description (Optional[str]): Detailed description of the event
            location (Optional[str]): Location of the event
            timezone (Optional[str]): Timezone for the event (default: UTC)
            attendees (Optional[List[str]]): List of attendee email addresses
            add_google_meet_link (Optional[bool]): Whether to add a Google Meet video link
            notify_attendees (Optional[bool]): Whether to send email notifications to attendees

        Returns:
            str: JSON string containing the created event or error message
        """
        try:
            attendees_list = [{"email": attendee} for attendee in attendees] if attendees else []

            try:
                start_time = datetime.datetime.fromisoformat(start_date).strftime("%Y-%m-%dT%H:%M:%S")
                end_time = datetime.datetime.fromisoformat(end_date).strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                return json.dumps({"error": "Invalid datetime format. Use ISO format (YYYY-MM-DDTHH:MM:SS)."})

            event: Dict[str, Any] = {
                "summary": title,
                "location": location,
                "description": description,
                "start": {"dateTime": start_time, "timeZone": timezone},
                "end": {"dateTime": end_time, "timeZone": timezone},
                "attendees": attendees_list,
            }

            if add_google_meet_link:
                event["conferenceData"] = {
                    "createRequest": {"requestId": str(uuid.uuid4()), "conferenceSolutionKey": {"type": "hangoutsMeet"}}
                }

            # Remove None values
            event = {k: v for k, v in event.items() if v is not None}

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
            title (Optional[str]): New title/summary
            description (Optional[str]): New description
            location (Optional[str]): New location
            start_date (Optional[str]): New start date/time in ISO format
            end_date (Optional[str]): New end date/time in ISO format
            timezone (Optional[str]): New timezone
            attendees (Optional[List[str]]): Updated list of attendee email addresses
            notify_attendees (Optional[bool]): Whether to send email notifications

        Returns:
            str: JSON string containing the updated event or error message
        """
        try:
            service = cast(Resource, self.service)
            event = service.events().get(calendarId=self.calendar_id, eventId=event_id).execute()

            if title is not None:
                event["summary"] = title
            if description is not None:
                event["description"] = description
            if location is not None:
                event["location"] = location
            if attendees is not None:
                event["attendees"] = [{"email": attendee} for attendee in attendees]

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

            send_updates = "all" if notify_attendees and attendees else "none"

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
            notify_attendees (Optional[bool]): Whether to send notifications to attendees (default: True)

        Returns:
            str: JSON string containing success or error message
        """
        try:
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
        Paginates through results automatically to retrieve every matching event.

        Args:
            max_results (int): Number of events to fetch per page (default: 10, max: 100)
            start_date (Optional[str]): Start of range in ISO format (YYYY-MM-DDTHH:MM:SS)
            end_date (Optional[str]): End of range in ISO format (YYYY-MM-DDTHH:MM:SS)

        Returns:
            str: JSON string containing all events or error message
        """
        try:
            service = cast(Resource, self.service)

            params: Dict[str, Any] = {
                "calendarId": self.calendar_id,
                "maxResults": min(max_results, 100),
                "singleEvents": True,
                "orderBy": "startTime",
            }

            if start_date:
                if isinstance(start_date, str):
                    try:
                        dt = datetime.datetime.fromisoformat(start_date)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=datetime.timezone.utc)
                        params["timeMin"] = dt.isoformat()
                    except ValueError:
                        params["timeMin"] = start_date
                else:
                    params["timeMin"] = start_date

            if end_date:
                if isinstance(end_date, str):
                    try:
                        dt = datetime.datetime.fromisoformat(end_date)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=datetime.timezone.utc)
                        params["timeMax"] = dt.isoformat()
                    except ValueError:
                        params["timeMax"] = end_date
                else:
                    params["timeMax"] = end_date

            all_events: List[Any] = []
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
        Find available time slots within a date range based on your calendar.
        Checks existing events against working hours to find free windows.

        Args:
            start_date (str): Start date in ISO format (YYYY-MM-DD)
            end_date (str): End date in ISO format (YYYY-MM-DD)
            duration_minutes (int): Length of the desired slot in minutes (default: 30)

        Returns:
            str: JSON string containing available time slots or error message
        """
        try:
            start_dt = datetime.datetime.fromisoformat(start_date)
            end_dt = datetime.datetime.fromisoformat(end_date)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=datetime.timezone.utc)

            working_hours_json = self._get_working_hours()
            working_hours_data = json.loads(working_hours_json)

            if "error" not in working_hours_data:
                working_hours_start = working_hours_data["start_hour"]
                working_hours_end = working_hours_data["end_hour"]
                tz = working_hours_data["timezone"]
                locale = working_hours_data["locale"]
                log_debug(
                    f"Using working hours from settings: {working_hours_start}:00-{working_hours_end}:00 ({locale})"
                )
            else:
                working_hours_start, working_hours_end = 9, 17
                tz = "UTC"
                locale = "en"
                log_debug("Using default working hours: 9:00-17:00")

            events_json = self.fetch_all_events(start_date=start_date, end_date=end_date)
            events_data = json.loads(events_json)

            if isinstance(events_data, dict) and "error" in events_data:
                return json.dumps({"error": events_data["error"]})

            events = events_data if isinstance(events_data, list) else events_data.get("items", [])

            busy_periods = []
            for event in events:
                if event.get("transparency") == "transparent":
                    continue
                start_info = event.get("start", {})
                end_info = event.get("end", {})
                if "dateTime" in start_info and "dateTime" in end_info:
                    try:
                        s = datetime.datetime.fromisoformat(start_info["dateTime"].replace("Z", "+00:00"))
                        e = datetime.datetime.fromisoformat(end_info["dateTime"].replace("Z", "+00:00"))
                        busy_periods.append((s, e))
                    except (ValueError, KeyError) as err:
                        log_debug(f"Skipping invalid event: {err}")

            available_slots = []
            current = start_dt.replace(hour=working_hours_start, minute=0, second=0, microsecond=0)
            end_search = end_dt.replace(hour=working_hours_end, minute=0, second=0, microsecond=0)

            while current <= end_search:
                if current.weekday() >= 5:
                    current = (current + datetime.timedelta(days=1)).replace(
                        hour=working_hours_start, minute=0, second=0, microsecond=0
                    )
                    continue

                slot_end = current + datetime.timedelta(minutes=duration_minutes)

                is_available = True
                for busy_start, busy_end in busy_periods:
                    if not (slot_end <= busy_start or current >= busy_end):
                        is_available = False
                        break

                if is_available and slot_end.hour <= working_hours_end:
                    available_slots.append({"start": current.isoformat(), "end": slot_end.isoformat()})

                current += datetime.timedelta(minutes=30)

                if current.hour >= working_hours_end:
                    current = (current + datetime.timedelta(days=1)).replace(
                        hour=working_hours_start, minute=0, second=0, microsecond=0
                    )

            result = {
                "available_slots": available_slots,
                "duration_minutes": duration_minutes,
                "working_hours": {"start": f"{working_hours_start:02d}:00", "end": f"{working_hours_end:02d}:00"},
                "timezone": tz,
                "locale": locale,
                "events_analyzed": len(busy_periods),
            }

            log_debug(f"Found {len(available_slots)} available slots")
            return json.dumps(result)

        except Exception as e:
            log_error(f"An error occurred while finding available slots: {str(e)}")
            return json.dumps({"error": f"An error occurred: {str(e)}"})

    @authenticate
    def _get_working_hours(self) -> str:
        """Get working hours based on user's calendar settings and locale.

        Returns:
            str: JSON string containing working hours information
        """
        try:
            settings_result = self.service.settings().list().execute()  # type: ignore
            settings = settings_result.get("items", [])

            user_prefs = {}
            for setting in settings:
                user_prefs[setting["id"]] = setting["value"]

            tz = user_prefs.get("timezone", "UTC")
            locale = user_prefs.get("locale", "en")
            week_start = int(user_prefs.get("weekStart", "0"))
            hide_weekends = user_prefs.get("hideWeekends", "false") == "true"

            if locale.startswith(("es", "it", "pt")):
                start_hour, end_hour = 9, 18
            elif locale.startswith(("de", "nl", "dk", "se", "no")):
                start_hour, end_hour = 8, 17
            elif locale.startswith(("ja", "ko")):
                start_hour, end_hour = 9, 18
            else:
                start_hour, end_hour = 9, 17

            return json.dumps(
                {
                    "start_hour": start_hour,
                    "end_hour": end_hour,
                    "start_time": f"{start_hour:02d}:00",
                    "end_time": f"{end_hour:02d}:00",
                    "timezone": tz,
                    "locale": locale,
                    "week_start": week_start,
                    "hide_weekends": hide_weekends,
                }
            )

        except HttpError as error:
            log_error(f"An error occurred while getting working hours: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def list_calendars(self) -> str:
        """
        List all available Google Calendars for the authenticated user.

        Returns:
            str: JSON string containing available calendars with their IDs, names, and access roles
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

    @authenticate
    def get_event(self, event_id: str) -> str:
        """
        Get full details of a single Google Calendar event by its ID.

        Args:
            event_id (str): The unique identifier of the event

        Returns:
            str: JSON string with full event details
        """
        try:
            service = cast(Resource, self.service)
            event = service.events().get(calendarId=self.calendar_id, eventId=event_id).execute()
            return json.dumps(event)
        except HttpError as error:
            log_error(f"An error occurred while getting event: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def quick_add_event(self, text: str) -> str:
        """
        Create a Google Calendar event from a natural language description.
        Examples: "Meeting with John tomorrow 3pm", "Lunch at noon on Friday"

        Args:
            text (str): Natural language description of the event including date, time, and title

        Returns:
            str: JSON string containing the created event or error message
        """
        try:
            service = cast(Resource, self.service)
            event = service.events().quickAdd(calendarId=self.calendar_id, text=text).execute()
            log_debug(f"Quick add event created: {event.get('id')}")
            return json.dumps(event)
        except HttpError as error:
            log_error(f"An error occurred while quick-adding event: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def check_availability(
        self,
        start_date: str,
        end_date: str,
        attendee_emails: Optional[List[str]] = None,
        timezone: Optional[str] = None,
    ) -> str:
        """
        Check availability of one or more people within a time window.
        Returns busy time ranges for each attendee.
        Use "me" or omit attendee_emails to check the authenticated user's own calendar.

        Args:
            start_date (str): Start of the time window in ISO format (YYYY-MM-DDTHH:MM:SS)
            end_date (str): End of the time window in ISO format (YYYY-MM-DDTHH:MM:SS)
            attendee_emails (Optional[List[str]]): Email addresses to check availability for. Defaults to the authenticated user's calendar if not provided. Use "me" for the authenticated user alongside other emails.
            timezone (Optional[str]): Timezone for the query (default: UTC)

        Returns:
            str: JSON string with busy periods for each attendee
        """
        try:
            # Default to authenticated user's primary calendar
            resolved = [("primary" if e in ("me", "primary") else e) for e in (attendee_emails or ["me"])]

            try:
                start_dt = datetime.datetime.fromisoformat(start_date)
                end_dt = datetime.datetime.fromisoformat(end_date)
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=datetime.timezone.utc)
            except ValueError:
                return json.dumps({"error": "Invalid date format. Use ISO format (YYYY-MM-DDTHH:MM:SS)."})

            body = {
                "timeMin": start_dt.isoformat(),
                "timeMax": end_dt.isoformat(),
                "timeZone": timezone or "UTC",
                "items": [{"id": cal_id} for cal_id in resolved],
            }

            service = cast(Resource, self.service)
            result = service.freebusy().query(body=body).execute()

            calendars = result.get("calendars", {})
            availability: Dict[str, Any] = {}
            for cal_id in resolved:
                cal_data = calendars.get(cal_id, {})
                busy = cal_data.get("busy", [])
                errors = cal_data.get("errors", [])
                # Label as "me" in output when checking own calendar
                label = "me" if cal_id == "primary" else cal_id
                availability[label] = {
                    "busy_periods": busy,
                    "is_free": len(busy) == 0 and len(errors) == 0,
                }
                if errors:
                    availability[label]["errors"] = errors

            log_debug(f"Checked availability for {len(resolved)} attendees")
            return json.dumps(
                {
                    "availability": availability,
                    "time_window": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
                    "timezone": timezone or "UTC",
                }
            )
        except HttpError as error:
            log_error(f"An error occurred while checking availability: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def search_events(
        self,
        query: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_results: int = 10,
    ) -> str:
        """
        Search Google Calendar events by text across summary, description, location, and attendees.
        Unlike list_events which returns upcoming events, this performs full-text search.

        Args:
            query (str): Free-text search terms
            start_date (Optional[str]): Start of search window in ISO format
            end_date (Optional[str]): End of search window in ISO format
            max_results (int): Maximum number of events to return (default: 10)

        Returns:
            str: JSON string containing matching events or error message
        """
        try:
            service = cast(Resource, self.service)

            params: Dict[str, Any] = {
                "calendarId": self.calendar_id,
                "q": query,
                "maxResults": min(max_results, 100),
                "singleEvents": True,
                "orderBy": "startTime",
            }

            if start_date:
                try:
                    dt = datetime.datetime.fromisoformat(start_date)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=datetime.timezone.utc)
                    params["timeMin"] = dt.isoformat()
                except ValueError:
                    params["timeMin"] = start_date

            if end_date:
                try:
                    dt = datetime.datetime.fromisoformat(end_date)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=datetime.timezone.utc)
                    params["timeMax"] = dt.isoformat()
                except ValueError:
                    params["timeMax"] = end_date

            events_result = service.events().list(**params).execute()
            events = events_result.get("items", [])

            if not events:
                return json.dumps({"message": f"No events found matching '{query}'."})

            log_debug(f"Found {len(events)} events matching '{query}'")
            return json.dumps(events)
        except HttpError as error:
            log_error(f"An error occurred while searching events: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def move_event(
        self,
        event_id: str,
        destination_calendar_id: str,
        notify_attendees: Optional[bool] = False,
    ) -> str:
        """
        Move a Google Calendar event to a different calendar.

        Args:
            event_id (str): ID of the event to move
            destination_calendar_id (str): ID of the target calendar
            notify_attendees (Optional[bool]): Whether to notify attendees of the move

        Returns:
            str: JSON string containing the moved event or error message
        """
        try:
            send_updates = "all" if notify_attendees else "none"
            service = cast(Resource, self.service)
            moved_event = (
                service.events()
                .move(
                    calendarId=self.calendar_id,
                    eventId=event_id,
                    destination=destination_calendar_id,
                    sendUpdates=send_updates,
                )
                .execute()
            )
            log_debug(f"Event {event_id} moved to calendar {destination_calendar_id}")
            return json.dumps(moved_event)
        except HttpError as error:
            log_error(f"An error occurred while moving event: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def get_event_attendees(self, event_id: str) -> str:
        """
        Get the attendee list and their RSVP statuses for a Google Calendar event.

        Args:
            event_id (str): ID of the event

        Returns:
            str: JSON string with attendees, their emails, names, and response statuses
                 (accepted, declined, tentative, needsAction)
        """
        try:
            service = cast(Resource, self.service)
            event = service.events().get(calendarId=self.calendar_id, eventId=event_id).execute()
            attendees = event.get("attendees", [])

            attendee_list = []
            for attendee in attendees:
                attendee_list.append(
                    {
                        "email": attendee.get("email"),
                        "name": attendee.get("displayName", ""),
                        "response_status": attendee.get("responseStatus", "needsAction"),
                        "organizer": attendee.get("organizer", False),
                        "optional": attendee.get("optional", False),
                    }
                )

            return json.dumps(
                {
                    "event_id": event_id,
                    "event_summary": event.get("summary", ""),
                    "attendees": attendee_list,
                    "total": len(attendee_list),
                }
            )
        except HttpError as error:
            log_error(f"An error occurred while getting attendees: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def respond_to_event(self, event_id: str, response: str) -> str:
        """
        Set the authenticated user's attendance response for a Google Calendar event.

        Args:
            event_id (str): ID of the event
            response (str): Response status - one of "accepted", "declined", or "tentative"

        Returns:
            str: JSON string containing the updated event or error message
        """
        valid_responses = {"accepted", "declined", "tentative"}
        if response not in valid_responses:
            return json.dumps({"error": f"Invalid response '{response}'. Must be one of: {', '.join(valid_responses)}"})

        try:
            service = cast(Resource, self.service)

            # Get authenticated user's email (cached)
            if not self._user_email:
                cal = service.calendarList().get(calendarId="primary").execute()
                self._user_email = cal.get("id")

            event = service.events().get(calendarId=self.calendar_id, eventId=event_id).execute()
            attendees = event.get("attendees", [])

            found = False
            for attendee in attendees:
                if attendee.get("email") == self._user_email:
                    attendee["responseStatus"] = response
                    found = True
                    break

            if not found:
                # User not in attendees — add them with the response
                attendees.append({"email": self._user_email, "responseStatus": response})
                event["attendees"] = attendees

            updated_event = (
                service.events()
                .patch(
                    calendarId=self.calendar_id,
                    eventId=event_id,
                    body={"attendees": attendees},
                    sendUpdates="all",
                )
                .execute()
            )

            log_debug(f"Responded '{response}' to event {event_id}")
            return json.dumps(updated_event)
        except HttpError as error:
            log_error(f"An error occurred while responding to event: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})
