"""Helpers for synchronous member execution."""

from __future__ import annotations

import asyncio
from queue import Queue
from threading import Thread
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Coroutine, Iterator, TypeVar, Union, cast

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
        dependencies = context_values["dependencies"] if "dependencies" in context_values else run_context.dependencies
        knowledge_filters = (
            context_values["knowledge_filters"]
            if "knowledge_filters" in context_values
            else run_context.knowledge_filters
        )
        metadata = context_values["metadata"] if "metadata" in context_values else run_context.metadata
        output_schema = (
            context_values["output_schema"] if "output_schema" in context_values else run_context.output_schema
        )
        return RunContext(
            run_id=context_values.get("run_id") or run_context.run_id,
            session_id=context_values.get("session_id") or run_context.session_id,
            user_id=context_values.get("user_id") or run_context.user_id,
            dependencies=dependencies,
            knowledge_filters=knowledge_filters,
            metadata=metadata,
            session_state=context_values.get("session_state")
            if context_values.get("session_state") is not None
            else run_context.session_state,
            output_schema=output_schema,
            messages=context_values.get("messages"),
        )

    return RunContext(
        run_id=context_values.get("run_id") or "",
        session_id=context_values.get("session_id") or "",
        user_id=context_values.get("user_id"),
        session_state=context_values.get("session_state"),
    )


def _apply_run_option_defaults(
    entity: Union[Agent, "Team"], run_context: RunContext, context_values: dict[str, Any]
) -> None:
    options: Any
    if isinstance(entity, Agent):
        from agno.agent._run_options import resolve_run_options as resolve_agent_run_options

        options = resolve_agent_run_options(
            entity,
            dependencies=context_values.get("dependencies"),
            knowledge_filters=context_values.get("knowledge_filters"),
            metadata=context_values.get("metadata"),
            output_schema=context_values.get("output_schema"),
        )
    else:
        from agno.team._run_options import resolve_run_options as resolve_team_run_options

        options = resolve_team_run_options(
            entity,
            dependencies=context_values.get("dependencies"),
            knowledge_filters=context_values.get("knowledge_filters"),
            metadata=context_values.get("metadata"),
            output_schema=context_values.get("output_schema"),
        )

    options.apply_to_context(
        run_context,
        dependencies_provided=context_values.get("dependencies") is not None,
        knowledge_filters_provided=context_values.get("knowledge_filters") is not None,
        metadata_provided=context_values.get("metadata") is not None,
    )


def _invoke_tool_factory(entity: Union[Agent, "Team"], context_values: dict[str, Any]) -> Any:
    from agno.utils.callables import invoke_callable_factory

    run_context = _make_resolution_context(context_values)
    _apply_run_option_defaults(entity, run_context, context_values)
    return invoke_callable_factory(cast(Callable[..., Any], entity.tools), entity, run_context)


def _invoke_member_factory(entity: "Team", context_values: dict[str, Any]) -> Any:
    from agno.utils.callables import invoke_callable_factory

    run_context = _make_resolution_context(context_values)
    _apply_run_option_defaults(entity, run_context, context_values)
    return invoke_callable_factory(cast(Callable[..., Any], entity.members), entity, run_context)


def _get_resolved_tools(entity: Union[Agent, "Team"], context_values: dict[str, Any]) -> Any:
    tools = getattr(entity, "tools", None)
    if isinstance(tools, list):
        return tools
    if callable(tools):
        result = _invoke_tool_factory(entity, context_values)
        if result is None:
            return []
        if isinstance(result, tuple):
            return list(result)
        if isinstance(result, list):
            return result
        raise TypeError(f"Callable tools factory must return a list or tuple, got {type(result).__name__}")
    return None


def _get_resolved_members(entity: "Team", context_values: dict[str, Any]) -> Any:
    members = getattr(entity, "members", None)
    if isinstance(members, list):
        return members
    if callable(members):
        result = _invoke_member_factory(entity, context_values)
        if result is None:
            return []
        if isinstance(result, tuple):
            return list(result)
        if isinstance(result, list):
            return result
        raise TypeError(f"Callable members factory must return a list or tuple, got {type(result).__name__}")
    return None


def _get_execution_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    execution_kwargs = dict(kwargs)
    if isinstance(kwargs.get("run_context"), RunContext):
        execution_kwargs["run_context"] = _make_resolution_context(kwargs)
    return execution_kwargs


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

    execution_kwargs = _get_execution_kwargs(kwargs)
    if not _uses_mcp_async_bridge(member_agent, kwargs):
        return member_agent.run(**execution_kwargs)  # type: ignore[misc]

    return _run_async_in_thread(lambda: member_agent.arun(**execution_kwargs))  # type: ignore[misc]


def stream_member_sync(member_agent: Union[Agent, "Team"], **kwargs: Any) -> Iterator[Any]:
    """Stream a member synchronously, bridging MCP-backed Agents to ``arun()`` when needed."""

    execution_kwargs = _get_execution_kwargs(kwargs)
    if not _uses_mcp_async_bridge(member_agent, kwargs):
        return member_agent.run(**execution_kwargs)  # type: ignore[misc]

    return _stream_async_in_thread(lambda: member_agent.arun(**execution_kwargs))  # type: ignore[misc]
