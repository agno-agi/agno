"""
Google Calendar Context Provider
================================

Read/write Calendar access via two tools:

- ``query_<id>`` — natural-language calendar reads (list events,
  check availability, find free slots).
- ``update_<id>`` — natural-language writes (create, update, delete
  events).

Separate sub-agents keep each scope narrow. Reads get list/search
tools; writes get CRUD plus lookup tools.

**Auth methods:**

1. Service Account + domain-wide delegation (headless):
   - Set ``GOOGLE_SERVICE_ACCOUNT_FILE`` and optionally ``GOOGLE_DELEGATED_USER``
   - Without ``delegated_user``, operates on the service account's own calendar

2. OAuth (interactive, for personal Calendar):
   - Set ``GOOGLE_CLIENT_ID``, ``GOOGLE_CLIENT_SECRET``, ``GOOGLE_PROJECT_ID``
   - Opens browser on first use, caches token to ``calendar_token.json``
"""

from __future__ import annotations

import asyncio
from os import getenv
from typing import TYPE_CHECKING

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.context.google import validate_google_credentials
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status
from agno.run import RunContext
from agno.tools.google.calendar import GoogleCalendarTools

if TYPE_CHECKING:
    from agno.models.base import Model


DEFAULT_READ_INSTRUCTIONS = """\
You answer questions by searching and reading Google Calendar.

## Tools available

- `list_events(time_min, time_max)` — events in a date range
- `search_events(query)` — free-text search across event titles/descriptions
- `get_event(event_id)` — full details for one event
- `check_availability(time_min, time_max)` — busy/free slots
- `find_available_slots(...)` — suggest meeting times
- `list_calendars()` — all calendars the user can access

## Searching for events

1. **For "what's on my calendar today/this week"** — use `list_events`
   with appropriate `time_min` and `time_max` (ISO 8601 format).

2. **For "find meetings about X"** — use `search_events(query="X")`.

3. **For specific event details** — use `get_event(event_id)` after
   finding the event ID from a list or search.

## Time zones

- Always ask the user's timezone if not obvious from context.
- Return times in the user's local timezone, not UTC.
- When listing events, show both date and time clearly.

## Citing results

- Include event IDs so the user can reference them later.
- Link to the event's `htmlLink` when available.
- For recurring events, clarify which instance you're referring to.

**Read-only.** No creating, updating, or deleting events.
"""

DEFAULT_WRITE_INSTRUCTIONS = """\
You manage Google Calendar — searching, reading, and modifying events.

## Tools available

- `create_event(summary, start, end, ...)` — create new event
- `update_event(event_id, ...)` — modify existing event
- `delete_event(event_id)` — remove an event
- `list_events`, `search_events`, `get_event` — for lookups

## Before modifying

1. **Always look up first.** Use `get_event(event_id)` or `search_events`
   to confirm you have the right event before updating or deleting.

2. **Confirm ambiguous requests.** If the user says "move my meeting"
   but has multiple meetings, ask which one.

## Creating events

- **Required:** `summary`, `start`, `end` (ISO 8601 with timezone)
- **Optional:** `description`, `location`, `attendees`, `reminders`
- Always confirm the timezone with the user if not explicit.
- For all-day events, use date format (`2026-05-01`), not datetime.

## Updating events

- Only specify fields that should change — omit unchanged fields.
- For attendees: `notify_attendees=True` sends update emails (default).
  Set to `False` for minor changes that don't need notifications.

## Deleting events

- Confirm before deleting, especially for recurring events.
- For recurring events, clarify: delete this instance or all future?
"""


