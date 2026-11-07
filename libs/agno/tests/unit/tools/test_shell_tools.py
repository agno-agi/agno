"""Tests for ShellTools confirmation gating.

ShellTools.run_shell_command executes an arbitrary List[str] command — an RCE
sink under prompt injection. The toolkit's requires_confirmation_tools gates it
behind human approval; these tests lock that documented pattern and guard the
kwargs passthrough against regressions.
"""

import sys
import tempfile

from agno.tools.shell import ShellTools


def test_shell_tools_registered_by_default():
    """run_shell_command is registered by default (existing contract preserved)."""
    tools = ShellTools()
    assert "run_shell_command" in tools.functions


def test_unrestricted_by_default_runs_command():
    """Default mode executes commands — backward compatible."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir)
        assert "hello" in tools.run_shell_command(["echo", "hello"])


def test_requires_confirmation_tools_gates_run_shell_command():
    """The documented HITL pattern marks run_shell_command for confirmation."""
    tools = ShellTools(requires_confirmation_tools=["run_shell_command"])
    assert tools.functions["run_shell_command"].requires_confirmation is True


def test_run_shell_command_zero_tail_returns_empty():
    """tail=0 asks for no lines; [-0:] slicing returns the whole output instead."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir)
        out = tools.run_shell_command(
            [sys.executable, "-c", "import sys; sys.stdout.write(chr(97) + chr(10) + chr(98) + chr(10) + chr(99))"],
            tail=0,
        )
        assert out == ""


def test_run_shell_command_positive_tail_returns_last_lines():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir)
        out = tools.run_shell_command(
            [sys.executable, "-c", "import sys; sys.stdout.write(chr(97) + chr(10) + chr(98) + chr(10) + chr(99))"],
            tail=2,
        )
        assert out == "b" + chr(10) + "c"


def test_utils_shell_zero_tail_returns_empty():
    from agno.utils.shell import run_shell_command as util_run_shell_command

    out = util_run_shell_command(
        [sys.executable, "-c", "import sys; sys.stdout.write(chr(97) + chr(10) + chr(98) + chr(10) + chr(99))"], tail=0
    )
    assert out == ""


_TWO_LINES = [sys.executable, "-c", "print('first'); print('second')"]


def test_run_shell_command_tail_ignores_trailing_newline():
    """A trailing newline must not take up one of the requested tail lines."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir)
        assert tools.run_shell_command(_TWO_LINES, tail=1) == "second\n"
        assert tools.run_shell_command(_TWO_LINES, tail=2) == "first\nsecond\n"
        assert tools.run_shell_command(_TWO_LINES) == "first\nsecond\n"


def test_utils_shell_tail_ignores_trailing_newline():
    from agno.utils.shell import run_shell_command as util_run_shell_command

    assert util_run_shell_command(_TWO_LINES, tail=1) == "second\n"
    assert util_run_shell_command(_TWO_LINES, tail=2) == "first\nsecond\n"


# A form feed inside a line; str.splitlines would treat it as a line break.
_FORM_FEED = [sys.executable, "-c", "print('x' + chr(12) + 'y'); print('last')"]


def test_run_shell_command_tail_counts_only_newlines():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir)
        assert tools.run_shell_command(_FORM_FEED, tail=1) == "last\n"
        assert tools.run_shell_command(_FORM_FEED, tail=2) == "x\fy\nlast\n"


def test_utils_shell_tail_counts_only_newlines():
    from agno.utils.shell import run_shell_command as util_run_shell_command

    assert util_run_shell_command(_FORM_FEED, tail=2) == "x\fy\nlast\n"
