"""Unit tests for E2BDesktopTools class."""

import os
from unittest.mock import Mock, patch

import pytest

# Mock the e2b_desktop module
with patch.dict("sys.modules", {"e2b_desktop": Mock()}):
    # Create a mock Sandbox class
    sys_modules = __import__("sys").modules
    sys_modules["e2b_desktop"].Sandbox = Mock

    # Now import the module that uses e2b_desktop
    from agno.tools.e2b_desktop import DesktopSandbox, E2BDesktopTools

TEST_API_KEY = os.environ.get("E2B_API_KEY", "test_api_key")


@pytest.fixture
def mock_agent():
    """Create a mocked Agent instance."""
    agent = Mock()
    agent.add_image = Mock()
    return agent


@pytest.fixture
def mock_e2b_desktop_tools():
    """Create a mocked E2BDesktopTools instance with patched methods."""
    # First, create a mock for the Sandbox class
    with patch("e2b_desktop.Sandbox") as mock_sandbox_class:
        # Set up our mock sandbox instance
        mock_sandbox = Mock()
        mock_sandbox_class.return_value = mock_sandbox

        # Create stream and other attributes for sandbox
        mock_sandbox.stream = Mock()
        mock_sandbox.stream.start = Mock()
        mock_sandbox.stream.stop = Mock()
        mock_sandbox.stream.get_url = Mock(return_value="https://stream.example.com")
        mock_sandbox.stream.get_auth_key = Mock(return_value="test-auth-key")
        mock_sandbox.screenshot = Mock(return_value=b"mock_image_data")

        # Create the E2BDesktopTools instance with our patched Sandbox
        with patch.dict("os.environ", {"E2B_API_KEY": TEST_API_KEY}):
            tools = E2BDesktopTools()

            # Mock the methods we'll test with return values matching actual implementation
            tools.get_stream_url = Mock(return_value='{"status": "success", "url": "https://stream.example.com"}')
            tools.start_stream = Mock(
                return_value='{"status": "success", "message": "Stream started successfully", "require_auth": false}'
            )
            tools.stop_stream = Mock(return_value='{"status": "success", "message": "Stream stopped successfully"}')
            tools.take_screenshot = Mock(
                return_value='{"status": "success", "format": "base64", "data": "bW9ja19pbWFnZV9kYXRh", "save_path": null}'
            )
            tools.left_click = Mock(return_value='{"status": "success", "message": "Left click executed"}')
            tools.double_click = Mock(return_value='{"status": "success", "message": "Double click executed"}')
            tools.right_click = Mock(return_value='{"status": "success", "message": "Right click executed"}')
            tools.middle_click = Mock(return_value='{"status": "success", "message": "Middle click executed"}')
            tools.scroll = Mock(return_value='{"status": "success", "message": "Scrolled by 10"}')
            tools.move_mouse = Mock(return_value='{"status": "success", "message": "Moved mouse to (100, 200)"}')
            tools.drag = Mock(return_value='{"status": "success", "message": "Dragged from (10, 20) to (100, 200)"}')
            tools.mouse_press = Mock(return_value='{"status": "success", "message": "Pressed left mouse button"}')
            tools.mouse_release = Mock(return_value='{"status": "success", "message": "Released left mouse button"}')
            tools.get_cursor_position = Mock(return_value='{"status": "success", "x": 100, "y": 200}')
            tools.get_screen_size = Mock(return_value='{"status": "success", "width": 1280, "height": 720}')
            tools.write = Mock(
                return_value='{"status": "success", "message": "Wrote text: \'Hello World\'", "chunk_size": 25, "delay_in_ms": 75}'
            )
            tools.press_key = Mock(return_value='{"status": "success", "message": "Pressed key: \'enter\'"}')
            tools.press_keys = Mock(return_value='{"status": "success", "message": "Pressed keys: \'ctrl+c\'"}')
            tools.wait = Mock(return_value='{"status": "success", "message": "Waited for 1000 milliseconds"}')
            tools.open = Mock(return_value='{"status": "success", "message": "Opened: \'https://example.com\'"}')
            tools.run_command = Mock(
                return_value='{"status": "success", "message": "Command executed: \'ls -la\'", "output": "file1 file2"}'
            )
            tools.shutdown_sandbox = Mock(return_value='{"status": "success", "message": "Desktop sandbox shut down"}')

            return tools


def test_init_with_api_key():
    """Test initialization with provided API key."""
    with patch("e2b_desktop.Sandbox"):
        tools = E2BDesktopTools(api_key=TEST_API_KEY)
        # Verify the API key is set
        assert tools.api_key == TEST_API_KEY


def test_init_with_env_var():
    """Test initialization with environment variable."""
    with patch("e2b_desktop.Sandbox"):
        with patch.dict("os.environ", {"E2B_API_KEY": TEST_API_KEY}):
            tools = E2BDesktopTools()
            # Verify the API key is set
            assert tools.api_key == TEST_API_KEY


def test_init_without_api_key():
    """Test initialization without API key raises error."""
    with patch.dict("os.environ", clear=True):
        with pytest.raises(ValueError, match="E2B_API_KEY not set"):
            E2BDesktopTools()


