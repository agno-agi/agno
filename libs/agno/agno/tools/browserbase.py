import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from browserbase import Browserbase
except ImportError:
    raise ImportError("`browserbase` not installed. Please install using `pip install browserbase`")


class BrowserbaseTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        project_id: Optional[str] = None,
        base_url: Optional[str] = None,
        enable_navigate_to: bool = True,
        enable_screenshot: bool = True,
        enable_get_page_content: bool = True,
        enable_close_session: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize BrowserbaseTools.

        Args:
            api_key (str, optional): Browserbase API key.
            project_id (str, optional): Browserbase project ID.
            base_url (str, optional): Custom Browserbase API endpoint URL (NOT the target website URL).
                Only use this if you're using a self-hosted Browserbase instance or need to connect to a different region.
            enable_navigate_to (bool): Enable the navigate_to tool. Defaults to True.
            enable_screenshot (bool): Enable the screenshot tool. Defaults to True.
            enable_get_page_content (bool): Enable the get_page_content tool. Defaults to True.
            enable_close_session (bool): Enable the close_session tool. Defaults to True.
            all (bool): Enable all tools. Defaults to False.
        """
        self.api_key = api_key or getenv("BROWSERBASE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "BROWSERBASE_API_KEY is required. Please set the BROWSERBASE_API_KEY environment variable."
            )

        self.project_id = project_id or getenv("BROWSERBASE_PROJECT_ID")
        if not self.project_id:
            raise ValueError(
                "BROWSERBASE_PROJECT_ID is required. Please set the BROWSERBASE_PROJECT_ID environment variable."
            )

        self.base_url = base_url or getenv("BROWSERBASE_BASE_URL")

        # Initialize the Browserbase client with optional base_url
        if self.base_url:
            self.app = Browserbase(api_key=self.api_key, base_url=self.base_url)
            log_debug(f"Using custom Browserbase API endpoint: {self.base_url}")
        else:
            self.app = Browserbase(api_key=self.api_key)

        # Sync playwright state
        self._playwright = None
        self._browser = None
        self._page = None

        # Async playwright state
        self._async_playwright = None
        self._async_browser = None
        self._async_page = None

        # Shared session state
        self._session = None
        self._connect_url = None

        # Build tools lists
        # sync tools: used by agent.run() and agent.print_response()
        # async tools: used by agent.arun() and agent.aprint_response()
        tools: List[Any] = []
        async_tools: List[tuple] = []

        if all or enable_navigate_to:
            tools.append(self.navigate_to)
            async_tools.append((self.anavigate_to, "navigate_to"))
        if all or enable_screenshot:
            tools.append(self.screenshot)
            async_tools.append((self.ascreenshot, "screenshot"))
        if all or enable_get_page_content:
            tools.append(self.get_page_content)
            async_tools.append((self.aget_page_content, "get_page_content"))
        if all or enable_close_session:
            tools.append(self.close_session)
            async_tools.append((self.aclose_session, "close_session"))

        super().__init__(name="browserbase_tools", tools=tools, async_tools=async_tools, **kwargs)

    def _ensure_session(self):
        """Ensures a session exists, creating one if needed."""
        if not self._session:
            try:
                self._session = self.app.sessions.create(project_id=self.project_id)  # type: ignore
                self._connect_url = self._session.connect_url if self._session else ""  # type: ignore
                if self._session:
                    log_debug(f"Created new session with ID: {self._session.id}")
            except Exception as e:
                logger.error(f"Failed to create session: {str(e)}")
                raise

    def _initialize_browser(self, connect_url: Optional[str] = None):
        """
        Initialize sync browser connection if not already initialized.
        Use provided connect_url or ensure we have a session with a connect_url
        """
        try:
            from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError(
                "`playwright` not installed. Please install using `pip install playwright` and run `playwright install`"
            )

        if connect_url:
            self._connect_url = connect_url if connect_url else ""  # type: ignore
        elif not self._connect_url:
            self._ensure_session()

        if not self._playwright:
            self._playwright = sync_playwright().start()  # type: ignore
            if self._playwright:
                self._browser = self._playwright.chromium.connect_over_cdp(self._connect_url)
            context = self._browser.contexts[0] if self._browser else ""
            self._page = context.pages[0] or context.new_page()  # type: ignore

    def _cleanup(self):
        """Clean up sync browser resources."""
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
        return {
            "session_id": self._session.id if self._session else "",
            "connect_url": self._session.connect_url if self._session else "",
        }

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
            if self._page:
                self._page.goto(url, wait_until="networkidle")
            result = {"status": "complete", "title": self._page.title() if self._page else "", "url": url}
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
            if self._page:
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
            return self._page.content() if self._page else ""
        except Exception as e:
            self._cleanup()
            raise e

    def close_session(self) -> str:
        """Closes a browser session.

        Returns:
            JSON string with closure status
        """
        try:
            # First cleanup our local browser resources
            self._cleanup()

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

    async def _ainitialize_browser(self, connect_url: Optional[str] = None):
        """
        Initialize async browser connection if not already initialized.
        Use provided connect_url or ensure we have a session with a connect_url
        """
        try:
            from playwright.async_api import async_playwright  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError(
                "`playwright` not installed. Please install using `pip install playwright` and run `playwright install`"
            )

        if connect_url:
            self._connect_url = connect_url if connect_url else ""  # type: ignore
        elif not self._connect_url:
            self._ensure_session()

        if not self._async_playwright:
            self._async_playwright = await async_playwright().start()  # type: ignore
            if self._async_playwright:
                self._async_browser = await self._async_playwright.chromium.connect_over_cdp(self._connect_url)
            context = self._async_browser.contexts[0] if self._async_browser else None
            if context:
                self._async_page = context.pages[0] if context.pages else await context.new_page()

    async def _acleanup(self):
        """Clean up async browser resources."""
        if self._async_browser:
            await self._async_browser.close()
            self._async_browser = None
        if self._async_playwright:
            await self._async_playwright.stop()
            self._async_playwright = None
        self._async_page = None

    async def anavigate_to(self, url: str, connect_url: Optional[str] = None) -> str:
        """Navigates to a URL asynchronously.

        Args:
            url (str): The URL to navigate to
            connect_url (str, optional): The connection URL from an existing session

        Returns:
            JSON string with navigation status
        """
        try:
            await self._ainitialize_browser(connect_url)
            if self._async_page:
                await self._async_page.goto(url, wait_until="networkidle")
            title = await self._async_page.title() if self._async_page else ""
            result = {"status": "complete", "title": title, "url": url}
            return json.dumps(result)
        except Exception as e:
            await self._acleanup()
            raise e

    async def ascreenshot(self, path: str, full_page: bool = True, connect_url: Optional[str] = None) -> str:
        """Takes a screenshot of the current page asynchronously.

        Args:
            path (str): Where to save the screenshot
            full_page (bool): Whether to capture the full page
            connect_url (str, optional): The connection URL from an existing session

        Returns:
            JSON string confirming screenshot was saved
        """
        try:
            await self._ainitialize_browser(connect_url)
            if self._async_page:
                await self._async_page.screenshot(path=path, full_page=full_page)
            return json.dumps({"status": "success", "path": path})
        except Exception as e:
            await self._acleanup()
            raise e

    async def aget_page_content(self, connect_url: Optional[str] = None) -> str:
        """Gets the HTML content of the current page asynchronously.

        Args:
            connect_url (str, optional): The connection URL from an existing session

        Returns:
            The page HTML content
        """
        try:
            await self._ainitialize_browser(connect_url)
            return await self._async_page.content() if self._async_page else ""
        except Exception as e:
            await self._acleanup()
            raise e

    async def aclose_session(self) -> str:
        """Closes a browser session asynchronously.

        Returns:
            JSON string with closure status
        """
        try:
            # First cleanup our local browser resources
            await self._acleanup()

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
