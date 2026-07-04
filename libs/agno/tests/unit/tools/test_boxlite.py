"""Test BoxLiteTools functionality."""

import base64
import re
import shlex
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock the boxlite module before importing BoxLiteTools so the import guard passes
# without the native runtime being installed.
sys.modules["boxlite"] = MagicMock()

from agno.tools.boxlite import BoxLiteTools  # noqa: E402


def _exec_result(stdout: str = "", stderr: str = "", exit_code: int = 0) -> MagicMock:
    """Build a mock that quacks like boxlite.ExecResult."""
    result = MagicMock()
    result.stdout = stdout
    result.stderr = stderr
    result.exit_code = exit_code
    return result


@pytest.fixture
def mock_box() -> MagicMock:
    """A mock SimpleBox whose async methods resolve on the toolkit's private loop."""
    box = MagicMock()
    box.start = AsyncMock(return_value=None)
    box.stop = AsyncMock(return_value=None)
    box.exec = AsyncMock(return_value=_exec_result())
    return box


@pytest.fixture
def tools(mock_box):
    """Construct BoxLiteTools with a mocked box, then hand back a clean exec mock."""
    with patch("agno.tools.boxlite.SimpleBox") as sync_box_cls:
        sync_box_cls.return_value = mock_box
        toolkit = BoxLiteTools()
        # __init__ boots the box and bootstraps the working dir; drop those calls so
        # each test asserts only against the exec calls it triggers.
        mock_box.exec.reset_mock()
        mock_box.exec.return_value = _exec_result()
        mock_box.exec.side_effect = None
        try:
            yield toolkit, mock_box
        finally:
            toolkit.shutdown_sandbox()


def _last_shell_command(mock_box: MagicMock) -> str:
    """Return the `sh -c <command>` string from the most recent exec call."""
    args = mock_box.exec.call_args.args
    assert args[0] == "sh" and args[1] == "-c"
    return args[2]


