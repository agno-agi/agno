"""PythonWorkspaceBackend — workspace search using pure Python.

Uses the standard Workspace toolkit with os.walk and re for search.
This is the default backend, available everywhere without dependencies.

Example:
    from agno.context.workspace import WorkspaceContextProvider, PythonWorkspaceBackend

    provider = WorkspaceContextProvider(
        backend=PythonWorkspaceBackend(root="./my-project"),
    )
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, List, Optional

from agno.context.provider import Status
from agno.context.workspace.backend import WorkspaceBackend


class PythonWorkspaceBackend(WorkspaceBackend):
    """Workspace backend using pure Python (Workspace toolkit).

    Args:
        root: Root directory of the workspace.
        max_file_lines: Maximum lines to read from a file. Default 100,000.
        max_file_length: Maximum file size in bytes. Default 10MB.
        max_grep_matches: Maximum grep results. Default 500.
        max_search_file_size: Skip files larger than this for search. Default 500KB.
        exclude_patterns: Glob patterns to exclude from search.
        allow_paths: Paths to allow even if they match exclude patterns.
    """

    def __init__(
        self,
        root: str | Path = ".",
        max_file_lines: int = 100_000,
        max_file_length: int = 10_000_000,
        max_grep_matches: int = 500,
        max_search_file_size: int = 500 * 1024,
        exclude_patterns: Optional[List[str]] = None,
        allow_paths: Optional[List[str]] = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.max_file_lines = max_file_lines
        self.max_file_length = max_file_length
        self.max_grep_matches = max_grep_matches
        self.max_search_file_size = max_search_file_size
        self.exclude_patterns = exclude_patterns
        self.allow_paths = allow_paths
        self._tools: Optional[Any] = None

    def status(self) -> Status:
        if not self.root.exists():
            return Status(ok=False, detail=f"root does not exist: {self.root}")
        if not self.root.is_dir():
            return Status(ok=False, detail=f"root is not a directory: {self.root}")
        return Status(ok=True, detail=f"python @ {self.root}")

    async def astatus(self) -> Status:
        return await asyncio.to_thread(self.status)

    def get_tools(self) -> List:
        if self._tools is None:
            self._tools = self._build_tools()
        return [self._tools]

    def _build_tools(self) -> Any:
        from agno.tools.workspace import Workspace

        return Workspace(
            root=self.root,
            allowed=Workspace.READ_TOOLS,
            max_file_lines=self.max_file_lines,
            max_file_length=self.max_file_length,
            max_grep_matches=self.max_grep_matches,
            max_search_file_size=self.max_search_file_size,
            exclude_patterns=self.exclude_patterns,
            allow_paths=self.allow_paths,
        )
