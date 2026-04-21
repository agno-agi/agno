"""
Filesystem Context Provider
===========================

Exposes a local directory tree to the calling agent via read-only
`FileTools`. Scoped to a single root; writes/deletes are disabled.

The provider registers even if the root directory does not exist —
`status()` reports `ok=False` in that case, so the caller can surface
the broken config explicitly rather than having the provider silently
disappear from the registry.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status
from agno.tools.file import FileTools

if TYPE_CHECKING:
    from agno.models.base import Model


class FilesystemContextProvider(ContextProvider):
    """Local filesystem rooted at a single directory."""

    def __init__(
        self,
        root: str | Path,
        *,
        id: str = "fs",
        name: str = "Filesystem",
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model)
        self.root = Path(root).expanduser().resolve()
        self._agent: Agent | None = None

    def status(self) -> Status:
        if not self.root.exists():
            return Status(ok=False, detail=f"root does not exist: {self.root}")
        if not self.root.is_dir():
            return Status(ok=False, detail=f"root is not a directory: {self.root}")
        return Status(ok=True, detail=str(self.root))

    async def astatus(self) -> Status:
        return self.status()

    def query(self, question: str) -> Answer:
        return answer_from_run(self._ensure_agent().run(question))

    async def aquery(self, question: str) -> Answer:
        return answer_from_run(await self._ensure_agent().arun(question))

    def instructions(self) -> str:
        if self.mode == ContextMode.agent:
            return f"`{self.name}`: call `{self.query_tool_name}(question)` to query files under {self.root}."
        return (
            f"`{self.name}`: browse files under {self.root}. Use `list_files` / `search_files` "
            "(glob) / `search_content` (text search) / `read_file` / `read_file_chunk`. "
            "Paths are relative to the root."
        )

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    def _default_tools(self) -> list:
        return self._all_tools()

    def _all_tools(self) -> list:
        return [_build_file_tools(self.root)]

    # ------------------------------------------------------------------
    # Sub-agent — built lazily for agent mode and programmatic query()
    # ------------------------------------------------------------------

    def _ensure_agent(self) -> Agent:
        if self._agent is None:
            self._agent = self._build_agent()
        return self._agent

    def _build_agent(self) -> Agent:
        return Agent(
            id=self.id,
            name=self.name,
            role="Answer questions by browsing files under a local root",
            model=self.model,
            instructions=_AGENT_INSTRUCTIONS.format(root=self.root),
            tools=[_build_file_tools(self.root)],
            markdown=True,
        )


def _build_file_tools(root: Path) -> FileTools:
    return FileTools(
        base_dir=root,
        enable_save_file=False,
        enable_delete_file=False,
        enable_replace_file_chunk=False,
        enable_list_files=True,
        enable_search_files=True,
        enable_search_content=True,
        enable_read_file=True,
        enable_read_file_chunk=True,
    )


_AGENT_INSTRUCTIONS = """\
You answer questions by browsing files under {root}.

Workflow:
1. **Start broad.** `list_files` to see what's available, or `search_files`
   with a glob (`**/*.py`, `docs/*`) to narrow.
2. **Find content.** `search_content(query)` surfaces files whose text matches.
3. **Read only what you need.** `read_file` for small files, `read_file_chunk`
   for large ones.
4. **Cite the paths.** Always mention the file paths you read.

You are read-only. No save, no delete.
"""