class TestBoxLiteTools:
    def test_initialization_boots_box(self, mock_box):
        """The box is created from the given image and started during __init__."""
        with patch("agno.tools.boxlite.SimpleBox") as sync_box_cls:
            sync_box_cls.return_value = mock_box
            toolkit = BoxLiteTools(image="alpine:latest")
            try:
                sync_box_cls.assert_called_once()
                assert sync_box_cls.call_args.kwargs["image"] == "alpine:latest"
                mock_box.start.assert_awaited_once()
                # __init__ bootstraps the working directory via mkdir -p.
                assert "mkdir -p" in _last_shell_command(mock_box)
            finally:
                toolkit.shutdown_sandbox()

    def test_run_code(self, tools):
        """run_code executes `python -c <code>` and returns combined output."""
        toolkit, mock_box = tools
        mock_box.exec.return_value = _exec_result(stdout="Hello, World!\n")

        result = toolkit.run_code("print('Hello, World!')")

        assert result == "Hello, World!\n"
        call = mock_box.exec.call_args
        assert call.args[0] == "python" and call.args[1] == "-c"
        assert call.kwargs["cwd"] == "/root"

    def test_run_code_surfaces_stderr(self, tools):
        """A failing script returns its traceback (stderr) to the agent."""
        toolkit, mock_box = tools
        mock_box.exec.return_value = _exec_result(stderr="Traceback: boom\n", exit_code=1)

        result = toolkit.run_code("raise SystemExit(1)")

        assert "Traceback: boom" in result

    def test_run_shell_command(self, tools):
        """run_shell_command wraps the command in `sh -c` at the working directory."""
        toolkit, mock_box = tools
        mock_box.exec.return_value = _exec_result(stdout="file1.txt\nfile2.txt")

        result = toolkit.run_shell_command("ls -la")

        assert "file1.txt" in result
        assert _last_shell_command(mock_box) == "ls -la"
        assert mock_box.exec.call_args.kwargs["cwd"] == "/root"

    def test_run_shell_command_cd_updates_working_directory(self, tools):
        """A bare `cd` is intercepted and updates the tracked working directory."""
        toolkit, mock_box = tools
        mock_box.exec.return_value = _exec_result(stdout="exists\n")

        result = toolkit.run_shell_command("cd /workspace")

        assert "Changed directory to: /workspace" in result
        assert toolkit._cwd == "/workspace"
        assert _last_shell_command(mock_box) == "test -d /workspace && echo exists || echo missing"

    def test_create_file_roundtrips_content(self, tools):
        """create_file base64-encodes content so it survives the shell verbatim."""
        toolkit, mock_box = tools
        mock_box.exec.return_value = _exec_result(exit_code=0)

        content = "line1\n'quotes' and $VARS and \"double\"\nEOF\n"
        result = toolkit.create_file("out.txt", content)

        assert result == "File created/updated: /root/out.txt"
        command = _last_shell_command(mock_box)
        # The path is shell-quoted, and the emitted base64 decodes back to the content.
        assert shlex.quote("/root/out.txt") in command
        token = re.search(r"printf %s (\S+) \| base64 -d", command).group(1)
        emitted_b64 = shlex.split(token)[0]
        assert base64.b64decode(emitted_b64).decode("utf-8") == content

    def test_create_file_quotes_injected_path(self, tools):
        """A path with shell metacharacters is quoted, not executed."""
        toolkit, mock_box = tools
        mock_box.exec.return_value = _exec_result(exit_code=0)

        toolkit.create_file("evil; id;.txt", "data")

        command = _last_shell_command(mock_box)
        assert shlex.quote("/root/evil; id;.txt") in command
        assert "; id;" not in command.replace(shlex.quote("/root/evil; id;.txt"), "")

    def test_read_file(self, tools):
        """read_file cats the resolved, quoted path and returns stdout."""
        toolkit, mock_box = tools
        mock_box.exec.return_value = _exec_result(stdout="file contents")

        result = toolkit.read_file("notes.txt")

        assert result == "file contents"
        assert _last_shell_command(mock_box) == f"cat {shlex.quote('/root/notes.txt')}"

    def test_read_file_error(self, tools):
        """A non-zero exit is reported as a JSON error, not returned as content."""
        toolkit, mock_box = tools
        mock_box.exec.return_value = _exec_result(stderr="No such file", exit_code=1)

        result = toolkit.read_file("missing.txt")

        assert '"status": "error"' in result
        assert "No such file" in result

    def test_list_files(self, tools):
        """list_files runs `ls -la` against the quoted path."""
        toolkit, mock_box = tools
        mock_box.exec.return_value = _exec_result(stdout="total 0\nfile1.txt")

        result = toolkit.list_files("subdir")

        assert "file1.txt" in result
        assert _last_shell_command(mock_box) == f"ls -la {shlex.quote('/root/subdir')}"

    def test_delete_file(self, tools):
        """delete_file checks the type then removes with the right flags."""
        toolkit, mock_box = tools
        mock_box.exec.side_effect = [
            _exec_result(stdout="file\n"),  # test -d ... -> "file"
            _exec_result(exit_code=0),  # rm -f ...
        ]

        result = toolkit.delete_file("stale.txt")

        assert result == "Deleted: /root/stale.txt"
        assert mock_box.exec.call_args_list[1].args[2] == f"rm -f {shlex.quote('/root/stale.txt')}"

    def test_change_directory_missing(self, tools):
        """Changing to a non-existent directory leaves the working directory unchanged."""
        toolkit, mock_box = tools
        mock_box.exec.return_value = _exec_result(stdout="missing\n")

        result = toolkit.change_directory("/does/not/exist")

        assert "not found" in result
        assert toolkit._cwd == "/root"

    def test_error_handling(self, tools):
        """Exceptions from the SDK are caught and returned as JSON errors."""
        toolkit, mock_box = tools
        mock_box.exec.side_effect = RuntimeError("boom")

        result = toolkit.run_shell_command("ls")

        assert '"status": "error"' in result
        assert "boom" in result

    def test_shutdown_is_idempotent(self, mock_box):
        """shutdown_sandbox stops the box once and is safe to call repeatedly."""
        with patch("agno.tools.boxlite.SimpleBox") as sync_box_cls:
            sync_box_cls.return_value = mock_box
            toolkit = BoxLiteTools()

            first = toolkit.shutdown_sandbox()
            second = toolkit.shutdown_sandbox()

            assert "shut down" in first
            assert "shut down" in second
            mock_box.stop.assert_awaited_once()
