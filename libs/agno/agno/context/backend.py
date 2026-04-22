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
