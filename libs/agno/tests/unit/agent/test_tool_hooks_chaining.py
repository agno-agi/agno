"""Agent-level tool_hooks must wrap a tool's own tool_hooks, not replace them."""

from typing import Any, Callable, Dict, List
from unittest.mock import MagicMock

import pytest

from agno.agent._tools import parse_tools
from agno.agent.agent import Agent
from agno.run import RunContext
from agno.tools import tool
from agno.tools.function import FunctionCall
from agno.tools.toolkit import Toolkit

events: List[str] = []


@pytest.fixture(autouse=True)
def clear_events():
    events.clear()


def _mock_model():
    model = MagicMock()
    model.supports_native_structured_outputs = False
    return model


def agent_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
    events.append("agent")
    return function_call(**arguments)


async def async_agent_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
    events.append("agent-before")
    result = await function_call(**arguments)
    events.append("agent-after")
    return result


def function_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
    events.append("function")
    return function_call(**arguments)


@tool(tool_hooks=[function_hook])
def lookup(query: str) -> str:
    """Look up a query."""
    events.append("tool")
    return f"found-{query}"


@tool(tool_hooks=[function_hook])
async def async_lookup(query: str) -> str:
    """Look up a query."""
    events.append("tool")
    return f"found-{query}"


def _parse(agent: Agent, async_mode: bool = False):
    return parse_tools(
        agent=agent,
        tools=agent.tools,
        model=_mock_model(),
        run_context=RunContext(run_id="r1", session_id="s1"),
        async_mode=async_mode,
    )


@pytest.mark.parametrize(
    "tools",
    [[lookup], [Toolkit(name="lookup_tools", tools=[lookup])]],
    ids=["function", "toolkit"],
)
def test_agent_tool_hooks_wrap_function_tool_hooks(tools):
    agent = Agent(tools=tools, tool_hooks=[agent_hook], telemetry=False)

    functions = _parse(agent)

    assert [f.tool_hooks for f in functions] == [[agent_hook, function_hook]]
    result = FunctionCall(function=functions[0], arguments={"query": "q"}).execute()
    assert result.status == "success"
    assert result.result == "found-q"
    assert events == ["agent", "function", "tool"]


def test_function_tool_hooks_kept_without_agent_tool_hooks():
    agent = Agent(tools=[lookup], telemetry=False)

    functions = _parse(agent)

    assert [f.tool_hooks for f in functions] == [[function_hook]]


def test_agent_tool_hooks_do_not_pile_up_across_runs():
    agent = Agent(tools=[lookup], tool_hooks=[agent_hook], telemetry=False)

    _parse(agent)
    functions = _parse(agent)

    assert [f.tool_hooks for f in functions] == [[agent_hook, function_hook]]
    assert lookup.tool_hooks == [function_hook]


@pytest.mark.asyncio
async def test_sync_function_hook_inside_async_agent_hook_runs_async_tool():
    agent = Agent(tools=[async_lookup], tool_hooks=[async_agent_hook], telemetry=False)

    functions = _parse(agent, async_mode=True)
    result = await FunctionCall(function=functions[0], arguments={"query": "q"}).aexecute()

    assert result.status == "success"
    assert result.result == "found-q"
    assert events == ["agent-before", "function", "tool", "agent-after"]
