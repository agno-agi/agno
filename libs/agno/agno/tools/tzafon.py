import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

API_BASE_URL = "https://api.tzafon.ai"

try:
    from tzafon import Computer
except ImportError:
    raise ImportError("`tzafon` not installed. Please install using `pip install tzafon`")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    raise ImportError(
        "`playwright` not installed. Please install using `pip install playwright` and run `playwright install`"
    )


class TzafonTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_navigate_to: bool = True,
        enable_screenshot: bool = True,
        enable_get_page_content: bool = True,
        enable_terminate_session: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize TzafonTools.

        Args:
            api_key (str, optional): The Tzafon API key. If not provided, it will be retrieved from the `TZAFON_API_KEY` environment variable.
        """
        self.api_key = api_key or getenv("TZAFON_API_KEY")
        if not self.api_key:
            raise ValueError("TZAFON_API_KEY is not set. Get your API key from https://tzafon.ai/dashboard")

        self._client = Computer(api_key=self.api_key)
        self._computer = None
        self._playwright = None
        self._browser = None
        self._page = None

        tools: List[Any] = []
        if all or enable_navigate_to:
            tools.append(self.navigate_to)
        if all or enable_screenshot:
            tools.append(self.screenshot)
        if all or enable_get_page_content:
            tools.append(self.get_page_content)
        if all or enable_terminate_session:
            tools.append(self.terminate_session)

        super().__init__(name="tzafon_tools", tools=tools, **kwargs)
        log_debug(f"Initialized TzafonTools with tools: {tools}")

    def _initialize_browser(self):
        """
        Initialize a new browser session and construct the CDP URL.
        """
        self._computer = self._client.create(kind="browser")
        cdp_url = f"{API_BASE_URL}/computers/{self._computer.id}/cdp?token={self.api_key}"

        if not self._playwright:
            self._playwright = sync_playwright().start()

        self._browser = self._playwright.chromium.connect_over_cdp(cdp_url)
        context = self._browser.contexts[0] if self._browser else ""
        self._page = context.pages[0] or context.new_page()

    def _cleanup(self):
        """Clean up browser resources."""
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None
        self._page = None

    def navigate_to(self, url: str) -> str:
        """Navigates to a URL.

        Args:
            url (str): The URL to navigate to

        Returns:
            JSON string with navigation status
        """
        try:
            self._initialize_browser()
            if self._page:
                self._page.goto(url, wait_until="networkidle")
            result = {"status": "success", "title": self._page.title() if self._page else "", "url": url}
            return json.dumps(result)
        except Exception as e:
            logger.error(f"Failed to navigate to URL: {str(e)}")
            self._cleanup()
            raise e

    def screenshot(self, path: str, full_page: bool = True) -> str:
        """Takes a screenshot of the current page.

        Args:
            path (str): Where to save the screenshot
            full_page (bool): Whether to capture the full page

        Returns:
            JSON string confirming screenshot was saved
        """
        try:
            if self._page:
                self._page.screenshot(path=path, full_page=full_page)
            return json.dumps({"status": "success", "path": path})
        except Exception as e:
            logger.error(f"Failed to take screenshot: {str(e)}")
            self._cleanup()
            raise e

    def get_page_content(self) -> str:
        """Gets the HTML content of the current page.

        Returns:
            The page HTML content
        """
        try:
            return self._page.content() if self._page else ""
        except Exception as e:
            logger.error(f"Failed to get page content: {str(e)}")
            self._cleanup()
            raise e

    def terminate_session(self) -> str:
        """Closes a browser session, releasing resources.

        Returns:
            JSON string with closure status
        """
        try:
            self._cleanup()
            self._computer.terminate()

            return json.dumps(
                {
                    "status": "success",
                    "message": "Browser resources cleaned up. Session will auto-close if not already closed.",
                }
            )
        except Exception as e:
            logger.error(f"Failed to close session: {str(e)}")
            return json.dumps({"status": "error", "message": f"Cleanup completed with error: {str(e)}"})
