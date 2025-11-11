"""Unit tests for E2BTools class."""

import os
import sys
from unittest.mock import Mock, patch

import pytest

from agno.agent import Agent
from agno.media import Image
from agno.tools.function import ToolResult

# Mock the e2b_code_interpreter module before importing E2BTools
with patch.dict("sys.modules", {"e2b_code_interpreter": Mock()}):
    # Create a mock Sandbox class
    mock_sandbox_class = Mock()
    sys.modules["e2b_code_interpreter"].Sandbox = mock_sandbox_class

    # Now import the E2BTools class
    from agno.tools.e2b import E2BTools

TEST_API_KEY = os.environ.get("E2B_API_KEY", "test_api_key")


@pytest.fixture
def mock_agent():
    """Create a mocked Agent instance."""
    agent = Mock(spec=Agent)
    return agent


@pytest.fixture
def mock_e2b_tools():
    """Create a mocked E2BTools instance with patched methods."""
    # Patch the Sandbox import at the module level
    with patch("agno.tools.e2b.Sandbox") as mock_sandbox_class:
        # Set up our mock sandbox instance
        mock_sandbox = Mock()
        mock_sandbox_class.return_value = mock_sandbox

        # Set up sandbox attributes and methods
        mock_sandbox.files = Mock()
        mock_sandbox.commands = Mock()
        mock_sandbox.get_host = Mock(return_value="example.com:8080")
        mock_sandbox.kill = Mock()
        mock_sandbox.list = Mock()
        mock_sandbox.id = "test-sandbox-123"

        # Create the E2BTools instance with our patched Sandbox
        with patch.dict("os.environ", {"E2B_API_KEY": TEST_API_KEY}):
            tools = E2BTools()

            # Mock the methods we'll test
            tools.run_python_code = Mock(return_value='["Logs:\\nHello, World!"]')
            tools.upload_file = Mock(return_value="/sandbox/file.txt")

            # Mock ToolResult returns for updated methods
            mock_image_result = ToolResult(
                content="Image added as artifact with ID test-image-id", images=[Mock(spec=Image)]
            )
            tools.download_png_result = Mock(return_value=mock_image_result)

            mock_chart_result = ToolResult(
                content="Interactive bar chart data saved to /local/output.json\nTitle: Sample Chart\nX-axis: Categories\nY-axis: Values\n"
            )
            tools.download_chart_data = Mock(return_value=mock_chart_result)

            tools.download_file_from_sandbox = Mock(return_value="/local/output.txt")
            tools.list_files = Mock(
                return_value="Contents of /:\n- file1.txt (File, 100 bytes)\n- dir1 (Directory, Unknown size)\n"
            )
            tools.read_file_content = Mock(return_value="file content")
            tools.write_file_content = Mock(return_value="/sandbox/file.txt")
            tools.get_public_url = Mock(return_value="http://example.com")
            tools.run_server = Mock(return_value="http://example.com")
            tools.set_sandbox_timeout = Mock(return_value="600")
            tools.get_sandbox_status = Mock(return_value="sandbox-id-12345")
            tools.shutdown_sandbox = Mock(
                return_value='{"status": "success", "message": "Sandbox shut down successfully"}'
            )
            tools.run_command = Mock(return_value='["STDOUT:\\ncommand output"]')
            tools.stream_command = Mock(return_value='["STDOUT: command output", "STDERR: some warning"]')
            tools.run_background_command = Mock(return_value=Mock())
            tools.kill_background_command = Mock(return_value="Background command terminated successfully.")
            tools.watch_directory = Mock(
                return_value='{"status": "success", "message": "Changes detected in /dir over 1 seconds:\\nmodified - /dir/file1.txt\\ncreated - /dir/file2.txt"}'
            )
            tools.list_running_sandboxes = Mock(
                return_value='{"status": "success", "message": "Found 2 running sandboxes", "sandboxes": [{"sandbox_id": "sb-123", "started_at": "2023-01-01T12:00:00", "template_id": "tmpl-123", "metadata": {}}]}'
            )

            return tools


