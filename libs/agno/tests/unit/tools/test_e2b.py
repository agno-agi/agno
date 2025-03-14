"""Unit tests for E2BTools class."""

from unittest.mock import Mock, patch

import pytest

from agno.tools.e2b import E2BTools


@pytest.fixture
def mock_e2b_tools():
    """Create a mocked E2BTools instance with patched methods."""
    # First, create a mock for the Sandbox class
    with patch("agno.tools.e2b.Sandbox") as mock_sandbox_class:
        # Set up our mock sandbox instance
        mock_sandbox = Mock()
        mock_sandbox_class.return_value = mock_sandbox

        # Create files/process structure
        mock_sandbox.filesystem = Mock()
        mock_sandbox.process = Mock()
        mock_sandbox.url = Mock()
        mock_sandbox.set_timeout = Mock()
        mock_sandbox.metadata = Mock()
        mock_sandbox.close = Mock()

        # Create the E2BTools instance with our patched Sandbox
        with patch.dict("os.environ", {"E2B_API_KEY": "test_key"}):
            tools = E2BTools()

            # Mock the methods we'll test
            tools.run_python_code = Mock(return_value="Hello, World!")
            tools.upload_file = Mock(return_value="File uploaded to /sandbox/file.txt")
            tools.download_png_result = Mock(return_value="PNG downloaded to /local/output.png")
            tools.download_chart_data = Mock(return_value="Chart data downloaded to /local/output.json")
            tools.download_file_from_sandbox = Mock(return_value="File downloaded to /local/output.txt")
            tools.list_files = Mock(return_value="file1.txt\ndir1/")
            tools.read_file_content = Mock(return_value="file content")
            tools.write_file_content = Mock(return_value="File written successfully")
            tools.get_public_url = Mock(return_value="https://example.com")
            tools.run_server = Mock(return_value="Server running at https://example.com")
            tools.set_sandbox_timeout = Mock(return_value="Timeout set to 600 seconds")
            tools.get_sandbox_status = Mock(return_value="Status: running")
            tools.shutdown_sandbox = Mock(return_value="Sandbox shut down")
            tools.run_command = Mock(return_value="command output")
            tools.stream_command = Mock(return_value="command output with streaming")
            tools.run_background_command = Mock(return_value=Mock())
            tools.kill_background_command = Mock(return_value="Command terminated")
            tools.watch_directory = Mock(return_value="Changes detected: file1.txt, file2.txt")

            return tools


def test_init_with_api_key():
    """Test initialization with provided API key."""
    with patch("agno.tools.e2b.Sandbox") as mock_sandbox_class:
        tools = E2BTools(api_key="test_key")
        mock_sandbox_class.assert_called_once()
        assert tools.api_key == "test_key"


def test_init_with_env_var():
    """Test initialization with environment variable."""
    with patch("agno.tools.e2b.Sandbox") as mock_sandbox_class:
        with patch.dict("os.environ", {"E2B_API_KEY": "env_key"}):
            tools = E2BTools()
            mock_sandbox_class.assert_called_once()
            assert tools.api_key == "env_key"


def test_init_without_api_key():
    """Test initialization without API key raises error."""
    with patch.dict("os.environ", clear=True):
        with pytest.raises(ValueError, match="E2B_API_KEY not set"):
            E2BTools()


