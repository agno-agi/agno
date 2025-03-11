import json
from os import getenv
from typing import Any, Dict, Optional
from contextlib import contextmanager

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from browserbase import Browserbase
except ImportError:
    raise ImportError(
        "`browserbase` not installed. Please install using `pip install browserbase`")

try:
    from playwright.sync_api import sync_playwright, Page, Browser
except ImportError:
    raise ImportError(
        "`playwright` not installed. Please install using `pip install playwright` and run `playwright install`")


class BrowserbaseTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        project_id: Optional[str] = None,
        api_url: Optional[str] = "https://api.browserbase.com",
    ):
        super().__init__(name="browserbase_tools")
        self.api_key: Optional[str] = api_key or getenv("BROWSERBASE_API_KEY")
        self.project_id: Optional[str] = project_id or getenv(
            "BROWSERBASE_PROJECT_ID")

        if not self.api_key:
            logger.error(
                "BROWSERBASE_API_KEY not set. Please set the BROWSERBASE_API_KEY environment variable.")
        if not self.project_id:
            logger.error(
                "BROWSERBASE_PROJECT_ID not set. Please set the BROWSERBASE_PROJECT_ID environment variable.")

        self.app: Browserbase = Browserbase(
            api_key=self.api_key)

        self._playwright = None
        self._browser = None
        self._page = None

        # Register the available functions
        self.register(self.create_session)
        self.register(self.navigate_to)
        self.register(self.screenshot)
        self.register(self.get_page_content)
        self.register(self.close_session)

    def _initialize_browser(self, connect_url: str):
        """Initialize browser connection if not already initialized."""
        if not self._playwright:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.connect_over_cdp(
                connect_url)
            context = self._browser.contexts[0]
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

    def create_session(self) -> str:
        """Creates a new browser session.

        Returns:
            JSON string containing session details including session_id and connect_url.
        """
        # Create a new session with default settings
        session = self.app.sessions.create(project_id=self.project_id)
        return json.dumps({
            "session_id": session.id,
            "connect_url": session.connect_url
        })

    def navigate_to(self, connect_url: str, url: str) -> str:
        """Navigates to a URL in the given session.

        Args:
            connect_url (str): The connection URL from the session
            url (str): The URL to navigate to

        Returns:
            JSON string with navigation result including page title
        """
        try:
            self._initialize_browser(connect_url)
            self._page.goto(url, wait_until="networkidle")
            result = {
                "status": "complete",
                "title": self._page.title(),
                "url": url
            }
            return json.dumps(result)
        except Exception as e:
            self._cleanup()
            raise e

    def screenshot(self, connect_url: str, path: str, full_page: bool = True) -> str:
        """Takes a screenshot of the current page.

        Args:
            connect_url (str): The connection URL from the session
            path (str): Where to save the screenshot
            full_page (bool): Whether to capture the full page

        Returns:
            JSON string confirming screenshot was saved
        """
        try:
            self._initialize_browser(connect_url)
            self._page.screenshot(path=path, full_page=full_page)
            return json.dumps({
                "status": "success",
                "path": path
            })
        except Exception as e:
            self._cleanup()
            raise e

    def get_page_content(self, connect_url: str) -> str:
        """Gets the HTML content of the current page.

        Args:
            connect_url (str): The connection URL from the session

        Returns:
            The page HTML content
        """
        try:
            self._initialize_browser(connect_url)
            return self._page.content()
        except Exception as e:
            self._cleanup()
            raise e

    def close_session(self, session_id: str) -> str:
        """Closes a browser session.

        Args:
            session_id (str): The session ID to close

        Returns:
            JSON string with closure status
        """
        try:
            # First cleanup our local browser resources
            self._cleanup()

            try:
                # Try to delete the session, but don't worry if it fails
                self.app.sessions.delete(session_id)
            except Exception as e:
                logger.debug(
                    f"Session {session_id} may have already been closed: {str(e)}")

            return json.dumps({
                "status": "closed",
                "message": "Browser resources cleaned up. Session will auto-close if not already closed."
            })
        except Exception as e:
            return json.dumps({
                "status": "warning",
                "message": f"Cleanup completed with warning: {str(e)}"
            })
