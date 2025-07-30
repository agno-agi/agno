"""Test DaytonaTools functionality."""

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
def mock_daytona():
    """Create mock Daytona objects."""
    with patch("agno.tools.daytona.Daytona") as mock_daytona_class:
        mock_client = mock_daytona_class.return_value
        mock_sandbox = MagicMock()
        mock_sandbox.id = "test-sandbox-123"
        mock_client.create.return_value = mock_sandbox

        # Mock process and fs
        mock_process = MagicMock()
        mock_fs = MagicMock()
        mock_sandbox.process = mock_process
        mock_sandbox.fs = mock_fs

        yield mock_client, mock_sandbox, mock_process, mock_fs


class TestDaytonaTools:
    """Test DaytonaTools class."""

    def test_initialization_with_api_key(self):
        """Test initialization with API key."""
        with patch.dict("os.environ", {"DAYTONA_API_KEY": "test-key"}):
            tools = DaytonaTools()
            assert tools.api_key == "test-key"
            assert tools.persistent is True

    def test_initialization_without_api_key(self):
        """Test initialization without API key."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="DAYTONA_API_KEY not set"):
                DaytonaTools()

    def test_working_directory_management(self, mock_agent):
        """Test working directory get/set methods."""
        with patch.dict("os.environ", {"DAYTONA_API_KEY": "test-key"}):
            tools = DaytonaTools()

            # Test get with no directory set
            assert tools._get_working_directory(mock_agent) == "/home/daytona"

            # Test set
            tools._set_working_directory(mock_agent, "/tmp")
            assert mock_agent.session_state["working_directory"] == "/tmp"

            # Test get with directory set
            assert tools._get_working_directory(mock_agent) == "/tmp"

    def test_create_sandbox_persistent(self, mock_daytona, mock_agent):
        """Test persistent sandbox creation."""
        mock_client, mock_sandbox, _, _ = mock_daytona

        with patch.dict("os.environ", {"DAYTONA_API_KEY": "test-key"}):
            tools = DaytonaTools(persistent=True)

            # Mock the get method to return the same sandbox
            mock_client.get.return_value = mock_sandbox

            # First call creates sandbox
            sandbox1 = tools._get_or_create_sandbox(mock_agent)
            assert sandbox1 == mock_sandbox
            assert mock_agent.session_state["sandbox_id"] == "test-sandbox-123"

            # Second call reuses sandbox via get()
            sandbox2 = tools._get_or_create_sandbox(mock_agent)
            assert sandbox2 == mock_sandbox
            assert mock_client.create.call_count == 1  # Only called once
            assert mock_client.get.call_count >= 1  # get() called to retrieve existing sandbox

    def test_create_sandbox_non_persistent(self, mock_daytona, mock_agent):
        """Test non-persistent sandbox creation."""
        mock_client, mock_sandbox, _, _ = mock_daytona

        with patch.dict("os.environ", {"DAYTONA_API_KEY": "test-key"}):
            tools = DaytonaTools(persistent=False)

            # Each call creates new sandbox
            _ = tools._get_or_create_sandbox(mock_agent)
            _ = tools._get_or_create_sandbox(mock_agent)
            assert mock_client.create.call_count == 2  # Called twice

    def test_run_python_code(self, mock_daytona, mock_agent):
        """Test run_code method with Python code."""
        mock_client, mock_sandbox, mock_process, _ = mock_daytona

        with patch.dict("os.environ", {"DAYTONA_API_KEY": "test-key"}):
            tools = DaytonaTools()

            # Mock execution result
            mock_execution = MagicMock()
            mock_execution.result = "Hello, World!"
            mock_process.code_run.return_value = mock_execution

            # Test execution
            result = tools.run_code(mock_agent, "print('Hello, World!')")
            assert result == "Hello, World!"

    def test_run_shell_command(self, mock_daytona, mock_agent):
        """Test run_shell_command method."""
        mock_client, mock_sandbox, mock_process, _ = mock_daytona

        with patch.dict("os.environ", {"DAYTONA_API_KEY": "test-key"}):
            tools = DaytonaTools()

            # Mock execution
            mock_execution = MagicMock()
            mock_execution.exit_code = 0
            mock_execution.result = "total 4\nfile1.txt\nfile2.txt"
            mock_process.exec.return_value = mock_execution

            # Test shell command
            result = tools.run_shell_command(mock_agent, "ls -la")
            assert "total 4" in result

    def test_run_shell_command_cd(self, mock_daytona, mock_agent):
        """Test run_shell_command with cd command."""
        mock_client, mock_sandbox, mock_process, _ = mock_daytona

        with patch.dict("os.environ", {"DAYTONA_API_KEY": "test-key"}):
            tools = DaytonaTools()

            # Test with a simple absolute path that won't be resolved
            mock_test = MagicMock()
            mock_test.result = "exists"

            mock_process.exec.return_value = mock_test

            # Test cd command
            result = tools.run_shell_command(mock_agent, "cd /home/test")
            assert "Changed directory to:" in result
            assert "/home/test" in result

    def test_create_file(self, mock_daytona, mock_agent):
        """Test create_file method."""
        mock_client, mock_sandbox, mock_process, _ = mock_daytona

        with patch.dict("os.environ", {"DAYTONA_API_KEY": "test-key"}):
            tools = DaytonaTools()

            # Mock successful file creation
            mock_execution = MagicMock()
            mock_execution.exit_code = 0
            mock_process.exec.return_value = mock_execution

            # Test file creation
            result = tools.create_file(mock_agent, "test.txt", "Hello, World!")
            assert "File created/updated: /home/daytona/test.txt" in result

    def test_read_file(self, mock_daytona, mock_agent):
        """Test read_file method."""
        mock_client, mock_sandbox, mock_process, _ = mock_daytona

        with patch.dict("os.environ", {"DAYTONA_API_KEY": "test-key"}):
            tools = DaytonaTools()

            # Mock file read
            mock_execution = MagicMock()
            mock_execution.exit_code = 0
            mock_execution.result = "File contents"
            mock_process.exec.return_value = mock_execution

            # Test file read
            result = tools.read_file(mock_agent, "test.txt")
            assert result == "File contents"

    def test_list_files(self, mock_daytona, mock_agent):
        """Test list_files method."""
        mock_client, mock_sandbox, mock_process, _ = mock_daytona

        with patch.dict("os.environ", {"DAYTONA_API_KEY": "test-key"}):
            tools = DaytonaTools()

            # Mock ls output
            mock_execution = MagicMock()
            mock_execution.exit_code = 0
            mock_execution.result = "file1.txt\nfile2.py\ndir1/"
            mock_process.exec.return_value = mock_execution

            # Test list files
            result = tools.list_files(mock_agent, ".")
            assert "file1.txt" in result
            assert "file2.py" in result

    def test_delete_file(self, mock_daytona, mock_agent):
        """Test delete_file method."""
        mock_client, mock_sandbox, mock_process, _ = mock_daytona

        with patch.dict("os.environ", {"DAYTONA_API_KEY": "test-key"}):
            tools = DaytonaTools()

            # Mock file check and deletion
            mock_check = MagicMock()
            mock_check.result = "file"
            mock_delete = MagicMock()
            mock_delete.exit_code = 0

            mock_process.exec.side_effect = [
                mock_check,  # test -d check
                mock_delete,  # rm command
            ]

            # Test file deletion
            result = tools.delete_file(mock_agent, "test.txt")
            assert result == "Deleted: /home/daytona/test.txt"

    def test_change_directory(self, mock_daytona, mock_agent):
        """Test change_directory method."""
        mock_client, mock_sandbox, mock_process, _ = mock_daytona

        with patch.dict("os.environ", {"DAYTONA_API_KEY": "test-key"}):
            tools = DaytonaTools()

            # Mock the test -d response to indicate directory exists
            mock_test = MagicMock()
            mock_test.result = "exists"

            mock_process.exec.return_value = mock_test

            # Test directory change
            result = tools.change_directory(mock_agent, "/home/test")
            assert "Changed directory to:" in result
            assert "/home/test" in result

            # Check that working directory was updated
            assert mock_agent.session_state["working_directory"] == "/home/test"

    def test_ssl_configuration(self):
        """Test SSL configuration."""
        with patch.dict("os.environ", {"DAYTONA_API_KEY": "test-key"}):
            # Test with SSL verification disabled
            tools = DaytonaTools(verify_ssl=False)
            assert tools.verify_ssl is False

            # Test with SSL verification enabled (default)
            tools = DaytonaTools(verify_ssl=True)
            assert tools.verify_ssl is True

    def test_error_handling(self, mock_daytona, mock_agent):
        """Test error handling in various methods."""
        mock_client, mock_sandbox, mock_process, _ = mock_daytona

        with patch.dict("os.environ", {"DAYTONA_API_KEY": "test-key"}):
            tools = DaytonaTools()

            # Test error in run_code
            mock_process.code_run.side_effect = Exception("Execution error")
            result = tools.run_code(mock_agent, "print('test')")
            assert "error" in result
            assert "Execution error" in result
