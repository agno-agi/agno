"""
Unit tests for framework-owned tool name reservation in
``agno/team/_tools.py:: _determine_tools_for_model``.

A user-provided tool must not be able to shadow a tool the Team depends on
internally (e.g. ``delegate_task_to_member``). Before the fix, the de-dup loop
was first-wins and user tools were appended before framework tools, so a user
function using a framework name replaced the framework tool and silently
broke delegation.

Regression test for: https://github.com/agno-agi/agno/issues/9871
"""

from unittest.mock import MagicMock

from agno.agent import Agent
from agno.models.base import Model
from agno.run.base import RunContext
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team import Team
from agno.team._tools import _determine_tools_for_model
from agno.tools.function import Function


def _resolve(team: Team):
    model = MagicMock(spec=Model)
    model.supports_native_structured_outputs = False
    return _determine_tools_for_model(
        team,
        model,
        TeamRunOutput(run_id="run", session_id="session"),
        RunContext(run_id="run", session_id="session"),
        {},
        TeamSession(session_id="session"),
    )


def _by_name(functions, name):
    return [f for f in functions if isinstance(f, Function) and f.name == name]


def test_user_function_cannot_shadow_delegate_task_to_member():
    """The team keeps its own framework ``delegate_task_to_member``; the user function is dropped.

    The framework tool requires ``member_id`` and ``task`` arguments, while the
    user function takes none, so the parameter surface tells them apart without
    relying on entrypoint object identity (which ``process_entrypoint`` rewrites).
    """

    def my_tool() -> str:
        """user tool docstring"""
        return "user function"

    team = Team(
        members=[Agent(id="member", telemetry=False)],
        tools=[Function(name="delegate_task_to_member", entrypoint=my_tool)],
        telemetry=False,
    )

    matches = _by_name(_resolve(team), "delegate_task_to_member")

    # Exactly one tool owns the framework name, and it is the framework's.
    assert len(matches) == 1
    props = matches[0].parameters.get("properties", {})
    assert "member_id" in props and "task" in props


def test_user_function_cannot_shadow_framework_callable():
    """Reservation also covers framework tools appended as raw callables, not just Function instances.

    ``Team.get_member_information`` is a bound method appended directly (not a ``Function``).
    Its ``run_context`` argument is framework-injected, so the real tool exposes no user
    parameters; a shadowing user tool would leak its own parameter (``x``).
    """

    def shadow(x: str) -> str:
        """user shadow tool"""
        return x

    team = Team(
        members=[Agent(id="member", telemetry=False)],
        tools=[Function(name="get_member_information", entrypoint=shadow)],
        get_member_information_tool=True,
        telemetry=False,
    )

    matches = _by_name(_resolve(team), "get_member_information")

    assert len(matches) == 1
    assert "x" not in matches[0].parameters.get("properties", {})


def test_regular_user_tool_still_resolved():
    """A user tool that does not collide with a framework name is unaffected."""

    def my_tool(x: str) -> str:
        """user tool docstring"""
        return x

    team = Team(
        members=[Agent(id="member", telemetry=False)],
        tools=[Function(name="my_tool", entrypoint=my_tool)],
        telemetry=False,
    )

    matches = _by_name(_resolve(team), "my_tool")

    assert len(matches) == 1
    assert "x" in matches[0].parameters.get("properties", {})
    assert matches[0].description == "user tool docstring"
