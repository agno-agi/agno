"""Team-level tool_hooks must wrap a tool's own tool_hooks, not replace them.

Mirrors libs/agno/tests/unit/agent/test_tool_hooks_chaining.py for Team.
"""

from typing import Any, Callable, Dict, List
from unittest.mock import MagicMock

import pytest

from agno.run.base import RunContext
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team._tools import _determine_tools_for_model
from agno.team.team import Team
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


def team_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
    events.append("team")
    return function_call(**arguments)


async def async_team_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
    events.append("team-before")
    result = await function_call(**arguments)
    events.append("team-after")
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


def _resolve_tools(team: Team, async_mode: bool = False):
    return _determine_tools_for_model(
        team=team,
        model=_mock_model(),
        run_response=TeamRunOutput(run_id="r1", session_id="s1", team_id="t1"),
        run_context=RunContext(run_id="r1", session_id="s1"),
        team_run_context={},
        session=TeamSession(session_id="s1"),
        async_mode=async_mode,
    )


@pytest.mark.parametrize(
    "tools",
    [[lookup], [Toolkit(name="lookup_tools", tools=[lookup])]],
    ids=["function", "toolkit"],
)
def test_team_tool_hooks_wrap_function_tool_hooks(tools):
    team = Team(name="t", members=[], tools=tools, tool_hooks=[team_hook])

    functions = _resolve_tools(team)

    assert [f.tool_hooks for f in functions] == [[team_hook, function_hook]]
    result = FunctionCall(function=functions[0], arguments={"query": "q"}).execute()
    assert result.status == "success"
    assert result.result == "found-q"
    assert events == ["team", "function", "tool"]


def test_function_tool_hooks_kept_without_team_tool_hooks():
    team = Team(name="t", members=[], tools=[lookup])

    functions = _resolve_tools(team)

    assert [f.tool_hooks for f in functions] == [[function_hook]]


def test_team_tool_hooks_do_not_pile_up_across_runs():
    team = Team(name="t", members=[], tools=[lookup], tool_hooks=[team_hook])

    _resolve_tools(team)
    functions = _resolve_tools(team)

    assert [f.tool_hooks for f in functions] == [[team_hook, function_hook]]
    assert lookup.tool_hooks == [function_hook]


@pytest.mark.asyncio
async def test_sync_function_hook_inside_async_team_hook_runs_async_tool():
    team = Team(name="t", members=[], tools=[async_lookup], tool_hooks=[async_team_hook])

    functions = _resolve_tools(team, async_mode=True)
    result = await FunctionCall(function=functions[0], arguments={"query": "q"}).aexecute()

    assert result.status == "success"
    assert result.result == "found-q"
    assert events == ["team-before", "function", "tool", "team-after"]
