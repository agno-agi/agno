import base64
import json
import os
import time
from os import getenv
from typing import Any, Dict, Iterator, List, Literal, Optional, Tuple, Union, overload

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    # Import the E2B Desktop SDK
    from e2b_desktop import Sandbox as DesktopSandbox
except ImportError:
    raise ImportError("`e2b_desktop` not installed. Please install using `pip install e2b-desktop`")


class E2BDesktopTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: int = 300,  # 5 minutes default timeout
        sandbox_options: Optional[Dict[str, Any]] = None,
        resolution: Optional[Tuple[int, int]] = None,
        dpi: Optional[int] = None,
        display: Optional[str] = None,
    ):
        """Initialize E2B Desktop toolkit for interacting with a virtual desktop sandbox.

        Args:
            api_key: E2B API key (defaults to E2B_API_KEY environment variable)
            timeout: Timeout in seconds for the sandbox (default: 5 minutes)
            sandbox_options: Additional options to pass to the Sandbox constructor
            resolution: Custom resolution as (width, height) tuple
            dpi: Custom DPI setting
            display: Custom display identifier (default is :0)
        """
        super().__init__(name="e2b_desktop_tools")

        self.api_key = api_key or getenv("E2B_API_KEY")
        if not self.api_key:
            raise ValueError("E2B_API_KEY not set. Please set the E2B_API_KEY environment variable.")

        # Create the sandbox once and reuse it
        self.sandbox_options = sandbox_options or {}

        kwargs = {"api_key": self.api_key}

        # Add optional parameters if provided
        if timeout:
            kwargs["timeout"] = timeout
        if resolution:
            kwargs["resolution"] = resolution
        if dpi:
            kwargs["dpi"] = dpi
        if display:
            kwargs["display"] = display

        # Add any additional options
        kwargs.update(self.sandbox_options)

        try:
            self.sandbox = DesktopSandbox(**kwargs)
            logger.info(f"Created E2B Desktop sandbox successfully")
        except Exception as e:
            logger.error(f"Error creating E2B Desktop sandbox: {e}")
            raise e

        # Register all the desktop interaction functions
        self.register(self.get_stream_url)
        self.register(self.start_stream)
        self.register(self.stop_stream)
        self.register(self.take_screenshot)
        self.register(self.left_click)
        self.register(self.double_click)
        self.register(self.right_click)
        self.register(self.middle_click)
        self.register(self.scroll)
        self.register(self.move_mouse)
        self.register(self.drag)
        self.register(self.mouse_press)
        self.register(self.mouse_release)
        self.register(self.get_cursor_position)
        self.register(self.get_screen_size)
        self.register(self.write)
        self.register(self.press_key)
        self.register(self.press_keys)
        self.register(self.wait)
        self.register(self.open)
        self.register(self.run_command)
        self.register(self.shutdown_sandbox)

    def start_stream(self, require_auth: bool = False) -> str:
        """
        Start streaming the desktop.

        Args:
            require_auth: Whether to require authentication for the stream

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.stream.start(require_auth=require_auth)
            return json.dumps(
                {"status": "success", "message": "Stream started successfully", "require_auth": require_auth}
            )
        except Exception as e:
            logger.error(f"Error starting stream: {e}")
            return json.dumps({"status": "error", "message": f"Error starting stream: {str(e)}"})

    def stop_stream(self) -> str:
        """
        Stop streaming the desktop.

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.stream.stop()
            return json.dumps({"status": "success", "message": "Stream stopped successfully"})
        except Exception as e:
            logger.error(f"Error stopping stream: {e}")
            return json.dumps({"status": "error", "message": f"Error stopping stream: {str(e)}"})

    def get_stream_url(self, auth_key: Optional[str] = None) -> str:
        """
        Get the URL for the desktop stream.

        Args:
            auth_key: Authentication key for the stream (if required)

        Returns:
            str: Stream URL or error message
        """
        try:
            if auth_key:
                url = self.sandbox.stream.get_url(auth_key=auth_key)
            else:
                url = self.sandbox.stream.get_url()

            logger.info(f"Stream URL: {url}")
            return json.dumps({"status": "success", "url": url})
        except Exception as e:
            logger.error(f"Error getting stream URL: {e}")
            return json.dumps({"status": "error", "message": f"Error getting stream URL: {str(e)}"})

    def get_stream_auth_key(self) -> str:
        """
        Get the authentication key for the stream.

        Returns:
            str: Authentication key or error message
        """
        try:
            auth_key = self.sandbox.stream.get_auth_key()
            return json.dumps({"status": "success", "auth_key": auth_key})
        except Exception as e:
            logger.error(f"Error getting stream authentication key: {e}")
            return json.dumps({"status": "error", "message": f"Error getting stream authentication key: {str(e)}"})

    def take_screenshot(self, save_path: Optional[str] = None) -> str:
        """
        Take a screenshot of the desktop sandbox.

        Args:
            save_path: Optional path to save the screenshot to

        Returns:
            str: Base64-encoded screenshot data or error message
        """
        try:
            screenshot = self.sandbox.screenshot()

            # If a save path is provided, save the screenshot there
            if save_path:
                with open(save_path, "wb") as f:
                    f.write(screenshot)

            # Always return the base64 encoded data
            screenshot_b64 = base64.b64encode(screenshot).decode("utf-8")
            return json.dumps({"status": "success", "format": "base64", "data": screenshot_b64, "save_path": save_path})

        except Exception as e:
            logger.error(f"Error taking screenshot: {e}")
            return json.dumps({"status": "error", "message": f"Error taking screenshot: {str(e)}"})

    def left_click(self) -> str:
        """
        Left click at the current mouse position.

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.left_click()
            return json.dumps({"status": "success", "message": "Left click executed"})
        except Exception as e:
            logger.error(f"Error performing left click: {e}")
            return json.dumps({"status": "error", "message": f"Error performing left click: {str(e)}"})

    def double_click(self) -> str:
        """
        Double click at the current mouse position.

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.double_click()
            return json.dumps({"status": "success", "message": "Double click executed"})
        except Exception as e:
            logger.error(f"Error performing double click: {e}")
            return json.dumps({"status": "error", "message": f"Error performing double click: {str(e)}"})

    def right_click(self) -> str:
        """
        Right click at the current mouse position.

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.right_click()
            return json.dumps({"status": "success", "message": "Right click executed"})
        except Exception as e:
            logger.error(f"Error performing right click: {e}")
            return json.dumps({"status": "error", "message": f"Error performing right click: {str(e)}"})

    def middle_click(self) -> str:
        """
        Middle click at the current mouse position.

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.middle_click()
            return json.dumps({"status": "success", "message": "Middle click executed"})
        except Exception as e:
            logger.error(f"Error performing middle click: {e}")
            return json.dumps({"status": "error", "message": f"Error performing middle click: {str(e)}"})

    def scroll(self, amount: int) -> str:
        """
        Scroll the mouse wheel by the given amount.

        Args:
            amount: Amount to scroll (positive for up, negative for down)

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.scroll(amount)
            return json.dumps({"status": "success", "message": f"Scrolled by {amount}"})
        except Exception as e:
            logger.error(f"Error scrolling: {e}")
            return json.dumps({"status": "error", "message": f"Error scrolling: {str(e)}"})

    def move_mouse(self, x: int, y: int) -> str:
        """
        Move the mouse to the specified coordinates.

        Args:
            x: X coordinate
            y: Y coordinate

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.move_mouse(x, y)
            return json.dumps({"status": "success", "message": f"Moved mouse to ({x}, {y})"})
        except Exception as e:
            logger.error(f"Error moving mouse: {e}")
            return json.dumps({"status": "error", "message": f"Error moving mouse: {str(e)}"})

    def drag(self, start: Tuple[int, int], end: Tuple[int, int]) -> str:
        """
        Drag the mouse from start position to end position.

        Args:
            start: Starting position (x, y)
            end: Ending position (x, y)

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.drag(start, end)
            return json.dumps({"status": "success", "message": f"Dragged from {start} to {end}"})
        except Exception as e:
            logger.error(f"Error dragging mouse: {e}")
            return json.dumps({"status": "error", "message": f"Error dragging mouse: {str(e)}"})

    def mouse_press(self, button: str = "left") -> str:
        """
        Press and hold a mouse button.

        Args:
            button: Mouse button to press ("left", "right", "middle")

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.mouse_press(button)
            return json.dumps({"status": "success", "message": f"Pressed {button} mouse button"})
        except Exception as e:
            logger.error(f"Error pressing mouse button: {e}")
            return json.dumps({"status": "error", "message": f"Error pressing mouse button: {str(e)}"})

    def mouse_release(self, button: str = "left") -> str:
        """
        Release a pressed mouse button.

        Args:
            button: Mouse button to release ("left", "right", "middle")

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.mouse_release(button)
            return json.dumps({"status": "success", "message": f"Released {button} mouse button"})
        except Exception as e:
            logger.error(f"Error releasing mouse button: {e}")
            return json.dumps({"status": "error", "message": f"Error releasing mouse button: {str(e)}"})

    def get_cursor_position(self) -> str:
        """
        Get the current cursor position.

        Returns:
            str: JSON with cursor position or error message
        """
        try:
            position = self.sandbox.get_cursor_position()
            return json.dumps({"status": "success", "x": position[0], "y": position[1]})
        except Exception as e:
            logger.error(f"Error getting cursor position: {e}")
            return json.dumps({"status": "error", "message": f"Error getting cursor position: {str(e)}"})

    def get_screen_size(self) -> str:
        """
        Get the screen size of the desktop sandbox.

        Returns:
            str: JSON with screen dimensions or error message
        """
        try:
            size = self.sandbox.get_screen_size()
            return json.dumps({"status": "success", "width": size[0], "height": size[1]})
        except Exception as e:
            logger.error(f"Error getting screen size: {e}")
            return json.dumps({"status": "error", "message": f"Error getting screen size: {str(e)}"})

    def write(self, text: str, chunk_size: int = 25, delay_in_ms: int = 75) -> str:
        """
        Write text at the current cursor position.

        Args:
            text: Text to write
            chunk_size: Number of characters to write at once
            delay_in_ms: Delay between chunks in milliseconds

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.write(text, chunk_size=chunk_size, delay_in_ms=delay_in_ms)
            return json.dumps(
                {
                    "status": "success",
                    "message": f"Wrote text: '{text}'",
                    "chunk_size": chunk_size,
                    "delay_in_ms": delay_in_ms,
                }
            )
        except Exception as e:
            logger.error(f"Error writing text: {e}")
            return json.dumps({"status": "error", "message": f"Error writing text: {str(e)}"})

    def press_key(self, key: str) -> str:
        """
        Press a single key.

        Args:
            key: Key to press (e.g., "enter", "space", "a", etc.)

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.press(key)
            return json.dumps({"status": "success", "message": f"Pressed key: '{key}'"})
        except Exception as e:
            logger.error(f"Error pressing key: {e}")
            return json.dumps({"status": "error", "message": f"Error pressing key: {str(e)}"})

    def press_keys(self, keys: List[str]) -> str:
        """
        Press a combination of keys simultaneously (hotkey).

        Args:
            keys: List of keys to press (e.g., ["ctrl", "c"] for Ctrl+C)

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.press(keys)
            key_desc = "+".join(keys)
            return json.dumps({"status": "success", "message": f"Pressed keys: '{key_desc}'"})
        except Exception as e:
            logger.error(f"Error pressing keys: {e}")
            return json.dumps({"status": "error", "message": f"Error pressing keys: {str(e)}"})

    def wait(self, ms: int) -> str:
        """
        Wait for the specified number of milliseconds.

        Args:
            ms: Time to wait in milliseconds

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.wait(ms)
            return json.dumps({"status": "success", "message": f"Waited for {ms} milliseconds"})
        except Exception as e:
            logger.error(f"Error waiting: {e}")
            return json.dumps({"status": "error", "message": f"Error waiting: {str(e)}"})

    def open(self, file_or_url: str) -> str:
        """
        Open a file or URL in the default application.

        Args:
            file_or_url: File path or URL to open

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.open(file_or_url)
            return json.dumps({"status": "success", "message": f"Opened: '{file_or_url}'"})
        except Exception as e:
            logger.error(f"Error opening file or URL: {e}")
            return json.dumps({"status": "error", "message": f"Error opening file or URL: {str(e)}"})

    def run_command(self, command: str) -> str:
        """
        Run a shell command in the sandbox.

        Args:
            command: Shell command to run

        Returns:
            str: Command output or error message
        """
        try:
            result = self.sandbox.commands.run(command)
            return json.dumps({"status": "success", "message": f"Command executed: '{command}'", "output": result})
        except Exception as e:
            logger.error(f"Error running command: {e}")
            return json.dumps({"status": "error", "message": f"Error running command: {str(e)}"})

    def shutdown_sandbox(self) -> str:
        """
        Shutdown the desktop sandbox.

        Returns:
            str: Success or error message
        """
        try:
            self.sandbox.kill()
            return json.dumps({"status": "success", "message": "Desktop sandbox shut down"})
        except Exception as e:
            logger.error(f"Error shutting down desktop sandbox: {e}")
            return json.dumps({"status": "error", "message": f"Error shutting down desktop sandbox: {str(e)}"})
