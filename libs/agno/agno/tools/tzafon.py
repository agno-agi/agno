import asyncio
import json
from os import getenv
from typing import Any, List, Optional
from uuid import uuid4

from agno.media import Image
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_debug, logger

try:
    from tzafon import Lightcone
except ImportError:
    raise ImportError("`tzafon` not installed. Please install using `pip install tzafon`")


class TzafonTools(Toolkit):
    """Drive a Lightcone (Tzafon) cloud computer with native SDK actions.

    Uses the `tzafon` SDK directly (navigate, click, type, scroll, wait, screenshot) -
    no Playwright or CDP required. See https://docs.lightcone.ai.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        kind: str = "browser",
        enable_navigate: bool = True,
        enable_screenshot: bool = True,
        enable_click: bool = True,
        enable_type: bool = True,
        enable_scroll: bool = True,
        enable_wait: bool = True,
        enable_close: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize TzafonTools.

        Args:
            api_key (str, optional): Tzafon API key. If not provided, it is read from the
                `TZAFON_API_KEY` environment variable. Get one from the Lightcone developer
                dashboard at https://lightcone.ai/developer.
            kind (str): The kind of cloud computer to create, passed straight to Lightcone.
                Use "browser" (Chromium in the foreground) or "desktop" (full Lightcone OS
                desktop). Defaults to "browser".
            enable_navigate (bool): Enable the navigate_to tool. Defaults to True.
            enable_screenshot (bool): Enable the screenshot tool. Defaults to True.
            enable_click (bool): Enable the click tool. Defaults to True.
            enable_type (bool): Enable the type_text tool. Defaults to True.
            enable_scroll (bool): Enable the scroll tool. Defaults to True.
            enable_wait (bool): Enable the wait tool. Defaults to True.
            enable_close (bool): Enable the close_session tool. Defaults to True.
            all (bool): Enable all tools. Defaults to False.
        """
        self.kind = kind

        self.api_key = api_key or getenv("TZAFON_API_KEY")
        if not self.api_key:
            raise ValueError("TZAFON_API_KEY is required. Get your API key from https://lightcone.ai/developer")

        self.app = Lightcone(api_key=self.api_key)

        # A single cloud computer is created lazily and reused across tool calls.
        self._computer = None

        tools: List[Any] = []
        async_tools: List[tuple] = []

        if all or enable_navigate:
            tools.append(self.navigate_to)
            async_tools.append((self.anavigate_to, "navigate_to"))
        if all or enable_screenshot:
            tools.append(self.screenshot)
            async_tools.append((self.ascreenshot, "screenshot"))
        if all or enable_click:
            tools.append(self.click)
            async_tools.append((self.aclick, "click"))
        if all or enable_type:
            tools.append(self.type_text)
            async_tools.append((self.atype_text, "type_text"))
        if all or enable_scroll:
            tools.append(self.scroll)
            async_tools.append((self.ascroll, "scroll"))
        if all or enable_wait:
            tools.append(self.wait)
            async_tools.append((self.await_, "wait"))
        if all or enable_close:
            tools.append(self.close_session)
            async_tools.append((self.aclose_session, "close_session"))

        super().__init__(name="tzafon_tools", tools=tools, async_tools=async_tools, **kwargs)
        log_debug(f"Initialized TzafonTools with tools: {tools}")

    def _ensure_computer(self):
        """Create the cloud computer on first use, then reuse it."""
        if self._computer is None:
            try:
                self._computer = self.app.computer.create(kind=self.kind)  # type: ignore
                log_debug(f"Created new Tzafon {self.kind} computer")
            except Exception:
                logger.exception("Failed to create Tzafon computer")
                raise
        return self._computer

    def _capture(self) -> str:
        """Take a screenshot and return its hosted URL (native SDK)."""
        computer = self._ensure_computer()
        result = computer.screenshot()
        return computer.get_screenshot_url(result)

    def _build_screenshot_result(self, url: str) -> ToolResult:
        image = Image(id=str(uuid4()), url=url, mime_type="image/png")
        return ToolResult(
            content=f"Screenshot captured and attached. Return this hosted URL to the user: {url}",
            images=[image],
        )

    # ------------------------------------------------------------------
    # Sync tools
    # ------------------------------------------------------------------
    def navigate_to(self, url: str) -> str:
        """Navigates the cloud computer to a URL.

        Args:
            url (str): The URL to navigate to.

        Returns:
            JSON string with navigation status.
        """
        try:
            self._ensure_computer().navigate(url)
            return json.dumps({"status": "complete", "url": url})
        except Exception as e:
            logger.error(f"Failed to navigate to {url}: {str(e)}")
            raise e

    def screenshot(self) -> ToolResult:
        """Takes a screenshot of the current screen.

        Returns:
            A ToolResult with the screenshot attached as an image and its hosted URL.
        """
        try:
            url = self._capture()
            return self._build_screenshot_result(url)
        except Exception as e:
            logger.error(f"Failed to take screenshot: {str(e)}")
            return ToolResult(content=f"Error taking screenshot: {str(e)}")

    def click(self, x: int, y: int) -> str:
        """Clicks at the given coordinates.

        Args:
            x (int): The x coordinate to click.
            y (int): The y coordinate to click.

        Returns:
            JSON string with click status.
        """
        try:
            self._ensure_computer().click(x, y)
            return json.dumps({"status": "complete", "action": "click", "x": x, "y": y})
        except Exception as e:
            logger.error(f"Failed to click at ({x}, {y}): {str(e)}")
            raise e

    def type_text(self, text: str) -> str:
        """Types text into the focused element.

        Args:
            text (str): The text to type.

        Returns:
            JSON string with type status.
        """
        try:
            self._ensure_computer().type(text)
            return json.dumps({"status": "complete", "action": "type"})
        except Exception as e:
            logger.error(f"Failed to type text: {str(e)}")
            raise e

    def scroll(self, dx: int, dy: int, x: int = 0, y: int = 0) -> str:
        """Scrolls the screen.

        Args:
            dx (int): Horizontal scroll delta.
            dy (int): Vertical scroll delta.
            x (int): The x coordinate to scroll from. Defaults to 0.
            y (int): The y coordinate to scroll from. Defaults to 0.

        Returns:
            JSON string with scroll status.
        """
        try:
            self._ensure_computer().scroll(dx, dy, x, y)
            return json.dumps({"status": "complete", "action": "scroll", "dx": dx, "dy": dy})
        except Exception as e:
            logger.error(f"Failed to scroll: {str(e)}")
            raise e

    def wait(self, seconds: float) -> str:
        """Waits for the given number of seconds.

        Args:
            seconds (float): How long to wait.

        Returns:
            JSON string with wait status.
        """
        try:
            self._ensure_computer().wait(seconds)
            return json.dumps({"status": "complete", "action": "wait", "seconds": seconds})
        except Exception as e:
            logger.error(f"Failed to wait: {str(e)}")
            raise e

    def close_session(self) -> str:
        """Terminates the cloud computer and releases resources.

        Returns:
            JSON string with closure status.
        """
        if self._computer is None:
            return json.dumps({"status": "closed", "message": "No active Tzafon computer."})
        try:
            self._computer.terminate()
        except Exception as e:
            logger.warning(f"Failed to terminate Tzafon computer: {str(e)}")
        finally:
            self._computer = None
        return json.dumps({"status": "closed", "message": "Tzafon computer terminated."})

    # ------------------------------------------------------------------
    # Async tools (the tzafon SDK is synchronous; wrap calls in a thread)
    # ------------------------------------------------------------------
    async def anavigate_to(self, url: str) -> str:
        """Navigates the cloud computer to a URL asynchronously.

        Args:
            url (str): The URL to navigate to.

        Returns:
            JSON string with navigation status.
        """
        return await asyncio.to_thread(self.navigate_to, url)

    async def ascreenshot(self) -> ToolResult:
        """Takes a screenshot of the current screen asynchronously.

        Returns:
            A ToolResult with the screenshot attached as an image and its hosted URL.
        """
        try:
            url = await asyncio.to_thread(self._capture)
            return self._build_screenshot_result(url)
        except Exception as e:
            logger.error(f"Failed to take screenshot: {str(e)}")
            return ToolResult(content=f"Error taking screenshot: {str(e)}")

    async def aclick(self, x: int, y: int) -> str:
        """Clicks at the given coordinates asynchronously.

        Args:
            x (int): The x coordinate to click.
            y (int): The y coordinate to click.

        Returns:
            JSON string with click status.
        """
        return await asyncio.to_thread(self.click, x, y)

    async def atype_text(self, text: str) -> str:
        """Types text into the focused element asynchronously.

        Args:
            text (str): The text to type.

        Returns:
            JSON string with type status.
        """
        return await asyncio.to_thread(self.type_text, text)

    async def ascroll(self, dx: int, dy: int, x: int = 0, y: int = 0) -> str:
        """Scrolls the screen asynchronously.

        Args:
            dx (int): Horizontal scroll delta.
            dy (int): Vertical scroll delta.
            x (int): The x coordinate to scroll from. Defaults to 0.
            y (int): The y coordinate to scroll from. Defaults to 0.

        Returns:
            JSON string with scroll status.
        """
        return await asyncio.to_thread(self.scroll, dx, dy, x, y)

    async def await_(self, seconds: float) -> str:
        """Waits for the given number of seconds asynchronously.

        Args:
            seconds (float): How long to wait.

        Returns:
            JSON string with wait status.
        """
        return await asyncio.to_thread(self.wait, seconds)

    async def aclose_session(self) -> str:
        """Terminates the cloud computer asynchronously.

        Returns:
            JSON string with closure status.
        """
        return await asyncio.to_thread(self.close_session)
