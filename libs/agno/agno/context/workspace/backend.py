"""WorkspaceBackend — pluggable I/O layer for WorkspaceContextProvider.

A backend provides the tools that the workspace sub-agent uses. Different
backends can use different implementations:

- PythonWorkspaceBackend: Pure Python (os.walk, re)
- RipgrepWorkspaceBackend: Uses ripgrep for fast search

Example:
    from agno.context.workspace import WorkspaceContextProvider, RipgrepWorkspaceBackend

    provider = WorkspaceContextProvider(
        backend=RipgrepWorkspaceBackend(root="./my-project"),
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from agno.context.provider import Status


class WorkspaceBackend(ABC):
    """Base class for workspace I/O backends.

    Subclasses provide tools for searching and reading files in a workspace.
    The provider delegates tool creation to the backend, allowing different
    implementations (Python, ripgrep, etc.) to be swapped transparently.
    """

    root: Path

    @abstractmethod
    def status(self) -> Status:
        """Check if the backend is operational."""
        ...

    @abstractmethod
    async def astatus(self) -> Status:
        """Async variant of status()."""
        ...

    @abstractmethod
    def get_tools(self) -> List:
        """Return the tools for the workspace sub-agent.

        Returns a list containing either:
        - A single Toolkit instance (e.g., RipgrepTools, Workspace)
        - Multiple @tool-decorated functions
        """
        ...

    async def asetup(self) -> None:
        """Setup any resources. Default: no-op."""
        pass

    async def aclose(self) -> None:
        """Release any resources. Default: no-op."""
        pass
