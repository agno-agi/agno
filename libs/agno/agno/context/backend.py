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
from typing import TYPE_CHECKING, ClassVar, List

from agno.context.provider import Status

if TYPE_CHECKING:
    from agno.knowledge.reader.page_fetcher import FetchedPage


class ContextBackend(ABC):
    """Base class for the I/O layer behind a `ContextProvider`."""

    # How many URLs one fetch_many/afetch_many call may take (one provider request per call).
    fetch_batch_limit: ClassVar[int] = 1
    # What lands in FetchedPage.extractor and knowledge provenance for pages this backend fetched.
    extractor_id: ClassVar[str] = "backend"

    @abstractmethod
    def status(self) -> Status: ...

    @abstractmethod
    async def astatus(self) -> Status: ...

    @abstractmethod
    def get_tools(self) -> list: ...

    def fetch_many(self, urls: List[str], *, max_chars: int = 50_000) -> List[FetchedPage]:
        """Fetch up to ``fetch_batch_limit`` pages in one provider request.

        Backends that can extract pages override this (and ``afetch_many``) so knowledge
        readers can fetch through them. Raises ``RateLimited`` when the provider says to slow
        down; any other per-page problem is reported on the page, not raised.
        """
        raise NotImplementedError(f"{type(self).__name__} does not implement page fetching")

    async def afetch_many(self, urls: List[str], *, max_chars: int = 50_000) -> List[FetchedPage]:
        """Async variant of :meth:`fetch_many`."""
        raise NotImplementedError(f"{type(self).__name__} does not implement page fetching")

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
