"""
Unit tests for _get_tool_names in agno/team/_messages.py.

Verifies that async toolkit functions are included in the team system message
when add_member_tools_to_context=True.

Regression test for: https://github.com/agno-agi/agno/issues/7039
"""

from types import SimpleNamespace
from typing import List

import pytest

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


class DuplicateNameToolkit(Toolkit):
    """Toolkit where a sync and async function share the same name via aliasing."""

    def __init__(self):
        super().__init__(name="dup_tools", auto_register=False)
        self.register(self._sync_impl, name="shared_tool")
        self.register(self._async_impl, name="shared_tool")

    def _sync_impl(self, query: str) -> str:
        """Sync implementation."""
        return "sync"

    async def _async_impl(self, query: str) -> str:
        """Async implementation."""
        return "async"


def _make_member(tools: list) -> SimpleNamespace:
    """Create a minimal member-like object with a tools list."""
    return SimpleNamespace(tools=tools)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetToolNames:
    def test_sync_only_toolkit(self):
        """Sync-only toolkit functions appear in tool names."""
        member = _make_member([SyncOnlyToolkit()])
        names = _get_tool_names(member)
        assert "sync_tool" in names

    def test_async_only_toolkit(self):
        """Async-only toolkit functions appear in tool names (regression #7039)."""
        member = _make_member([AsyncOnlyToolkit()])
        names = _get_tool_names(member)
        assert "async_tool" in names

    def test_mixed_toolkit(self):
        """Both sync and async functions appear in tool names."""
        member = _make_member([MixedToolkit()])
        names = _get_tool_names(member)
        assert "sync_tool" in names
        assert "async_tool" in names

    def test_no_duplicate_names(self):
        """When a tool name exists in both sync and async dicts, it appears only once."""
        member = _make_member([DuplicateNameToolkit()])
        names = _get_tool_names(member)
        assert names.count("shared_tool") == 1

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

    def test_multiple_toolkits(self):
        """Multiple toolkits with async-only tools all get included."""
        member = _make_member([SyncOnlyToolkit(), AsyncOnlyToolkit()])
        names = _get_tool_names(member)
        assert "sync_tool" in names
        assert "async_tool" in names
