"""Tests for user tools colliding with Team framework tools."""

from typing import Callable
from unittest.mock import MagicMock

import pytest
from agno.agent import Agent
from agno.run.base import RunContext
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team import Team
from agno.team._tools import _determine_tools_for_model
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit


def _my_tool() -> str:
    return "user function"


def delegate_task_to_member() -> str:
    return "user function"


def _make_model() -> MagicMock:
    model = MagicMock()
    model.supports_native_structured_outputs = False
    return model


def _resolve_team_tools(team: Team) -> list:
    return _determine_tools_for_model(
        team=team,
        model=_make_model(),
        run_response=TeamRunOutput(run_id="run", session_id="session", team_id="team"),
        run_context=RunContext(run_id="run", session_id="session"),
        team_run_context={},
        session=TeamSession(session_id="session"),
        async_mode=False,
    )


def test_user_tools_do_not_conflict_with_team_framework_tools() -> None:
    team = Team(
        name="test-team",
        members=[Agent(id="member")],
        tools=[_my_tool],
    )

    functions = _resolve_team_tools(team)
    function_names = [function.name for function in functions if isinstance(function, Function)]

    assert "_my_tool" in function_names
    assert function_names.count("delegate_task_to_member") == 1


def test_toolkit_tools_cannot_replace_team_framework_tools() -> None:
    team = Team(
        name="test-team",
        members=[Agent(id="member")],
        tools=[Toolkit(name="user-toolkit", tools=[delegate_task_to_member])],
    )

    with pytest.raises(ValueError, match="delegate_task_to_member"):
        _resolve_team_tools(team)


@pytest.mark.parametrize(
    "tool",
    [
        Function.from_callable(_my_tool, name="delegate_task_to_member"),
        delegate_task_to_member,
    ],
    ids=["function", "callable"],
)
def test_user_tools_cannot_replace_team_framework_tools(tool: Callable) -> None:
    team = Team(
        name="test-team",
        members=[Agent(id="member")],
        tools=[tool],
    )

    with pytest.raises(ValueError, match="delegate_task_to_member"):
        _resolve_team_tools(team)