def test_init_with_api_key():
    """Test initialization with provided API key."""
    with patch("agno.tools.e2b.Sandbox"):
        tools = E2BTools(api_key=TEST_API_KEY)
        assert tools.api_key == TEST_API_KEY


def test_init_with_env_var():
    """Test initialization with environment variable."""
    with patch("agno.tools.e2b.Sandbox"):
        with patch.dict("os.environ", {"E2B_API_KEY": TEST_API_KEY}):
            tools = E2BTools()
            assert tools.api_key == TEST_API_KEY


def test_init_without_api_key():
    """Test initialization without API key raises error."""
    with patch.dict("os.environ", clear=True):
        with pytest.raises(ValueError, match="E2B_API_KEY not set"):
            E2BTools()


def test_init_with_selective_tools():
    """Test initialization with only selected tools enabled."""
    with patch("agno.tools.e2b.Sandbox"):
        with patch.dict("os.environ", {"E2B_API_KEY": TEST_API_KEY}):
            tools = E2BTools(
                include_tools=["run_python_code", "list_files", "run_command"],
                exclude_tools=["upload_file", "download_png_result", "get_public_url"],
            )

            # Check enabled functions
            function_names = [func.name for func in tools.functions.values()]
            assert "run_python_code" in function_names
            assert "list_files" in function_names
            assert "run_command" in function_names

            # Check disabled functions
            assert "upload_file" not in function_names
            assert "download_png_result" not in function_names
            assert "get_public_url" not in function_names


def test_run_python_code(mock_e2b_tools):
    """Test Python code execution."""
    # Call the method with lowercase keywords
    mock_e2b_tools.run_python_code("if x == true and y == false and z == none:")

    # Verify the method was called with exactly what we passed in
    mock_e2b_tools.run_python_code.assert_called_once_with("if x == true and y == false and z == none:")

    # Reset the mock for the next test
    mock_e2b_tools.run_python_code.reset_mock()

    # Test a regular code execution
    result = mock_e2b_tools.run_python_code("print('Hello, World!')")

    # Verify regular code execution
    mock_e2b_tools.run_python_code.assert_called_once_with("print('Hello, World!')")
    assert "Logs:\\nHello, World!" in result


def test_upload_file(mock_e2b_tools):
    """Test file upload."""
    result = mock_e2b_tools.upload_file("/local/file.txt")

    mock_e2b_tools.upload_file.assert_called_once_with("/local/file.txt")
    assert result == "/sandbox/file.txt"


def test_download_png_result(mock_e2b_tools, mock_agent):
    """Test downloading a PNG result."""
    result = mock_e2b_tools.download_png_result(mock_agent, 0, "/local/output.png")

    mock_e2b_tools.download_png_result.assert_called_once_with(mock_agent, 0, "/local/output.png")

    # Check that it returns a ToolResult
    assert isinstance(result, ToolResult)
    assert "Image added as artifact with ID" in result.content
    assert result.images is not None
    assert len(result.images) == 1


def test_download_chart_data(mock_e2b_tools, mock_agent):
    """Test downloading chart data."""
    result = mock_e2b_tools.download_chart_data(mock_agent, 0, "/local/output.json")

    mock_e2b_tools.download_chart_data.assert_called_once_with(mock_agent, 0, "/local/output.json")

    # Check that it returns a ToolResult
    assert isinstance(result, ToolResult)
    assert "Interactive bar chart data saved to" in result.content
    assert "Title: Sample Chart" in result.content


def test_download_file_from_sandbox(mock_e2b_tools):
    """Test downloading a file from the sandbox."""
    result = mock_e2b_tools.download_file_from_sandbox("/sandbox/file.txt", "/local/output.txt")

    mock_e2b_tools.download_file_from_sandbox.assert_called_once_with("/sandbox/file.txt", "/local/output.txt")
    assert result == "/local/output.txt"


