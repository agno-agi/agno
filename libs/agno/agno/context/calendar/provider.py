"""
Google Calendar Context Provider
================================

Read/write Calendar access for agents. Supports two auth methods:

1. Service Account + domain-wide delegation (headless, for bots):
   - Set GOOGLE_SERVICE_ACCOUNT_FILE and optionally GOOGLE_DELEGATED_USER
   - Without delegated_user, operates on the service account's own calendar

2. OAuth (interactive, for personal Calendar):
   - Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID
   - Opens browser on first use, caches token to calendar_token.json
"""

from __future__ import annotations

from os import getenv
from typing import TYPE_CHECKING

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status
from agno.run import RunContext
from agno.tools.google.calendar import GoogleCalendarTools

if TYPE_CHECKING:
    from agno.models.base import Model


DEFAULT_READ_INSTRUCTIONS = """\
You answer questions by searching and reading Google Calendar.

## Workflow
1. Search or list events matching the query
2. Fetch full event details when needed
3. Cite event IDs in responses
4. Read-only mode — no creating, updating, or deleting
"""

DEFAULT_WRITE_INSTRUCTIONS = """\
You manage Google Calendar — searching, reading, and modifying events.

## Workflow
- Look up event details before updating or deleting
- If instruction is ambiguous, return what fields are missing
- Set notify_attendees explicitly when modifying events with guests
- For updates, only specify fields that should change
"""


class CalendarContextProvider(ContextProvider):
    """Google Calendar context for agents via service account or OAuth."""

    def __init__(
        self,
        *,
        service_account_path: str | None = None,
        delegated_user: str | None = None,
        credentials_path: str | None = None,
        token_path: str | None = None,
        calendar_id: str = "primary",
        id: str = "calendar",
        name: str = "Calendar",
        instructions: str | None = None,
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

        self._read_instructions = instructions or DEFAULT_READ_INSTRUCTIONS
        self._write_instructions = instructions or DEFAULT_WRITE_INSTRUCTIONS
        self._read_agent: Agent | None = None
        self._write_agent: Agent | None = None

    def status(self) -> Status:
        # Toolkit handles actual auth validation
        mode = "service_account" if self._sa_path else "oauth"
        return Status(ok=True, detail=f"{self.id} ({mode})")

    async def astatus(self) -> Status:
        return self.status()

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
        return [self._build_read_toolkit()]

    def _ensure_read_agent(self) -> Agent:
        if self._read_agent is None:
            self._read_agent = Agent(
                id=f"{self.id}_read",
                name=f"{self.name} (read)",
                model=self.model,
                instructions=self._read_instructions,
                tools=[self._build_read_toolkit()],
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
                tools=[self._build_write_toolkit()],
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
            # Read operations
            list_events=True,
            get_event=True,
            fetch_all_events=True,
            find_available_slots=True,
            list_calendars=True,
            check_availability=True,
            get_event_attendees=True,
            search_events=True,
            # Disable all write operations
            create_event=False,
            update_event=False,
            delete_event=False,
            quick_add_event=False,
            move_event=False,
            respond_to_event=False,
        )

    def _build_write_toolkit(self) -> GoogleCalendarTools:
        return GoogleCalendarTools(
            service_account_path=self._sa_path,
            delegated_user=self._delegated_user,
            credentials_path=self._credentials_path,
            token_path=self._token_path,
            calendar_id=self._calendar_id,
            scopes=["https://www.googleapis.com/auth/calendar"],
            # Lookup tools for grounding writes
            list_events=True,
            get_event=True,
            search_events=True,
            check_availability=True,
            list_calendars=True,
            # Core write operations
            create_event=True,
            update_event=True,
            delete_event=True,
            # Excluded from defaults (risky or freeform)
            quick_add_event=False,
            move_event=False,
            respond_to_event=False,
            # Disable unused read tools
            fetch_all_events=False,
            find_available_slots=False,
            get_event_attendees=False,
        )
