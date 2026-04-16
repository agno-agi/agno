"""
Unit tests for _get_tool_names in agno/team/_messages.py.

Verifies that async toolkit functions are included in the team system message
when add_member_tools_to_context=True and async_mode=True.

Regression test for: https://github.com/agno-agi/agno/issues/7039
"""

from types import SimpleNamespace

from agno.team._messages import _get_tool_names
from agno.tools import Toolkit
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
