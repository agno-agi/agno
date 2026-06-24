"""
Context Provider Backends
=========================

A `ContextBackend` is the I/O layer behind a `ContextProvider`.
The provider owns the agent-facing contract (`query` / `status` / `get_tools`).
The backend owns the actual connection to the source — MCP server, SDK client, filesystem.

The provider can swap between backends without changing its agent interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agno.context.provider import Status


class ContextBackend(ABC):
    """Base class for the I/O layer behind a `ContextProvider`."""

    @abstractmethod
    def status(self) -> Status: ...

    @abstractmethod
    async def astatus(self) -> Status: ...

    @abstractmethod
    def get_tools(self) -> list: ...

    async def asetup(self) -> None:
        """Setup any resources the backend needs. Default: no-op.

        Override in backends that wrap a resource needing async setup
        before ``get_tools()`` is called (e.g. an MCP client
        whose tool list only populates after ``_connect()``).
        """
        return None

    async def aclose(self) -> None:
        """Release any resources the backend holds. Default: no-op.

        Override in backends that keep long-lived state. Must be safe
        to call even if the backend never finished setup.
        """
        return None
