"""
Google Drive Context Provider
=============================

Read-only Google Drive access for the calling agent — list, search,
read files. Auth via a service account (headless). Upload/download
are left off.

To enable:
1. Create a service account in Google Cloud Console, download the JSON key.
2. Share the Drive folders/files you want the agent to see with the
   service account's email (or use domain-wide delegation via
   `GOOGLE_DELEGATED_USER`).
3. Set `GOOGLE_SERVICE_ACCOUNT_FILE` to the path of the key file.
"""

from __future__ import annotations

from os import getenv
from pathlib import Path
from typing import TYPE_CHECKING

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status
from agno.tools.google.drive import GoogleDriveTools

if TYPE_CHECKING:
    from agno.models.base import Model


class GDriveContextProvider(ContextProvider):
    """Read-only Google Drive access via a service account."""

    def __init__(
        self,
        *,
        service_account_path: str | None = None,
        delegated_user: str | None = None,
        id: str = "gdrive",
        name: str = "Google Drive",
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model)
        self.service_account_path = service_account_path or getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        self.delegated_user = delegated_user or getenv("GOOGLE_DELEGATED_USER")
        if not self.service_account_path:
            raise ValueError("GDriveContextProvider: GOOGLE_SERVICE_ACCOUNT_FILE is required")
        self._tools: GoogleDriveTools | None = None
        self._agent: Agent | None = None

    def status(self) -> Status:
        if not self.service_account_path:
            return Status(ok=False, detail="GOOGLE_SERVICE_ACCOUNT_FILE not set")
        path = Path(self.service_account_path).expanduser()
        if not path.exists():
            return Status(ok=False, detail=f"service account file not found: {path}")
        delegated = f" (as {self.delegated_user})" if self.delegated_user else ""
        return Status(ok=True, detail=f"gdrive{delegated}")

    async def astatus(self) -> Status:
        return self.status()

    def query(self, question: str) -> Answer:
        return answer_from_run(self._ensure_agent().run(question))

    async def aquery(self, question: str) -> Answer:
        return answer_from_run(await self._ensure_agent().arun(question))

    def instructions(self) -> str:
        if self.mode == ContextMode.agent:
            return f"`{self.name}`: call `{self.query_tool_name}(question)` to query Google Drive."
        return (
            f"`{self.name}`: `search_files(query)` or `list_files(query)` with Drive query syntax "
            "(e.g. `name contains 'roadmap'`, `mimeType = 'application/vnd.google-apps.document'`). "
            "Then `read_file(file_id)` to read contents. Read-only."
        )

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    def _default_tools(self) -> list:
        return self._all_tools()

    def _all_tools(self) -> list:
        return [self._ensure_tools()]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_tools(self) -> GoogleDriveTools:
        if self._tools is None:
            self._tools = GoogleDriveTools(
                service_account_path=self.service_account_path,
                delegated_user=self.delegated_user,
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
            role="Answer questions by searching and reading Google Drive",
            model=self.model,
            instructions=_AGENT_INSTRUCTIONS,
            tools=[self._ensure_tools()],
            markdown=True,
        )


_AGENT_INSTRUCTIONS = """\
You answer questions by searching and reading Google Drive.

Workflow:
1. **Search with Drive query syntax.** `search_files(query=...)` accepts
   clauses like `name contains 'roadmap'`,
   `mimeType = 'application/vnd.google-apps.document'`,
   `modifiedTime > '2025-01-01T00:00:00'`. Combine with `and` / `or`.
2. **Open the most relevant hits.** `read_file(file_id)` returns plain text
   for Docs, CSV for Sheets, raw text for non-Workspace files.
3. **Don't read everything.** The search result has enough metadata
   (name, mimeType, modifiedTime, webViewLink) to decide what to open.
4. **Cite webViewLinks.** Every fact should point to a Drive link.

You are read-only. No upload, no download, no writes.
"""
