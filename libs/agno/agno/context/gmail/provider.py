"""
Gmail Context Provider
======================

Read/write Gmail access via two tools:

- ``query_<id>`` — natural-language email reads (search, threads,
  message details, labels).
- ``update_<id>`` — natural-language writes (drafts, send, reply,
  label management).

Separate sub-agents keep each scope narrow. Reads get search and
message tools; writes get compose plus lookup tools.

**Auth methods:**

1. Service Account + domain-wide delegation (headless):
   - Set ``GOOGLE_SERVICE_ACCOUNT_FILE`` and ``GOOGLE_DELEGATED_USER``
   - Gmail requires ``delegated_user`` because service accounts have no inbox

2. OAuth (interactive, for personal Gmail):
   - Set ``GOOGLE_CLIENT_ID``, ``GOOGLE_CLIENT_SECRET``, ``GOOGLE_PROJECT_ID``
   - Opens browser on first use, caches token to ``gmail_token.json``
"""

from __future__ import annotations

from os import getenv
from typing import TYPE_CHECKING

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status
from agno.run import RunContext
from agno.tools.google.gmail import GmailTools

if TYPE_CHECKING:
    from agno.models.base import Model


DEFAULT_READ_INSTRUCTIONS = """\
You answer questions by searching and reading Gmail.

## Workflow
1. Search with relevant filters
2. Read full message content when details needed
3. Cite message IDs and thread IDs in responses
4. Read-only mode — no sending or modifications
"""

DEFAULT_WRITE_INSTRUCTIONS = """\
You manage Gmail — searching, reading, and writing emails.

## Workflow
- Search for context before composing (find the thread, verify recipients)
- If instruction is ambiguous, return what fields are missing
- Create drafts when user says "draft", send when user says "send"
- Use reply tools for thread responses, not new emails
"""


class GmailContextProvider(ContextProvider):
    """Gmail context for agents via service account or OAuth."""

    def __init__(
        self,
        *,
        service_account_path: str | None = None,
        delegated_user: str | None = None,
        credentials_path: str | None = None,
        token_path: str | None = None,
        id: str = "gmail",
        name: str = "Gmail",
        instructions: str | None = None,
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
        read: bool = True,
        write: bool = False,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model, read=read, write=write)

        # Resolve auth at init — fail fast if misconfigured
        self._sa_path = service_account_path or getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        self._credentials_path = credentials_path
        self._token_path = token_path or "gmail_token.json"
        self._delegated_user: str | None = None

        if self._sa_path:
            self._delegated_user = delegated_user or getenv("GOOGLE_DELEGATED_USER")
            if not self._delegated_user:
                raise ValueError(
                    "GmailContextProvider requires delegated_user with service account. "
                    "Gmail service accounts must impersonate a user via domain-wide delegation. "
                    "Set GOOGLE_DELEGATED_USER or pass delegated_user parameter."
                )

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
            return f"`{self.name}`: raw Gmail tools (read-only). Tool names may collide with other providers."
        tools = [self.query_tool_name]
        if self.write:
            tools.append(self.update_tool_name)
        return f"`{self.name}`: {', '.join(f'`{t}`' for t in tools)} for email operations."

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

    def _build_read_toolkit(self) -> GmailTools:
        return GmailTools(
            service_account_path=self._sa_path,
            delegated_user=self._delegated_user,
            credentials_path=self._credentials_path,
            token_path=self._token_path,
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            # Search and list
            get_latest_emails=True,
            get_emails_from_user=True,
            get_unread_emails=True,
            get_starred_emails=True,
            get_emails_by_context=True,
            get_emails_by_date=True,
            get_emails_by_thread=True,
            search_emails=True,
            # Message details
            get_message=True,
            get_thread=True,
            search_threads=True,
            # Labels and drafts (read-only)
            list_custom_labels=True,
            list_drafts=True,
            get_draft=True,
            # Disable all write operations
            mark_email_as_read=False,
            mark_email_as_unread=False,
            star_email=False,
            unstar_email=False,
            archive_email=False,
            create_draft_email=False,
            send_email=False,
            send_email_reply=False,
            apply_label=False,
            remove_label=False,
            delete_custom_label=False,
            modify_thread_labels=False,
            trash_thread=False,
            send_draft=False,
            update_draft=False,
            list_labels=False,
            modify_message_labels=False,
            trash_message=False,
            download_attachment=False,
        )

    def _build_write_toolkit(self) -> GmailTools:
        return GmailTools(
            service_account_path=self._sa_path,
            delegated_user=self._delegated_user,
            credentials_path=self._credentials_path,
            token_path=self._token_path,
            scopes=[
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/gmail.compose",
            ],
            # Lookup tools for grounding writes
            search_emails=True,
            search_threads=True,
            get_message=True,
            get_thread=True,
            list_custom_labels=True,
            # Compose and send
            create_draft_email=True,
            update_draft=True,
            send_email=True,
            send_email_reply=True,
            # Status management
            mark_email_as_read=True,
            mark_email_as_unread=True,
            star_email=True,
            unstar_email=True,
            # Label management
            apply_label=True,
            remove_label=True,
            # Disable unused read tools (write agent has minimal lookup)
            get_latest_emails=False,
            get_emails_from_user=False,
            get_unread_emails=False,
            get_starred_emails=False,
            get_emails_by_context=False,
            get_emails_by_date=False,
            get_emails_by_thread=False,
            list_drafts=False,
            get_draft=False,
            # Disable dangerous operations
            archive_email=False,
            delete_custom_label=False,
            modify_thread_labels=False,
            trash_thread=False,
            send_draft=False,
            list_labels=False,
            modify_message_labels=False,
            trash_message=False,
            download_attachment=False,
        )