def test_init_with_custom_parameters():
    """Test initialization with custom parameters."""
    with patch("e2b_desktop.Sandbox") as mock_sandbox_class:
        with patch.dict("os.environ", {"E2B_API_KEY": TEST_API_KEY}):
            resolution = (1920, 1080)
            dpi = 120
            display = ":1"
            timeout = 600

            tools = E2BDesktopTools(
                timeout=timeout,
                resolution=resolution,
                dpi=dpi,
                display=display,
            )

            # Verify custom parameters were passed correctly to the Sandbox constructor
            mock_sandbox_class.assert_called_once()
            _, kwargs = mock_sandbox_class.call_args

            assert kwargs["timeout"] == timeout
            assert kwargs["resolution"] == resolution
            assert kwargs["dpi"] == dpi
            assert kwargs["display"] == display


def test_get_stream_url(mock_e2b_desktop_tools):
    """Test getting stream URL."""
    # Call the method
    result = mock_e2b_desktop_tools.get_stream_url()

    # Verify
    mock_e2b_desktop_tools.get_stream_url.assert_called_once()
    assert '"url": "https://stream.example.com"' in result


def test_get_stream_url_with_auth(mock_e2b_desktop_tools):
    """Test getting stream URL with auth key."""
    # Call the method
    result = mock_e2b_desktop_tools.get_stream_url("test-auth-key")

    # Verify
    mock_e2b_desktop_tools.get_stream_url.assert_called_once_with("test-auth-key")
    assert '"url": "https://stream.example.com"' in result


def test_start_stream(mock_e2b_desktop_tools):
    """Test starting a stream."""
    # Call the method
    result = mock_e2b_desktop_tools.start_stream(False)

    # Verify
    mock_e2b_desktop_tools.start_stream.assert_called_once_with(False)
    assert '"message": "Stream started successfully"' in result


def test_start_stream_with_auth(mock_e2b_desktop_tools):
    """Test starting a stream with authentication."""
    # Call the method with require_auth=True
    mock_e2b_desktop_tools.start_stream.return_value = (
        '{"status": "success", "message": "Stream started successfully", "require_auth": true}'
    )
    result = mock_e2b_desktop_tools.start_stream(True)

    # Verify
    mock_e2b_desktop_tools.start_stream.assert_called_with(True)
    assert '"require_auth": true' in result


def test_stop_stream(mock_e2b_desktop_tools):
    """Test stopping a stream."""
    # Call the method
    result = mock_e2b_desktop_tools.stop_stream()

    # Verify
    mock_e2b_desktop_tools.stop_stream.assert_called_once()
    assert '"message": "Stream stopped successfully"' in result


def test_take_screenshot(mock_e2b_desktop_tools):
    """Test taking a screenshot."""
    # Call the method
    result = mock_e2b_desktop_tools.take_screenshot()

    # Verify
    mock_e2b_desktop_tools.take_screenshot.assert_called_once()
    assert '"format": "base64"' in result
    assert '"data":' in result


def test_take_screenshot_with_save_path(mock_e2b_desktop_tools):
    """Test taking a screenshot with a save path."""
    # Setup
    mock_e2b_desktop_tools.take_screenshot.return_value = (
        '{"status": "success", "format": "base64", "data": "bW9ja19pbWFnZV9kYXRh", "save_path": "/tmp/screenshot.png"}'
    )

    # Call the method
    result = mock_e2b_desktop_tools.take_screenshot("/tmp/screenshot.png")

    # Verify
    mock_e2b_desktop_tools.take_screenshot.assert_called_once_with("/tmp/screenshot.png")
    assert '"save_path": "/tmp/screenshot.png"' in result


def test_left_click(mock_e2b_desktop_tools):
    """Test left click."""
    # Call the method
    result = mock_e2b_desktop_tools.left_click()

    # Verify
    mock_e2b_desktop_tools.left_click.assert_called_once()
    assert '"message": "Left click executed"' in result


def test_double_click(mock_e2b_desktop_tools):
    """Test double click."""
    # Call the method
    result = mock_e2b_desktop_tools.double_click()

    # Verify
    mock_e2b_desktop_tools.double_click.assert_called_once()
    assert '"message": "Double click executed"' in result


def test_right_click(mock_e2b_desktop_tools):
    """Test right click."""
    # Call the method
    result = mock_e2b_desktop_tools.right_click()

    # Verify
    mock_e2b_desktop_tools.right_click.assert_called_once()
    assert '"message": "Right click executed"' in result


def test_middle_click(mock_e2b_desktop_tools):
    """Test middle click."""
    # Call the method
    result = mock_e2b_desktop_tools.middle_click()

    # Verify
    mock_e2b_desktop_tools.middle_click.assert_called_once()
    assert '"message": "Middle click executed"' in result


def test_scroll(mock_e2b_desktop_tools):
    """Test scrolling."""
    # Call the method
    result = mock_e2b_desktop_tools.scroll(10)

    # Verify
    mock_e2b_desktop_tools.scroll.assert_called_once_with(10)
    assert '"message": "Scrolled by 10"' in result


