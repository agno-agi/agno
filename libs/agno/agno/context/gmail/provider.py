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

import asyncio
from os import getenv
from typing import TYPE_CHECKING

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.context.google import validate_google_credentials
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status
from agno.run import RunContext
from agno.tools.google.gmail import GmailTools

if TYPE_CHECKING:
    from agno.models.base import Model


DEFAULT_READ_INSTRUCTIONS = """\
You answer questions by searching and reading Gmail.

## Tools available

- `search_emails(query)` — Gmail search syntax (see below)
- `get_message(message_id)` — full message content
- `get_thread(thread_id)` — all messages in a conversation
- `get_latest_emails(count)` — most recent emails
- `get_unread_emails(count)` — unread messages
- `get_emails_from_user(email)` — from a specific sender
- `list_custom_labels()` — user's Gmail labels

## Gmail search syntax

Use these operators in `search_emails(query="...")`:

- `from:alice@example.com` — from a sender
- `to:bob@example.com` — to a recipient
- `subject:meeting` — in subject line
- `has:attachment` — has attachments
- `is:unread` — unread messages
- `newer_than:7d` — last 7 days
- `older_than:1m` — older than 1 month
- `label:important` — has a label
- Combine with AND/OR: `from:alice subject:report newer_than:30d`

## Reading messages

1. **Start with search** to find relevant messages.
2. **Use `get_message`** for full content (body, attachments list).
3. **Use `get_thread`** to see the full conversation context.

## Citing results

- Include message IDs so the user can reference them.
- Quote the subject line and sender for clarity.
- For threads, mention how many messages are in the conversation.

**Read-only.** No sending, drafting, or modifying messages.
"""

DEFAULT_WRITE_INSTRUCTIONS = """\
You manage Gmail — searching, reading, and composing emails.

## Tools available

- `create_draft_email(to, subject, body, thread_id, message_id)` — save as draft
- `send_email(to, subject, body)` — send immediately
- `send_email_reply(message_id, body)` — reply in thread (sends immediately)
- `search_emails`, `get_message`, `get_thread` — for lookups
- `mark_email_as_read/unread`, `star_email/unstar_email` — status
- `apply_label`, `remove_label` — label management

## Before composing

1. **Search for context.** If replying, find the thread first with
   `search_emails` or `get_thread` to understand the conversation.

2. **Verify recipients.** If the user says "email Alice", search for
   recent emails from/to Alice to confirm the correct address.

## Composing emails

- **Draft vs Send:** Create drafts when user says "draft", "prepare",
  "write". Send immediately only when user explicitly says "send".

- **Draft replies:** To draft a reply (not send immediately), use
  `create_draft_email` with `thread_id` and `message_id` from the
  original message. This keeps the draft in the thread.

- **Send replies:** Use `send_email_reply(message_id, body)` to send
  a reply immediately. This keeps the message in the thread.

- **New emails:** Use `create_draft_email` or `send_email` without
  thread_id for new conversations.

- **Formatting:** Keep emails concise and professional unless the
  user specifies a tone. Use plain text; avoid excessive formatting.

## Managing messages

- Use `mark_email_as_read` after user reviews a message.
- Apply labels to help organize: `apply_label(message_id, "Follow-up")`.
- **Never archive or delete** without explicit user confirmation.
"""


class GmailContextProvider(ContextProvider):
    """Gmail context for agents via service account or OAuth."""

    def __init__(
        self,
        *,
        # Service account auth
        service_account_path: str | None = None,
        delegated_user: str | None = None,
        # OAuth auth (browser flow)
        credentials_path: str | None = None,  # OAuth client config (client_id/secret JSON)
        token_path: str | None = None,  # Cached user tokens after consent
        id: str = "gmail",
        name: str = "Gmail",
        read_instructions: str | None = None,
        write_instructions: str | None = None,
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

        self._read_instructions = read_instructions if read_instructions is not None else DEFAULT_READ_INSTRUCTIONS
        self._write_instructions = write_instructions if write_instructions is not None else DEFAULT_WRITE_INSTRUCTIONS
        self._read_toolkit: GmailTools | None = None
        self._write_toolkit: GmailTools | None = None
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
            return f"`{self.name}`: raw Gmail tools (read-only). Tool names may collide with other providers."
        tools = [self.query_tool_name]
        if self.write:
            tools.append(self.update_tool_name)
        return f"`{self.name}`: {', '.join(f'`{t}`' for t in tools)} for email operations."

    def _default_tools(self) -> list:
        return self._read_write_tools()

    def _all_tools(self) -> list:
        return [self._ensure_read_toolkit()]

    def _ensure_read_toolkit(self) -> GmailTools:
        if self._read_toolkit is None:
            self._read_toolkit = self._build_read_toolkit()
        return self._read_toolkit

    def _ensure_write_toolkit(self) -> GmailTools:
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

    def _build_read_toolkit(self) -> GmailTools:
        return GmailTools(
            service_account_path=self._sa_path,
            delegated_user=self._delegated_user,
            credentials_path=self._credentials_path,
            token_path=self._token_path,
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            # Disable write operations (these default to True)
            mark_email_as_read=False,
            mark_email_as_unread=False,
            star_email=False,
            unstar_email=False,
            create_draft_email=False,
            send_email=False,
            send_email_reply=False,
            apply_label=False,
            remove_label=False,
            delete_custom_label=False,
            update_draft=False,
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
            # Disable bulk read tools (write agent has minimal lookup)
            get_latest_emails=False,
            get_emails_from_user=False,
            get_unread_emails=False,
            get_starred_emails=False,
            get_emails_by_context=False,
            get_emails_by_date=False,
            get_emails_by_thread=False,
            list_drafts=False,
            get_draft=False,
            delete_custom_label=False,
        )
