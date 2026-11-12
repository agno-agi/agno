"""Tests for ShellTools.run_shell_command and agno.utils.shell."""

import sys
import tempfile

from agno.tools.shell import ShellTools


def test_unrestricted_by_default_runs_command():
    """Default mode executes commands — backward compatible."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir)
        assert "hello" in tools.run_shell_command(["echo", "hello"])


def test_run_shell_command_non_utf8_bytes_do_not_error():
    """Undecodable stdout must not fail the call (#11580)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir)
        out = tools.run_shell_command(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'caf' + bytes([0xE9]))"]
        )
        assert out == "caf\ufffd"
        assert not out.startswith("Error")


def test_utils_shell_non_utf8_bytes_do_not_error():
    """Undecodable stdout must not fail the utils helper (#11580)."""
    from agno.utils.shell import run_shell_command as util_run_shell_command

    out = util_run_shell_command([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'caf' + bytes([0xE9]))"])
    assert out == "caf\ufffd"
    assert not out.startswith("Error")