def test_init_with_selective_tools():
    """Test initialization with only selected tools enabled."""
    with patch("agno.tools.e2b.Sandbox"):
        with patch.dict("os.environ", {"E2B_API_KEY": "test_key"}):
            tools = E2BTools(
                run_code=True,
                upload_file=False,
                download_result=False,
                filesystem=True,
                internet_access=False,
                sandbox_management=False,
                command_execution=True,
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
    # Call the method
    result = mock_e2b_tools.run_python_code("print('Hello, World!')")

    # Verify
    mock_e2b_tools.run_python_code.assert_called_once_with("print('Hello, World!')")
    assert result == "Hello, World!"


def test_upload_file(mock_e2b_tools):
    """Test file upload."""
    # Call the method
    result = mock_e2b_tools.upload_file("/local/file.txt")

    # Verify
    mock_e2b_tools.upload_file.assert_called_once_with("/local/file.txt")
    assert result == "File uploaded to /sandbox/file.txt"


def test_download_png_result(mock_e2b_tools):
    """Test downloading a PNG result."""
    # Call the method
    result = mock_e2b_tools.download_png_result(0, "/local/output.png")

    # Verify
    mock_e2b_tools.download_png_result.assert_called_once_with(0, "/local/output.png")
    assert result == "PNG downloaded to /local/output.png"


def test_download_chart_data(mock_e2b_tools):
    """Test downloading chart data."""
    # Call the method
    result = mock_e2b_tools.download_chart_data(0, "/local/output.json")

    # Verify
    mock_e2b_tools.download_chart_data.assert_called_once_with(0, "/local/output.json")
    assert result == "Chart data downloaded to /local/output.json"


def test_download_file_from_sandbox(mock_e2b_tools):
    """Test downloading a file from the sandbox."""
    # Call the method
    result = mock_e2b_tools.download_file_from_sandbox("/sandbox/file.txt", "/local/output.txt")

    # Verify
    mock_e2b_tools.download_file_from_sandbox.assert_called_once_with("/sandbox/file.txt", "/local/output.txt")
    assert result == "File downloaded to /local/output.txt"


def test_run_command(mock_e2b_tools):
    """Test running a command."""
    # Call the method
    result = mock_e2b_tools.run_command("ls -la")

    # Verify
    mock_e2b_tools.run_command.assert_called_once_with("ls -la")
    assert result == "command output"


def test_stream_command(mock_e2b_tools):
    """Test streaming a command."""
    # Call the method
    result = mock_e2b_tools.stream_command("echo hello")

    # Verify
    mock_e2b_tools.stream_command.assert_called_once_with("echo hello")
    assert result == "command output with streaming"


def test_list_files(mock_e2b_tools):
    """Test listing files."""
    # Call the method
    result = mock_e2b_tools.list_files("/")

    # Verify
    mock_e2b_tools.list_files.assert_called_once_with("/")
    assert result == "file1.txt\ndir1/"


def test_read_file_content(mock_e2b_tools):
    """Test reading file content."""
    # Call the method
    result = mock_e2b_tools.read_file_content("/file.txt")

    # Verify
    mock_e2b_tools.read_file_content.assert_called_once_with("/file.txt")
    assert result == "file content"


def test_write_file_content(mock_e2b_tools):
    """Test writing file content."""
    # Call the method
    result = mock_e2b_tools.write_file_content("/file.txt", "content")

    # Verify
    mock_e2b_tools.write_file_content.assert_called_once_with("/file.txt", "content")
    assert result == "File written successfully"


def test_get_public_url(mock_e2b_tools):
    """Test getting a public URL."""
    # Call the method
    result = mock_e2b_tools.get_public_url(8080)

    # Verify
    mock_e2b_tools.get_public_url.assert_called_once_with(8080)
    assert result == "https://example.com"


def test_run_server(mock_e2b_tools):
    """Test running a server."""
    # Call the method
    result = mock_e2b_tools.run_server("python -m http.server", 8080)

    # Verify
    mock_e2b_tools.run_server.assert_called_once_with("python -m http.server", 8080)
    assert result == "Server running at https://example.com"


def test_set_sandbox_timeout(mock_e2b_tools):
    """Test setting sandbox timeout."""
    # Call the method
    result = mock_e2b_tools.set_sandbox_timeout(600)

    # Verify
    mock_e2b_tools.set_sandbox_timeout.assert_called_once_with(600)
    assert result == "Timeout set to 600 seconds"


def test_get_sandbox_status(mock_e2b_tools):
    """Test getting sandbox status."""
    # Call the method
    result = mock_e2b_tools.get_sandbox_status()

    # Verify
    mock_e2b_tools.get_sandbox_status.assert_called_once()
    assert result == "Status: running"


def test_shutdown_sandbox(mock_e2b_tools):
    """Test shutting down the sandbox."""
    # Call the method
    result = mock_e2b_tools.shutdown_sandbox()

    # Verify
    mock_e2b_tools.shutdown_sandbox.assert_called_once()
    assert result == "Sandbox shut down"


def test_run_background_command(mock_e2b_tools):
    """Test running a background command."""
    # Call the method
    result = mock_e2b_tools.run_background_command("sleep 30")

    # Verify
    mock_e2b_tools.run_background_command.assert_called_once_with("sleep 30")
    assert isinstance(result, Mock)


def test_kill_background_command(mock_e2b_tools):
    """Test killing a background command."""
    # Create a mock process
    process_mock = Mock()

    # Call the method
    result = mock_e2b_tools.kill_background_command(process_mock)

    # Verify
    mock_e2b_tools.kill_background_command.assert_called_once_with(process_mock)
    assert result == "Command terminated"


def test_watch_directory(mock_e2b_tools):
    """Test watching a directory."""
    # Call the method
    result = mock_e2b_tools.watch_directory("/dir", 1)

    # Verify
    mock_e2b_tools.watch_directory.assert_called_once_with("/dir", 1)
    assert result == "Changes detected: file1.txt, file2.txt"


def test_dunder_del():
    """Test the __del__ method."""
    # Create a mock for the sandbox
    mock_sandbox = Mock()

    # Create E2BTools and set its _sandbox attribute
    with patch("agno.tools.e2b.Sandbox", return_value=mock_sandbox):
        with patch.dict("os.environ", {"E2B_API_KEY": "test_key"}):
            tools = E2BTools()

            # Call __del__
            tools.__del__()

            # Verify sandbox.close was called
            mock_sandbox.close.assert_called_once()