class GoogleCalendarContextProvider(ContextProvider):
    """Google Calendar context for agents via service account or OAuth."""

    def __init__(
        self,
        *,
        # Service account auth
        service_account_path: str | None = None,
        delegated_user: str | None = None,
        # OAuth auth (browser flow)
        credentials_path: str | None = None,  # OAuth client config (client_id/secret JSON)
        token_path: str | None = None,  # Cached user tokens after consent
        calendar_id: str = "primary",
        id: str = "calendar",
        name: str = "Calendar",
        read_instructions: str | None = None,
        write_instructions: str | None = None,
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
        read: bool = True,
        write: bool = False,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model, read=read, write=write)

        self._sa_path = service_account_path or getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        self._credentials_path = credentials_path
        self._token_path = token_path or "calendar_token.json"
        self._calendar_id = calendar_id
        # Calendar does NOT require delegated_user — SA can use its own calendar
        self._delegated_user = delegated_user or getenv("GOOGLE_DELEGATED_USER") if self._sa_path else None

        self._read_instructions = read_instructions if read_instructions is not None else DEFAULT_READ_INSTRUCTIONS
        self._write_instructions = write_instructions if write_instructions is not None else DEFAULT_WRITE_INSTRUCTIONS
        self._read_toolkit: GoogleCalendarTools | None = None
        self._write_toolkit: GoogleCalendarTools | None = None
        self._read_agent: Agent | None = None
        self._write_agent: Agent | None = None

    def status(self) -> Status:
        return validate_google_credentials(
            provider_id=self.id,
            sa_path=self._sa_path,
            token_path=self._token_path,
            delegated_user=self._delegated_user,
        )

    async def astatus(self) -> Status:
        return await asyncio.to_thread(self.status)

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(self._ensure_read_agent().run(question, **kwargs))

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(await self._ensure_read_agent().arun(question, **kwargs))

    def update(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(self._ensure_write_agent().run(instruction, **kwargs))

    async def aupdate(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(await self._ensure_write_agent().arun(instruction, **kwargs))

    def instructions(self) -> str:
        if self.mode == ContextMode.tools:
            return f"`{self.name}`: raw Calendar tools (read-only). Tool names may collide with other providers."
        tools = [self.query_tool_name]
        if self.write:
            tools.append(self.update_tool_name)
        return f"`{self.name}`: {', '.join(f'`{t}`' for t in tools)} for calendar operations."

    def _default_tools(self) -> list:
        return self._read_write_tools()

    def _all_tools(self) -> list:
        return [self._ensure_read_toolkit()]

    def _ensure_read_toolkit(self) -> GoogleCalendarTools:
        if self._read_toolkit is None:
            self._read_toolkit = self._build_read_toolkit()
        return self._read_toolkit

    def _ensure_write_toolkit(self) -> GoogleCalendarTools:
        if self._write_toolkit is None:
            self._write_toolkit = self._build_write_toolkit()
        return self._write_toolkit

    def _ensure_read_agent(self) -> Agent:
        if self._read_agent is None:
            self._read_agent = Agent(
                id=f"{self.id}_read",
                name=f"{self.name} (read)",
                model=self.model,
                instructions=self._read_instructions,
                tools=[self._ensure_read_toolkit()],
                markdown=True,
            )
        return self._read_agent

    def _ensure_write_agent(self) -> Agent:
        if self._write_agent is None:
            self._write_agent = Agent(
                id=f"{self.id}_write",
                name=f"{self.name} (write)",
                model=self.model,
                instructions=self._write_instructions,
                tools=[self._ensure_write_toolkit()],
                markdown=True,
            )
        return self._write_agent

    def _build_read_toolkit(self) -> GoogleCalendarTools:
        return GoogleCalendarTools(
            service_account_path=self._sa_path,
            delegated_user=self._delegated_user,
            credentials_path=self._credentials_path,
            token_path=self._token_path,
            calendar_id=self._calendar_id,
            scopes=["https://www.googleapis.com/auth/calendar.readonly"],
            # Disable write operations (these default to True)
            create_event=False,
            update_event=False,
            delete_event=False,
        )

    def _build_write_toolkit(self) -> GoogleCalendarTools:
        return GoogleCalendarTools(
            service_account_path=self._sa_path,
            delegated_user=self._delegated_user,
            credentials_path=self._credentials_path,
            token_path=self._token_path,
            calendar_id=self._calendar_id,
            scopes=["https://www.googleapis.com/auth/calendar"],
            # Disable bulk read tools — keep find_available_slots for scheduling
            fetch_all_events=False,
            get_event_attendees=False,
        )
