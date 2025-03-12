import json
from os import getenv
from typing import Any, Dict, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from browserbase import Browserbase
except ImportError:
    raise ImportError("`browserbase` not installed. Please install using `pip install browserbase`")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    raise ImportError(
        "`playwright` not installed. Please install using `pip install playwright` and run `playwright install`"
    )


class BrowserbaseTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        project_id: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        """Initialize BrowserbaseTools.

        Args:
            base_url (str, optional): Custom Browserbase API endpoint URL (NOT the target website URL).
                                     Only use this if you're using a self-hosted Browserbase instance
                                     or need to connect to a different region.
        """
        super().__init__(name="browserbase_tools")

        self.api_key = api_key or getenv("BROWSERBASE_API_KEY")
        if not self.api_key:
            raise ValueError(
                f"{self.API_KEY_ENV_VAR} is required. Please set the {self.API_KEY_ENV_VAR} environment variable."
            )

        self.project_id = project_id or getenv("BROWSERBASE_PROJECT_ID")
        if not self.project_id:
            raise ValueError(
                f"{self.PROJECT_ID_ENV_VAR} is required. Please set the {self.PROJECT_ID_ENV_VAR} environment variable."
            )

        self.base_url = base_url or getenv("BROWSERBASE_BASE_URL")

        # Initialize the Browserbase client with optional base_url
        if self.base_url:
            self.app = Browserbase(api_key=self.api_key, base_url=self.base_url)
            logger.debug(f"Using custom Browserbase API endpoint: {self.base_url}")
        else:
            self.app = Browserbase(api_key=self.api_key)

        self._playwright = None
        self._browser = None
        self._page = None
        self._session = None
        self._connect_url = None

        self.register(self.navigate_to)
        self.register(self.screenshot)
        self.register(self.get_page_content)
        self.register(self.close_session)

    def _ensure_session(self):
        """Ensures a session exists, creating one if needed."""
        if not self._session:
            try:
                self._session = self.app.sessions.create(project_id=self.project_id)
                self._connect_url = self._session.connect_url
                logger.debug(f"Created new session with ID: {self._session.id}")
            except Exception as e:
                logger.error(f"Failed to create session: {str(e)}")
                raise

    def _initialize_browser(self, connect_url: Optional[str] = None):
        """
        Initialize browser connection if not already initialized.
        Use provided connect_url or ensure we have a session with a connect_url
        """
        if connect_url:
            self._connect_url = connect_url
        elif not self._connect_url:
            self._ensure_session()

        if not self._playwright:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.connect_over_cdp(self._connect_url)
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

    def _create_session(self) -> Dict[str, str]:
        """Creates a new browser session.

        Returns:
            Dictionary containing session details including session_id and connect_url.
        """
        self._ensure_session()
        return {"session_id": self._session.id, "connect_url": self._session.connect_url}

    def navigate_to(self, url: str, connect_url: Optional[str] = None) -> str:
        """Navigates to a URL.

        Args:
            url (str): The URL to navigate to
            connect_url (str, optional): The connection URL from an existing session

        Returns:
            JSON string with navigation status
        """
        try:
            self._initialize_browser(connect_url)
            self._page.goto(url, wait_until="networkidle")
            result = {"status": "complete", "title": self._page.title(), "url": url}
            return json.dumps(result)
        except Exception as e:
            self._cleanup()
            raise e

    def screenshot(self, path: str, full_page: bool = True, connect_url: Optional[str] = None) -> str:
        """Takes a screenshot of the current page.

        Args:
            path (str): Where to save the screenshot
            full_page (bool): Whether to capture the full page
            connect_url (str, optional): The connection URL from an existing session

        Returns:
            JSON string confirming screenshot was saved
        """
        try:
            self._initialize_browser(connect_url)
            self._page.screenshot(path=path, full_page=full_page)
            return json.dumps({"status": "success", "path": path})
        except Exception as e:
            self._cleanup()
            raise e

    def get_page_content(self, connect_url: Optional[str] = None) -> str:
        """Gets the HTML content of the current page.

        Args:
            connect_url (str, optional): The connection URL from an existing session

        Returns:
            The page HTML content
        """
        try:
            self._initialize_browser(connect_url)
            return self._page.content()
        except Exception as e:
            self._cleanup()
            raise e

    def close_session(self, session_id: Optional[str] = None) -> str:
        """Closes a browser session.
        Args:
            session_id (str, optional): The session ID to close. If not provided, will use the current session.
        Returns:
            JSON string with closure status
        """
        try:
            # First cleanup our local browser resources
            self._cleanup()

            # Use provided session_id or fall back to the current session
            session_id_to_close = session_id or (self._session.id if self._session else None)

            if session_id_to_close:
                try:
                    self.app.sessions.delete(session_id_to_close)
                    logger.debug(f"Closed session: {session_id_to_close}")
                except Exception as e:
                    logger.debug(f"Session {session_id_to_close} may have already been closed: {str(e)}")
            else:
                logger.warning("No session ID provided or available to close")

            # Reset session state
            self._session = None
            self._connect_url = None

            return json.dumps(
                {
                    "status": "closed",
                    "message": "Browser resources cleaned up. Session will auto-close if not already closed.",
                }
            )
        except Exception as e:
            return json.dumps({"status": "warning", "message": f"Cleanup completed with warning: {str(e)}"})