def test_run_command(mock_e2b_tools):
    """Test running a command."""
    result = mock_e2b_tools.run_command("ls -la")

    mock_e2b_tools.run_command.assert_called_once_with("ls -la")
    assert result == '["STDOUT:\\ncommand output"]'


def test_stream_command(mock_e2b_tools):
    """Test streaming a command."""
    result = mock_e2b_tools.stream_command("echo hello")

    mock_e2b_tools.stream_command.assert_called_once_with("echo hello")
    assert "STDOUT: command output" in result
    assert "STDERR: some warning" in result


def test_list_files(mock_e2b_tools):
    """Test listing files."""
    result = mock_e2b_tools.list_files("/")

    mock_e2b_tools.list_files.assert_called_once_with("/")
    assert "Contents of /:" in result
    assert "file1.txt (File, 100 bytes)" in result


def test_read_file_content(mock_e2b_tools):
    """Test reading file content."""
    result = mock_e2b_tools.read_file_content("/file.txt")

    mock_e2b_tools.read_file_content.assert_called_once_with("/file.txt")
    assert result == "file content"


def test_write_file_content(mock_e2b_tools):
    """Test writing file content."""
    result = mock_e2b_tools.write_file_content("/file.txt", "content")

    mock_e2b_tools.write_file_content.assert_called_once_with("/file.txt", "content")
    assert result == "/sandbox/file.txt"


def test_get_public_url(mock_e2b_tools):
    """Test getting a public URL."""
    result = mock_e2b_tools.get_public_url(8080)

    mock_e2b_tools.get_public_url.assert_called_once_with(8080)
    assert result == "http://example.com"


def test_run_server(mock_e2b_tools):
    """Test running a server."""
    result = mock_e2b_tools.run_server("python -m http.server", 8080)

    mock_e2b_tools.run_server.assert_called_once_with("python -m http.server", 8080)
    assert result == "http://example.com"


def test_set_sandbox_timeout(mock_e2b_tools):
    """Test setting sandbox timeout."""
    result = mock_e2b_tools.set_sandbox_timeout(600)

    mock_e2b_tools.set_sandbox_timeout.assert_called_once_with(600)
    assert result == "600"


def test_get_sandbox_status(mock_e2b_tools):
    """Test getting sandbox status."""
    result = mock_e2b_tools.get_sandbox_status()

    mock_e2b_tools.get_sandbox_status.assert_called_once()
    assert result == "sandbox-id-12345"


def test_shutdown_sandbox(mock_e2b_tools):
    """Test shutting down the sandbox."""
    result = mock_e2b_tools.shutdown_sandbox()

    mock_e2b_tools.shutdown_sandbox.assert_called_once()
    assert '"status": "success"' in result
    assert '"message": "Sandbox shut down successfully"' in result


def test_run_background_command(mock_e2b_tools):
    """Test running a background command."""
    result = mock_e2b_tools.run_background_command("sleep 30")

    mock_e2b_tools.run_background_command.assert_called_once_with("sleep 30")
    assert isinstance(result, Mock)


def test_kill_background_command(mock_e2b_tools):
    """Test killing a background command."""
    process_mock = Mock()
    result = mock_e2b_tools.kill_background_command(process_mock)

    mock_e2b_tools.kill_background_command.assert_called_once_with(process_mock)
    assert result == "Background command terminated successfully."


def test_watch_directory(mock_e2b_tools):
    """Test watching a directory."""
    result = mock_e2b_tools.watch_directory("/dir", 1)

    mock_e2b_tools.watch_directory.assert_called_once_with("/dir", 1)
    assert '"status": "success"' in result
    assert '"message": "Changes detected in /dir' in result


def test_list_running_sandboxes(mock_e2b_tools):
    """Test listing running sandboxes."""
    result = mock_e2b_tools.list_running_sandboxes()

    mock_e2b_tools.list_running_sandboxes.assert_called_once()
    assert '"status": "success"' in result
    assert '"message": "Found 2 running sandboxes"' in result
    assert '"sandbox_id": "sb-123"' in result
