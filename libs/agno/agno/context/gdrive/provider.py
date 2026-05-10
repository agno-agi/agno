"""
Google Drive Context Provider
=============================

Read-only Google Drive access via a single tool:

- ``query_<id>`` — natural-language file reads (list, search, read
  file contents).

A sub-agent handles Drive query syntax and file navigation. Read-only
by default; uploads/downloads are disabled.

**Auth methods:**

1. Service Account (headless):
   - Set ``GOOGLE_SERVICE_ACCOUNT_FILE`` or pass ``service_account_path``
   - Share folders with the service account email

2. OAuth (interactive, for personal Drive):
   - Set ``GOOGLE_CLIENT_ID``, ``GOOGLE_CLIENT_SECRET``, ``GOOGLE_PROJECT_ID``
   - Or pass ``credentials_path`` / ``token_path`` directly
   - Opens browser on first use, caches token to ``gdrive_token.json``

**Search scope (Shared Drive support):**

By default uses ``corpora="allDrives"`` so service accounts can see files
inside shared folders and Shared Drives. Customize with:

- ``corpora="user"`` — personal Drive only (My Drive + Shared with me)
- ``corpora="domain"`` — all files shared to user's domain
- ``corpora="drive"`` + ``drive_id="..."`` — single Shared Drive
- ``corpora="allDrives"`` — everything (default)

When using non-"user" corpora, set ``supports_all_drives=True`` and
``include_items_from_all_drives=True`` (both default to True).
"""

from __future__ import annotations

import asyncio
from os import getenv
from typing import TYPE_CHECKING

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.tools.google.drive import GoogleDriveTools
from agno.context.google import validate_google_credentials
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status
from agno.run import RunContext

if TYPE_CHECKING:
    from agno.models.base import Model


class GoogleDriveContextProvider(ContextProvider):
    """Read-only Google Drive access via service account or OAuth."""

    def __init__(
        self,
        *,
        service_account_path: str | None = None,  # SA JSON key file
        credentials_path: str | None = None,  # OAuth client config (client_id/secret JSON)
        token_path: str | None = None,  # Cached OAuth tokens after consent
        # Shared Drive support — passthrough to GoogleDriveTools
        corpora: str = "allDrives",  # "user" | "domain" | "drive" | "allDrives"
        supports_all_drives: bool = True,
        include_items_from_all_drives: bool = True,
        drive_id: str | None = None,  # Required when corpora="drive"
        id: str = "gdrive",
        name: str = "Google Drive",
        instructions: str | None = None,
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model)

        # Store params — toolkit handles actual auth
        self._sa_path = service_account_path or getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        self._credentials_path = credentials_path
        self._token_path = token_path or "gdrive_token.json"
        self._corpora = corpora
        self._supports_all_drives = supports_all_drives
        self._include_items_from_all_drives = include_items_from_all_drives
        self._drive_id = drive_id

        self.instructions_text = instructions if instructions is not None else DEFAULT_GDRIVE_INSTRUCTIONS
        self._tools: GoogleDriveTools | None = None
        self._agent: Agent | None = None

    def status(self) -> Status:
        return validate_google_credentials(
            provider_id=self.id,
            sa_path=self._sa_path,
            token_path=self._token_path,
        )

    async def astatus(self) -> Status:
        return await asyncio.to_thread(self.status)

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(self._ensure_agent().run(question, **kwargs))

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(await self._ensure_agent().arun(question, **kwargs))

    def instructions(self) -> str:
        if self.mode == ContextMode.tools:
            return (
                f"`{self.name}`: `search_files(query)` or `list_files(query)` with Drive query syntax "
                "(e.g. `name contains 'roadmap'`, `mimeType = 'application/vnd.google-apps.document'`). "
                "Then `read_file(file_id)` to read contents. Read-only. Note: these share tool names "
                "with other providers — mode=tools only works in isolation."
            )
        return (
            f"`{self.name}`: call `{self.query_tool_name}(question)` to query Google Drive — "
            "searches by name, mimeType, modifiedTime, etc., and returns matches with webViewLinks."
        )

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    # Wrap in a `query_gdrive` sub-agent because `GoogleDriveTools` exposes
    # `list_files` / `search_files` / `read_file` — names that collide with
    # `FileTools`, and agno's tool resolver dedupes by name across the whole
    # list (silently dropping the second toolkit). mode=tools only works when
    # Drive is the sole file-like provider.
    def _default_tools(self) -> list:
        return [self._query_tool()]

    def _all_tools(self) -> list:
        return [self._ensure_tools()]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_tools(self) -> GoogleDriveTools:
        if self._tools is None:
            self._tools = GoogleDriveTools(
                service_account_path=self._sa_path,
                creds_path=self._credentials_path,
                token_path=self._token_path,
                corpora=self._corpora,
                supports_all_drives=self._supports_all_drives,
                include_items_from_all_drives=self._include_items_from_all_drives,
                drive_id=self._drive_id,
            )
        return self._tools

    def _ensure_agent(self) -> Agent:
        if self._agent is None:
            self._agent = self._build_agent()
        return self._agent

    def _build_agent(self) -> Agent:
        return Agent(
            id=self.id,
            name=self.name,
            model=self.model,
            instructions=self.instructions_text,
            tools=[self._ensure_tools()],
            markdown=True,
        )


DEFAULT_GDRIVE_INSTRUCTIONS = """\
You answer questions by searching and reading Google Drive.

You authenticate as a *service account*, not an end user. The owner
shares folders (or individual files) with the SA email; `sharedWithMe`
is set on the shared *root* but NOT on files inside a shared folder.
So a bare `name contains '...'` search will miss files inside shared
folders. Always escalate when the first search comes back empty.

## Search workflow (escalate on empty)

1. **First try a bare name search.**
   `search_files(query="name contains 'X'")`
   — catches files directly owned by the SA, or files the SA can
   reach via an ancestor shared with it.

2. **If step 1 returns zero results, search shared items.**
   `search_files(query="sharedWithMe and name contains 'X'")`
   — catches files + folders shared with the SA directly. The folder
   itself is here even if its contents aren't.

3. **If step 2 still returns zero, traverse shared folders.**
   a. `search_files(query="mimeType = 'application/vnd.google-apps.folder' and sharedWithMe")`
      — enumerate every folder shared with the SA.
   b. For each returned folder id, search inside it:
      `search_files(query="'<folder_id>' in parents and name contains 'X'")`
   Stop as soon as you find matches. If the user's query refers to a
   topic (e.g. "growth"), match folder names first — a folder named
   "Growth" probably has the files inside.

4. **If the user gives a topic but not a name**, combine filters:
   `mimeType = 'application/vnd.google-apps.document' and name contains 'roadmap'`
   or `modifiedTime > '2025-01-01T00:00:00' and name contains 'Q4'`.

## After you find the files

- **Open the most relevant hit.** `read_file(file_id)` returns plain
  text for Docs, CSV for Sheets, raw text for non-Workspace files.
- **Don't read everything** — search metadata (name, mimeType,
  modifiedTime, webViewLink) is usually enough to decide what to open.
- **Cite webViewLinks.** Every fact points to a Drive link. Don't
  speculate about file contents you didn't read.
- **Read-only.** No upload, no download, no writes.
"""
