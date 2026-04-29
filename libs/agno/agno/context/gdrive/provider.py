"""
Google Drive Context Provider
=============================

Read-only Google Drive access for the calling agent — list, search,
read files. Auth goes through a *service account* (JSON key file);
the owner grants that identity access to the folders the agent
should see. Upload/download are left off so this provider is purely
for reading Drive as context.

To enable:

1. Create a service account in Google Cloud Console and download the
   JSON key file.
2. Share the Drive folders you want the agent to see with the service
   account's email.
3. Set ``GOOGLE_SERVICE_ACCOUNT_FILE`` to the path of the key file,
   or pass ``service_account_path=...`` explicitly.

The provider uses an ``AllDrivesGoogleDriveTools`` subclass so service
accounts can see files inside folders shared with them and files in
Shared Drives — see ``agno.context.gdrive.tools`` for why the upstream
``GoogleDriveTools`` returns zero hits without it.
"""

from __future__ import annotations

from os import getenv
from pathlib import Path
from typing import TYPE_CHECKING

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.context.gdrive.tools import AllDrivesGoogleDriveTools
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status
from agno.run import RunContext

if TYPE_CHECKING:
    from agno.models.base import Model


class GDriveContextProvider(ContextProvider):
    """Read-only Google Drive access via a service account."""

    def __init__(
        self,
        *,
        service_account_path: str | None = None,
        id: str = "gdrive",
        name: str = "Google Drive",
        instructions: str | None = None,
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model)
        resolved = service_account_path or getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        if not resolved:
            raise ValueError("GDriveContextProvider: GOOGLE_SERVICE_ACCOUNT_FILE is required")
        self.service_account_path: str = resolved
        self.instructions_text = instructions if instructions is not None else DEFAULT_GDRIVE_INSTRUCTIONS
        self._tools: AllDrivesGoogleDriveTools | None = None
        self._agent: Agent | None = None

    def status(self) -> Status:
        path = Path(self.service_account_path).expanduser()
        if not path.exists():
            return Status(ok=False, detail=f"service account file not found: {path}")
        return Status(ok=True, detail="gdrive")

    async def astatus(self) -> Status:
        return self.status()

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

    def _ensure_tools(self) -> AllDrivesGoogleDriveTools:
        if self._tools is None:
            self._tools = AllDrivesGoogleDriveTools(
                service_account_path=self.service_account_path,
                list_files=True,
                search_files=True,
                read_file=True,
                upload_file=False,
                download_file=False,
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