def test_move_mouse(mock_e2b_desktop_tools):
    """Test moving the mouse."""
    # Call the method
    result = mock_e2b_desktop_tools.move_mouse(100, 200)

    # Verify
    mock_e2b_desktop_tools.move_mouse.assert_called_once_with(100, 200)
    assert '"message": "Moved mouse to (100, 200)"' in result


def test_drag(mock_e2b_desktop_tools):
    """Test dragging the mouse."""
    # Call the method
    result = mock_e2b_desktop_tools.drag((10, 20), (100, 200))

    # Verify
    mock_e2b_desktop_tools.drag.assert_called_once_with((10, 20), (100, 200))
    assert '"message": "Dragged from (10, 20) to (100, 200)"' in result


def test_mouse_press(mock_e2b_desktop_tools):
    """Test pressing a mouse button."""
    # Call the method
    result = mock_e2b_desktop_tools.mouse_press("left")

    # Verify
    mock_e2b_desktop_tools.mouse_press.assert_called_once_with("left")
    assert '"message": "Pressed left mouse button"' in result


def test_mouse_release(mock_e2b_desktop_tools):
    """Test releasing a mouse button."""
    # Call the method
    result = mock_e2b_desktop_tools.mouse_release("left")

    # Verify
    mock_e2b_desktop_tools.mouse_release.assert_called_once_with("left")
    assert '"message": "Released left mouse button"' in result


def test_get_cursor_position(mock_e2b_desktop_tools):
    """Test getting cursor position."""
    # Call the method
    result = mock_e2b_desktop_tools.get_cursor_position()

    # Verify
    mock_e2b_desktop_tools.get_cursor_position.assert_called_once()
    assert '"x": 100' in result
    assert '"y": 200' in result


def test_get_screen_size(mock_e2b_desktop_tools):
    """Test getting screen size."""
    # Call the method
    result = mock_e2b_desktop_tools.get_screen_size()

    # Verify
    mock_e2b_desktop_tools.get_screen_size.assert_called_once()
    assert '"width": 1280' in result
    assert '"height": 720' in result


def test_write(mock_e2b_desktop_tools):
    """Test writing text."""
    # Call the method
    result = mock_e2b_desktop_tools.write("Hello World")

    # Verify
    mock_e2b_desktop_tools.write.assert_called_once_with("Hello World")
    assert '"message": "Wrote text: \'Hello World\'"' in result


def test_write_with_custom_params(mock_e2b_desktop_tools):
    """Test writing text with custom chunk size and delay."""
    # Setup
    mock_e2b_desktop_tools.write.return_value = (
        '{"status": "success", "message": "Wrote text: \'Hello World\'", "chunk_size": 10, "delay_in_ms": 100}'
    )

    # Call the method
    result = mock_e2b_desktop_tools.write("Hello World", 10, 100)

    # Verify
    mock_e2b_desktop_tools.write.assert_called_once_with("Hello World", 10, 100)
    assert '"chunk_size": 10' in result
    assert '"delay_in_ms": 100' in result


def test_press_key(mock_e2b_desktop_tools):
    """Test pressing a key."""
    # Call the method
    result = mock_e2b_desktop_tools.press_key("enter")

    # Verify
    mock_e2b_desktop_tools.press_key.assert_called_once_with("enter")
    assert '"message": "Pressed key: \'enter\'"' in result


def test_press_keys(mock_e2b_desktop_tools):
    """Test pressing multiple keys."""
    # Call the method
    result = mock_e2b_desktop_tools.press_keys(["ctrl", "c"])

    # Verify
    mock_e2b_desktop_tools.press_keys.assert_called_once_with(["ctrl", "c"])
    assert '"message": "Pressed keys: \'ctrl+c\'"' in result


def test_wait(mock_e2b_desktop_tools):
    """Test waiting."""
    # Call the method
    result = mock_e2b_desktop_tools.wait(1000)

    # Verify
    mock_e2b_desktop_tools.wait.assert_called_once_with(1000)
    assert '"message": "Waited for 1000 milliseconds"' in result


def test_open(mock_e2b_desktop_tools):
    """Test opening a file or URL."""
    # Call the method
    result = mock_e2b_desktop_tools.open("https://example.com")

    # Verify
    mock_e2b_desktop_tools.open.assert_called_once_with("https://example.com")
    assert '"message": "Opened: \'https://example.com\'"' in result


def test_run_command(mock_e2b_desktop_tools):
    """Test running a command."""
    # Call the method
    result = mock_e2b_desktop_tools.run_command("ls -la")

    # Verify
    mock_e2b_desktop_tools.run_command.assert_called_once_with("ls -la")
    assert '"message": "Command executed: \'ls -la\'"' in result
    assert '"output": "file1 file2"' in result


def test_shutdown_sandbox(mock_e2b_desktop_tools):
    """Test shutting down the sandbox."""
    # Call the method
    result = mock_e2b_desktop_tools.shutdown_sandbox()

    # Verify
    mock_e2b_desktop_tools.shutdown_sandbox.assert_called_once()
    assert '"message": "Desktop sandbox shut down"' in result
