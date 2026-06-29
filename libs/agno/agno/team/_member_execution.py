"""Helpers for synchronous member execution."""

from __future__ import annotations

import asyncio
from queue import Queue
from threading import Thread
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Coroutine, Iterator, TypeVar, Union

from agno.agent import Agent
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput

if TYPE_CHECKING:
    from agno.team.team import Team

_T = TypeVar("_T")
_STREAM_END = object()
_MCP_TOOLKIT_CLASS_NAMES = {"MCPTools", "MultiMCPTools"}


class _AsyncStreamError:
    def __init__(self, error: BaseException):
        self.error = error


def _has_mcp_toolkit(tools: Any) -> bool:
    return isinstance(tools, list) and any(
        hasattr(type(tool), "__mro__") and any(base.__name__ in _MCP_TOOLKIT_CLASS_NAMES for base in type(tool).__mro__)
        for tool in tools
    )


def _make_resolution_context(context_values: dict[str, Any]) -> RunContext:
    run_context = context_values.get("run_context")
    if isinstance(run_context, RunContext):
        return RunContext(
            run_id=run_context.run_id,
            session_id=run_context.session_id,
            user_id=run_context.user_id,
            dependencies=run_context.dependencies,
            knowledge_filters=run_context.knowledge_filters,
            metadata=run_context.metadata,
            session_state=run_context.session_state,
            output_schema=run_context.output_schema,
            messages=run_context.messages,
        )

    return RunContext(
        run_id=context_values.get("run_id") or "",
        session_id=context_values.get("session_id") or "",
        user_id=context_values.get("user_id"),
        session_state=context_values.get("session_state"),
    )


def _get_resolved_tools(entity: Union[Agent, "Team"], context_values: dict[str, Any]) -> Any:
    from agno.utils.callables import get_resolved_tools, resolve_callable_tools

    run_context = _make_resolution_context(context_values)
    resolve_callable_tools(entity, run_context)
    resolved_tools = get_resolved_tools(entity, run_context)
    if resolved_tools is not None:
        return resolved_tools
    return getattr(entity, "tools", None)


def _get_resolved_members(entity: "Team", context_values: dict[str, Any]) -> Any:
    from agno.utils.callables import get_resolved_members, resolve_callable_members

    run_context = _make_resolution_context(context_values)
    resolve_callable_members(entity, run_context)
    resolved_members = get_resolved_members(entity, run_context)
    if resolved_members is not None:
        return resolved_members
    return getattr(entity, "members", None)


def _uses_mcp_async_bridge(member_agent: Union[Agent, "Team"], context_values: dict[str, Any]) -> bool:
    if isinstance(member_agent, Agent):
        return _has_mcp_toolkit(_get_resolved_tools(member_agent, context_values))

    if type(member_agent).__name__ != "Team":
        return False

    if _has_mcp_toolkit(_get_resolved_tools(member_agent, context_values)):
        return True

    members = _get_resolved_members(member_agent, context_values) or []
    return any(_uses_mcp_async_bridge(member, context_values) for member in members)


def _run_async_in_thread(factory: Callable[[], Coroutine[Any, Any, _T]]) -> _T:
    result: dict[str, _T] = {}
    error: dict[str, BaseException] = {}

    def worker() -> None:
        try:
            result["value"] = asyncio.run(factory())
        except BaseException as exc:
            error["value"] = exc

    thread = Thread(target=worker, daemon=True)
    thread.start()
    thread.join()

    if "value" in error:
        raise error["value"]
    return result["value"]


def _stream_async_in_thread(factory: Callable[[], AsyncIterator[Any]]) -> Iterator[Any]:
    queue: Queue[object] = Queue()

    def worker() -> None:
        async def consume() -> None:
            async for item in factory():
                queue.put(item)

        try:
            asyncio.run(consume())
        except BaseException as exc:
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


def run_member_sync(
    member_agent: Union[Agent, "Team"],
    **kwargs: Any,
) -> Union[RunOutput, TeamRunOutput]:
    """Run a member synchronously, bridging MCP-backed Agents to ``arun()`` when needed."""

    if not _uses_mcp_async_bridge(member_agent, kwargs):
        return member_agent.run(**kwargs)  # type: ignore[misc]

    return _run_async_in_thread(lambda: member_agent.arun(**kwargs))  # type: ignore[misc]


def stream_member_sync(member_agent: Union[Agent, "Team"], **kwargs: Any) -> Iterator[Any]:
    """Stream a member synchronously, bridging MCP-backed Agents to ``arun()`` when needed."""

    if not _uses_mcp_async_bridge(member_agent, kwargs):
        return member_agent.run(**kwargs)  # type: ignore[misc]

    return _stream_async_in_thread(lambda: member_agent.arun(**kwargs))  # type: ignore[misc]
