"""
Unit tests for _get_tool_names in agno/team/_messages.py.

Verifies that async toolkit functions are included in the team system message
when add_member_tools_to_context=True and async_mode=True.

Regression test for: https://github.com/agno-agi/agno/issues/7039
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from agno.run.base import RunContext
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team._messages import _get_tool_names
from agno.team._tools import _determine_tools_for_model
from agno.team.team import Team
from agno.tools import Toolkit, tool
from agno.tools.function import Function

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SyncOnlyToolkit(Toolkit):
    def __init__(self):
        super().__init__(name="sync_tools")
        self.register(self.sync_tool)

    def sync_tool(self, query: str) -> str:
        """A sync tool."""
        return "sync result"


class AsyncOnlyToolkit(Toolkit):
    def __init__(self):
        super().__init__(name="async_tools")
        self.register(self.async_tool)

    async def async_tool(self, query: str) -> str:
        """An async tool."""
        return "async result"


class MixedToolkit(Toolkit):
    def __init__(self):
        super().__init__(name="mixed_tools")
        self.register(self.sync_tool)
        self.register(self.async_tool)

    def sync_tool(self, query: str) -> str:
        """A sync tool."""
        return "sync result"

    async def async_tool(self, query: str) -> str:
        """An async tool."""
        return "async result"


def _make_member(tools: list) -> SimpleNamespace:
    """Create a minimal member-like object with a tools list."""
    return SimpleNamespace(tools=tools)


# ---------------------------------------------------------------------------
# Tests — sync mode (async_mode=False, the default)
# ---------------------------------------------------------------------------


class TestGetToolNamesSyncMode:
    def test_sync_only_toolkit(self):
        """Sync-only toolkit functions appear in sync mode."""
        member = _make_member([SyncOnlyToolkit()])
        names = _get_tool_names(member)
        assert "sync_tool" in names

    def test_async_only_toolkit_not_shown(self):
        """Async-only toolkit functions do NOT appear in sync mode."""
        member = _make_member([AsyncOnlyToolkit()])
        names = _get_tool_names(member)
        assert names == []

    def test_mixed_toolkit_sync_only(self):
        """Only sync functions appear in sync mode for a mixed toolkit."""
        member = _make_member([MixedToolkit()])
        names = _get_tool_names(member)
        assert "sync_tool" in names
        assert "async_tool" not in names

    def test_empty_tools_list(self):
        """Empty tools list returns empty names."""
        member = _make_member([])
        names = _get_tool_names(member)
        assert names == []

    def test_none_tools(self):
        """None tools returns empty names."""
        member = SimpleNamespace(tools=None)
        names = _get_tool_names(member)
        assert names == []

    def test_callable_tool(self):
        """Plain callable tools are included."""

        def my_func(x: str) -> str:
            return x

        member = _make_member([my_func])
        names = _get_tool_names(member)
        assert "my_func" in names

    def test_function_tool(self):
        """Function objects are included."""

        def my_func(x: str) -> str:
            return x

        f = Function(name="my_function", entrypoint=my_func)
        member = _make_member([f])
        names = _get_tool_names(member)
        assert "my_function" in names


# ---------------------------------------------------------------------------
# Tests — async mode (async_mode=True)
# ---------------------------------------------------------------------------


class TestGetToolNamesAsyncMode:
    def test_async_only_toolkit(self):
        """Async-only toolkit functions appear in async mode (regression #7039)."""
        member = _make_member([AsyncOnlyToolkit()])
        names = _get_tool_names(member, async_mode=True)
        assert "async_tool" in names

    def test_sync_only_toolkit(self):
        """Sync-only toolkit functions also appear in async mode (fallback)."""
        member = _make_member([SyncOnlyToolkit()])
        names = _get_tool_names(member, async_mode=True)
        assert "sync_tool" in names

    def test_mixed_toolkit(self):
        """Both sync and async functions appear in async mode."""
        member = _make_member([MixedToolkit()])
        names = _get_tool_names(member, async_mode=True)
        assert "sync_tool" in names
        assert "async_tool" in names

    def test_multiple_toolkits(self):
        """Multiple toolkits with async-only tools all get included in async mode."""
        member = _make_member([SyncOnlyToolkit(), AsyncOnlyToolkit()])
        names = _get_tool_names(member, async_mode=True)
        assert "sync_tool" in names
        assert "async_tool" in names


# ---------------------------------------------------------------------------
# Tests — per-function instructions propagation through _determine_tools_for_model
#
# Verifies @tool(instructions=...) reaches team._tool_instructions whether the
# tool is registered bare or via a Toolkit.
# ---------------------------------------------------------------------------


def _make_tool_run_context():
    return RunContext(run_id="test-run", session_id="test-session")


def _make_tool_session():
    return TeamSession(session_id="test-session")


def _make_tool_run_response():
    return TeamRunOutput(run_id="test-run", session_id="test-session", team_id="test-team")


def _make_tool_model():
    model = MagicMock()
    model.supports_native_structured_outputs = False
    model.get_tools_for_api.return_value = []
    model.add_tool.return_value = None
    model.get_instructions_for_model = MagicMock(return_value=None)
    model.get_system_message_for_model = MagicMock(return_value=None)
    return model


def _resolve(team: Team) -> None:
    _determine_tools_for_model(
        team=team,
        model=_make_tool_model(),
        run_response=_make_tool_run_response(),
        run_context=_make_tool_run_context(),
        team_run_context={},
        session=_make_tool_session(),
        async_mode=False,
    )


def test_bare_function_instructions_reach_team():
    @tool(instructions="bare-rule")
    def my_tool(x: str) -> str:
        return x

    team = Team(name="t", members=[], tools=[my_tool])
    _resolve(team)

    assert team._tool_instructions == ["bare-rule"]


def test_toolkit_per_function_instructions_reach_team():
    """The original bug: @tool(instructions=...) inside a Toolkit was dropped."""

    class MyToolkit(Toolkit):
        def __init__(self):
            super().__init__(name="my_toolkit", tools=[self.my_tool])

        @tool(instructions="toolkit-func-rule")
        def my_tool(self, x: str) -> str:
            return x

    team = Team(name="t", members=[], tools=[MyToolkit()])
    _resolve(team)

    assert team._tool_instructions == ["toolkit-func-rule"]


def test_toolkit_level_and_per_function_instructions_both_reach_team():
    class MyToolkit(Toolkit):
        def __init__(self):
            super().__init__(
                name="my_toolkit",
                tools=[self.my_tool],
                instructions="toolkit-level-rule",
                add_instructions=True,
            )

        @tool(instructions="toolkit-func-rule")
        def my_tool(self, x: str) -> str:
            return x

    team = Team(name="t", members=[], tools=[MyToolkit()])
    _resolve(team)

    assert team._tool_instructions == ["toolkit-func-rule", "toolkit-level-rule"]


def test_toolkit_per_function_add_instructions_false_is_respected_team():
    class MyToolkit(Toolkit):
        def __init__(self):
            super().__init__(name="my_toolkit", tools=[self.kept, self.dropped])

        @tool(instructions="kept-rule")
        def kept(self, x: str) -> str:
            return x

        @tool(instructions="dropped-rule", add_instructions=False)
        def dropped(self, x: str) -> str:
            return x

    team = Team(name="t", members=[], tools=[MyToolkit()])
    _resolve(team)

    assert team._tool_instructions == ["kept-rule"]


def test_toolkit_multiple_per_function_instructions_all_reach_team():
    class MyToolkit(Toolkit):
        def __init__(self):
            super().__init__(name="my_toolkit", tools=[self.a, self.b])

        @tool(instructions="rule-a")
        def a(self, x: str) -> str:
            return x

        @tool(instructions="rule-b")
        def b(self, x: str) -> str:
            return x

    team = Team(name="t", members=[], tools=[MyToolkit()])
    _resolve(team)

    assert team._tool_instructions == ["rule-a", "rule-b"]
