"""Tests for ShellTools confirmation gating.

ShellTools.run_shell_command executes an arbitrary List[str] command — an RCE
sink under prompt injection. The toolkit's requires_confirmation_tools gates it
behind human approval; these tests lock that documented pattern and guard the
kwargs passthrough against regressions.
"""

import sys
import tempfile

import pytest

from agno.tools.shell import ShellTools
from agno.utils.shell import run_shell_command


def test_shell_tools_registered_by_default():
    """run_shell_command is registered by default (existing contract preserved)."""
    tools = ShellTools()
    assert "run_shell_command" in tools.functions


def test_unrestricted_by_default_runs_command():
    """Default mode executes commands — backward compatible."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir)
        assert "hello" in tools.run_shell_command(["echo", "hello"])


@pytest.mark.parametrize(
    ("runner", "code", "tail", "expected"),
    [
        ("toolkit", "print('first'); print('second')", 1, "second\n"),
        ("toolkit", "print('first'); print('second')", 2, "first\nsecond\n"),
        ("toolkit", "print('first'); print('second')", 3, "first\nsecond\n"),
        ("toolkit", "import sys; sys.stdout.write('first\\nsecond')", 1, "second"),
        ("utility", "print('first'); print('second')", 1, "second\n"),
        ("utility", "print('first'); print('second')", 2, "first\nsecond\n"),
        ("utility", "print('first'); print('second')", 3, "first\nsecond\n"),
        ("utility", "import sys; sys.stdout.write('first\\nsecond')", 1, "second"),
    ],
)
def test_tail_counts_output_lines_without_synthetic_trailing_line(runner, code, tail, expected):
    """A trailing newline must not consume one of the requested output lines."""
    args = [sys.executable, "-c", code]
    if runner == "toolkit":
        result = ShellTools().run_shell_command(args, tail=tail)
    else:
        result = run_shell_command(args, tail=tail)

    assert result == expected


def test_requires_confirmation_tools_gates_run_shell_command():
    """The documented HITL pattern marks run_shell_command for confirmation."""
    tools = ShellTools(requires_confirmation_tools=["run_shell_command"])
    assert tools.functions["run_shell_command"].requires_confirmation is True
