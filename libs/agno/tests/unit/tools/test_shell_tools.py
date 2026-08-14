"""Tests for ShellTools confirmation gating.

ShellTools.run_shell_command executes an arbitrary List[str] command — an RCE
sink under prompt injection. The toolkit's requires_confirmation_tools gates it
behind human approval; these tests lock that documented pattern and guard the
kwargs passthrough against regressions.
"""

import tempfile

from agno.tools.shell import ShellTools


def test_shell_tools_not_registered_by_default():
    """run_shell_command is opt-in (arbitrary host shell execution)."""
    tools = ShellTools()
    assert "run_shell_command" not in tools.functions


def test_shell_tools_registered_when_opted_in():
    """Passing run_shell_command=True registers the tool."""
    tools = ShellTools(run_shell_command=True)
    assert "run_shell_command" in tools.functions


def test_opted_in_runs_command():
    """Opt-in mode executes commands."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir, run_shell_command=True)
        assert "hello" in tools.run_shell_command(["echo", "hello"])


def test_requires_confirmation_tools_gates_run_shell_command():
    """The documented HITL pattern marks run_shell_command for confirmation."""
    tools = ShellTools(run_shell_command=True, requires_confirmation_tools=["run_shell_command"])
    assert tools.functions["run_shell_command"].requires_confirmation is True
