"""Helpers for synchronous team member execution.

These helpers detect MCP-backed members and route only those members through the
async ``arun()`` path on a dedicated event loop, so connection and tool
invocation happen on the same loop. Non-MCP members keep the fast sync
``run()`` path.
"""

from __future__ import annotations

import asyncio
from queue import Queue
from threading import Thread
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Coroutine, Iterator, TypeVar, Union

from agno.agent import Agent

if TYPE_CHECKING:
    from agno.team.team import Team

_T = TypeVar("_T")

# Sentinel marking the end of a bridged async stream.
_STREAM_END = object()

# MCP toolkit class names, matched via MRO to avoid importing the MCP extras.
_MCP_TOOLKIT_CLASS_NAMES = {"MCPTools", "MultiMCPTools"}


class _AsyncStreamError:
    """Wraps an exception raised inside the async stream worker thread."""

    def __init__(self, error: BaseException) -> None:
        self.error = error


def _tools_contain_mcp(tools: Any) -> bool:
    """Return True if a concrete tools list contains an MCP toolkit."""
    if not isinstance(tools, list):
        return False
    for tool in tools:
        tool_type = type(tool)
        if hasattr(tool_type, "__mro__") and any(
            base.__name__ in _MCP_TOOLKIT_CLASS_NAMES for base in tool_type.__mro__
        ):
            return True
    return False


def member_has_mcp_tools(member: Union[Agent, "Team"]) -> bool:
    """Return True if the member (or, for a member Team, any of its members) uses MCP tools.

    Callable tool/member factories are treated as non-MCP here: they are resolved
    later inside the run, and the async ``arun()`` path handles MCP connection for
    them anyway. We only need this fast check to decide whether to bridge the
    top-level sync delegation call to ``arun()``.
    """
    if _tools_contain_mcp(getattr(member, "tools", None)):
        return True

    # For member Teams, MCP tools may live on nested members.
    members = getattr(member, "members", None)
    if isinstance(members, list):
        return any(member_has_mcp_tools(sub_member) for sub_member in members)

    return False


def _run_coro_in_thread(factory: Callable[[], Coroutine[Any, Any, _T]]) -> _T:
    """Run a coroutine to completion on a fresh event loop in a worker thread.

    A dedicated thread + loop avoids clashing with any event loop already running
    on the calling thread and guarantees the MCP session is connected and used on
    the same loop.
    """
    result: dict[str, _T] = {}
    error: dict[str, BaseException] = {}

    def worker() -> None:
        try:
            result["value"] = asyncio.run(factory())
        except BaseException as exc:  # noqa: BLE001 - re-raised on the calling thread
            error["value"] = exc

    thread = Thread(target=worker, daemon=True)
    thread.start()
    thread.join()

    if "value" in error:
        raise error["value"]
    return result["value"]


def _stream_coro_in_thread(factory: Callable[[], AsyncIterator[Any]]) -> Iterator[Any]:
    """Consume an async iterator on a worker-thread loop and yield items synchronously."""
    queue: "Queue[object]" = Queue()

    def worker() -> None:
        async def consume() -> None:
            async for item in factory():
                queue.put(item)

        try:
            asyncio.run(consume())
        except BaseException as exc:  # noqa: BLE001 - surfaced to the consumer below
            queue.put(_AsyncStreamError(exc))
        finally:
            queue.put(_STREAM_END)

    thread = Thread(target=worker, daemon=True)
    thread.start()
    try:
        while True:
            item = queue.get()
            if item is _STREAM_END:
                break
            if isinstance(item, _AsyncStreamError):
                raise item.error
            yield item
    finally:
        thread.join()


def run_member_sync(member: Union[Agent, "Team"], **kwargs: Any) -> Any:
    """Run a member synchronously, bridging MCP-backed members to ``arun()``.

    Non-MCP members use the plain sync ``run()`` path.
    """
    if member_has_mcp_tools(member):
        return _run_coro_in_thread(lambda: member.arun(**kwargs))  # type: ignore[arg-type]
    return member.run(**kwargs)


def stream_member_sync(member: Union[Agent, "Team"], **kwargs: Any) -> Iterator[Any]:
    """Stream a member synchronously, bridging MCP-backed members to ``arun()``.

    Non-MCP members use the plain sync streaming ``run()`` path.
    """
    if member_has_mcp_tools(member):
        return _stream_coro_in_thread(lambda: member.arun(**kwargs))  # type: ignore[arg-type]
    return member.run(**kwargs)
