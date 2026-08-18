"""Backwards compatibility for Agno 2.x toolkit constructor kwargs.

Agno 3.0 renamed toolkit tool-toggle params (enable_search -> search) and
removed `all` from some toolkits. Passing the 2.x names must not raise:
they are remapped onto the 3.0 params with a deprecation warning.
"""

from typing import Callable, List

from agno.tools import Toolkit
from agno.tools.shell import ShellTools


class DemoTools(Toolkit):
    _legacy_param_aliases = {"enable_old_name": "renamed_tool"}

    def __init__(self, search: bool = True, renamed_tool: bool = False, all: bool = False, **kwargs):
        tools: List[Callable] = []
        if all or search:
            tools.append(self.search)
        if all or renamed_tool:
            tools.append(self.renamed_tool)
        super().__init__(name="demo_tools", tools=tools, **kwargs)

    def search(self, query: str) -> str:
        """Search for query.

        Args:
            query: The query.

        Returns:
            JSON results.
        """
        return "{}"

    def renamed_tool(self, value: str) -> str:
        """Do the renamed thing.

        Args:
            value: The value.

        Returns:
            JSON results.
        """
        return "{}"


def test_prefix_stripped_legacy_kwarg_maps_to_new_flag():
    tools = DemoTools(enable_search=False)
    assert "search" not in tools.functions


def test_aliased_legacy_kwarg_maps_to_renamed_flag():
    tools = DemoTools(enable_old_name=True)
    assert "renamed_tool" in tools.functions


def test_new_param_wins_over_legacy_kwarg():
    tools = DemoTools(enable_search=False, search=True)
    assert "search" in tools.functions


def test_unknown_legacy_kwarg_is_dropped_not_raised():
    tools = DemoTools(enable_does_not_exist=True)
    assert set(tools.functions) == {"search"}


def test_legacy_all_kwarg_still_works_where_all_exists():
    tools = DemoTools(all=True)
    assert set(tools.functions) == {"search", "renamed_tool"}


def test_shell_prefix_strip_registers_tool():
    tools = ShellTools(enable_run_shell_command=True)
    assert "run_shell_command" in tools.functions


def test_shell_legacy_all_maps_to_single_tool_flag():
    # ShellTools dropped `all`; the legacy kwarg maps onto run_shell_command
    tools = ShellTools(all=True)
    assert "run_shell_command" in tools.functions


def test_shell_defaults_unaffected():
    tools = ShellTools()
    assert "run_shell_command" not in tools.functions
