"""Runtime tool registration and immutable tool snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from agno.tools.function import Function
from agno.tools.toolkit import Toolkit

Tool = Union[Toolkit, Callable, Function, Dict[str, Any]]


@dataclass(frozen=True)
class ToolSnapshot:
    """An immutable view of the tools visible to the next model request."""

    tools: Tuple[Tool, ...]
    version: int


class ToolRegistry:
    """Thread-safe runtime registry for tools that can change during an Agent run.

    A registry is intentionally separate from the Agent's normal static ``tools``
    list. Tool executions can call :meth:`register`, :meth:`unregister`, or
    :meth:`replace`, and the Agent refreshes its model-visible tool snapshot only
    when the registry version changes.
    """

    def __init__(self, tools: Optional[List[Tool]] = None) -> None:
        self._lock = RLock()
        self._tools: List[Tool] = list(tools or [])
        self._version = 0

    @property
    def version(self) -> int:
        """Return the monotonically increasing registry version."""
        with self._lock:
            return self._version

    def snapshot(self) -> ToolSnapshot:
        """Return a stable view of the current tools and version."""
        with self._lock:
            return ToolSnapshot(tools=tuple(self._tools), version=self._version)

    def register(self, tool: Tool) -> int:
        """Register a tool and return the new registry version."""
        with self._lock:
            self._tools.append(tool)
            self._version += 1
            return self._version

    def unregister(self, name: str) -> bool:
        """Remove tools matching ``name`` and return whether anything changed."""
        with self._lock:
            remaining = [tool for tool in self._tools if _tool_name(tool) != name]
            if len(remaining) == len(self._tools):
                return False
            self._tools = remaining
            self._version += 1
            return True

    def replace(self, tools: List[Tool]) -> int:
        """Replace the registry contents and return the new registry version."""
        with self._lock:
            self._tools = list(tools)
            self._version += 1
            return self._version


def _tool_name(tool: Tool) -> str:
    if isinstance(tool, dict):
        function = tool.get("function")
        if isinstance(function, dict):
            return str(function.get("name", ""))
        return str(tool.get("name", ""))
    return str(getattr(tool, "name", getattr(tool, "__name__", "")))
