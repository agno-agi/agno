"""RipgrepWorkspaceBackend — fast workspace search using ripgrep.

Uses RipgrepTools for high-performance code search in large codebases.
Falls back gracefully if ripgrep is not installed.

Example:
    from agno.context.workspace import WorkspaceContextProvider, RipgrepWorkspaceBackend

    provider = WorkspaceContextProvider(
        backend=RipgrepWorkspaceBackend(root="./large-codebase"),
    )
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from shutil import which
from typing import Any, List, Optional

from agno.context.provider import Status
from agno.context.workspace.backend import WorkspaceBackend


class RipgrepWorkspaceBackend(WorkspaceBackend):
    """Workspace backend using ripgrep for fast search.

    Args:
        root: Root directory of the workspace.
        max_results: Maximum results per search. Default 100.
        max_file_size: Skip files larger than this (bytes). Default 500KB.
        timeout: Search timeout in seconds. Default 30.
        respect_gitignore: Respect .gitignore rules. Default True.
        include_hidden: Include hidden files. Default False.
    """

    def __init__(
        self,
        root: str | Path = ".",
        max_results: int = 100,
        max_file_size: int = 500 * 1024,
        timeout: int = 30,
        respect_gitignore: bool = True,
        include_hidden: bool = False,
    ) -> None:
        self.root = Path(root).resolve()
        self.max_results = max_results
        self.max_file_size = max_file_size
        self.timeout = timeout
        self.respect_gitignore = respect_gitignore
        self.include_hidden = include_hidden
        self._tools: Optional[Any] = None

    def status(self) -> Status:
        if not self.root.exists():
            return Status(ok=False, detail=f"root does not exist: {self.root}")
        if not self.root.is_dir():
            return Status(ok=False, detail=f"root is not a directory: {self.root}")
        if not which("rg"):
            return Status(ok=False, detail="ripgrep (rg) not installed")
        return Status(ok=True, detail=f"ripgrep @ {self.root}")

    async def astatus(self) -> Status:
        return await asyncio.to_thread(self.status)

    def get_tools(self) -> List:
        if self._tools is None:
            self._tools = self._build_tools()
        return [self._tools]

    def _build_tools(self) -> Any:
        from agno.tools.ripgrep import RipgrepTools

        return RipgrepTools(
            root=self.root,
            max_results=self.max_results,
            max_file_size=self.max_file_size,
            timeout=self.timeout,
            respect_gitignore=self.respect_gitignore,
            include_hidden=self.include_hidden,
        )
