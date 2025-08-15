import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

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
        **kwargs,
    ):
        """Initialize BrowserbaseTools.

        Args:
            api_key (str, optional): Browserbase API key.
            project_id (str, optional): Browserbase project ID.
            base_url (str, optional): Custom Browserbase API endpoint URL (NOT the target website URL). Only use this if you're using a self-hosted Browserbase instance or need to connect to a different region.
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

        self._playwright = None
        self._browser = None
        self._page = None
        self._session = None
        self._connect_url = None

        tools: List[Any] = []
        tools.append(self.navigate_to)
        tools.append(self.screenshot)
        tools.append(self.get_page_content)
        tools.append(self.close_session)
        tools.append(self.get_current_url)
        tools.append(self.go_back)
        tools.append(self.go_forward)
        tools.append(self.reload_page)
        tools.append(self.click_element)
        tools.append(self.fill_input)
        tools.append(self.wait_for_element)
        tools.append(self.get_page_title)
        tools.append(self.scroll_page)
        tools.append(self.extract_text)

        super().__init__(name="browserbase_tools", tools=tools, **kwargs)

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
        Initialize browser connection if not already initialized.
        Use provided connect_url or ensure we have a session with a connect_url
        """
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
        return {
            "session_id": self._session.id if self._session else "",
            "connect_url": self._session.connect_url if self._session else "",
        }

    def navigate_to(self, url: str, connect_url: Optional[str] = None, timeout: int = 600000) -> str:
        """Navigates to a URL.

        Args:
            url (str): The URL to navigate to
            connect_url (str, optional): The connection URL from an existing session
            timeout (int): Timeout in milliseconds (default: 600000)

        Returns:
            JSON string with navigation status
        """
        try:
            self._initialize_browser(connect_url)
            if self._page:
                self._page.goto(url, wait_until="networkidle", timeout=timeout)
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

    def get_current_url(self, connect_url: Optional[str] = None) -> str:
        """Gets the current URL of the page.

        Args:
            connect_url (str, optional): The connection URL from an existing session

        Returns:
            JSON string with the current URL
        """
        try:
            self._initialize_browser(connect_url)
            current_url = self._page.url() if self._page else ""
            return json.dumps({"status": "success", "url": current_url})
        except Exception as e:
            self._cleanup()
            raise e

    def go_back(self, connect_url: Optional[str] = None) -> str:
        """Navigates back in browser history.

        Args:
            connect_url (str, optional): The connection URL from an existing session

        Returns:
            JSON string with navigation status
        """
        try:
            self._initialize_browser(connect_url)
            if self._page:
                self._page.go_back(wait_until="networkidle")
            new_url = self._page.url() if self._page else ""
            return json.dumps({"status": "success", "action": "go_back", "url": new_url})
        except Exception as e:
            self._cleanup()
            raise e

    def go_forward(self, connect_url: Optional[str] = None) -> str:
        """Navigates forward in browser history.

        Args:
            connect_url (str, optional): The connection URL from an existing session

        Returns:
            JSON string with navigation status
        """
        try:
            self._initialize_browser(connect_url)
            if self._page:
                self._page.go_forward(wait_until="networkidle")
            new_url = self._page.url() if self._page else ""
            return json.dumps({"status": "success", "action": "go_forward", "url": new_url})
        except Exception as e:
            self._cleanup()
            raise e

    def reload_page(self, connect_url: Optional[str] = None) -> str:
        """Reloads/refreshes the current page.

        Args:
            connect_url (str, optional): The connection URL from an existing session

        Returns:
            JSON string with reload status
        """
        try:
            self._initialize_browser(connect_url)
            if self._page:
                self._page.reload(wait_until="networkidle")
            current_url = self._page.url() if self._page else ""
            return json.dumps({"status": "success", "action": "reload", "url": current_url})
        except Exception as e:
            self._cleanup()
            raise e

    def click_element(self, selector: str, connect_url: Optional[str] = None, timeout: int = 600000) -> str:
        """Clicks on an element specified by CSS selector.

        Args:
            selector (str): CSS selector for the element to click
            connect_url (str, optional): The connection URL from an existing session
            timeout (int): Timeout in milliseconds (default: 600000)

        Returns:
            JSON string with click status
        """
        try:
            self._initialize_browser(connect_url)
            if self._page:
                self._page.click(selector, timeout=timeout)
            return json.dumps({"status": "success", "action": "click", "selector": selector})
        except Exception as e:
            self._cleanup()
            raise e

    def fill_input(self, selector: str, text: str, connect_url: Optional[str] = None, timeout: int = 600000) -> str:
        """Fills an input field with the specified text.

        Args:
            selector (str): CSS selector for the input element
            text (str): Text to fill in the input
            connect_url (str, optional): The connection URL from an existing session
            timeout (int): Timeout in milliseconds (default: 600000)

        Returns:
            JSON string with fill status
        """
        try:
            self._initialize_browser(connect_url)
            if self._page:
                self._page.fill(selector, text, timeout=timeout)
            return json.dumps({"status": "success", "action": "fill", "selector": selector, "text": text})
        except Exception as e:
            self._cleanup()
            raise e

    def wait_for_element(self, selector: str, timeout: int = 600000, connect_url: Optional[str] = None) -> str:
        """Waits for an element to appear on the page.

        Args:
            selector (str): CSS selector for the element to wait for
            timeout (int): Timeout in milliseconds (default: 600000)
            connect_url (str, optional): The connection URL from an existing session

        Returns:
            JSON string with wait status
        """
        try:
            self._initialize_browser(connect_url)
            if self._page:
                self._page.wait_for_selector(selector, timeout=timeout)
            return json.dumps({"status": "success", "action": "wait_for_element", "selector": selector})
        except Exception as e:
            self._cleanup()
            raise e

    def get_page_title(self, connect_url: Optional[str] = None) -> str:
        """Gets the title of the current page.

        Args:
            connect_url (str, optional): The connection URL from an existing session

        Returns:
            JSON string with the page title
        """
        try:
            self._initialize_browser(connect_url)
            title = self._page.title() if self._page else ""
            return json.dumps({"status": "success", "title": title})
        except Exception as e:
            self._cleanup()
            raise e

    def scroll_page(self, direction: str = "down", pixels: int = 500, connect_url: Optional[str] = None) -> str:
        """Scrolls the page in the specified direction.

        Args:
            direction (str): Direction to scroll ("up", "down", "left", "right")
            pixels (int): Number of pixels to scroll (default: 500)
            connect_url (str, optional): The connection URL from an existing session

        Returns:
            JSON string with scroll status
        """
        try:
            self._initialize_browser(connect_url)
            if self._page:
                if direction == "down":
                    self._page.evaluate(f"window.scrollBy(0, {pixels})")
                elif direction == "up":
                    self._page.evaluate(f"window.scrollBy(0, -{pixels})")
                elif direction == "right":
                    self._page.evaluate(f"window.scrollBy({pixels}, 0)")
                elif direction == "left":
                    self._page.evaluate(f"window.scrollBy(-{pixels}, 0)")
                else:
                    raise ValueError(f"Invalid direction: {direction}. Use 'up', 'down', 'left', or 'right'")
            return json.dumps({"status": "success", "action": "scroll", "direction": direction, "pixels": pixels})
        except Exception as e:
            self._cleanup()
            raise e

    def extract_text(self, selector: Optional[str] = None, connect_url: Optional[str] = None) -> str:
        """Extracts text content from the page or a specific element.

        Args:
            selector (str, optional): CSS selector for specific element. If None, extracts all page text
            connect_url (str, optional): The connection URL from an existing session

        Returns:
            JSON string with extracted text
        """
        try:
            self._initialize_browser(connect_url)
            if self._page:
                if selector:
                    element = self._page.query_selector(selector)
                    text = element.text_content() if element else ""
                else:
                    text = self._page.evaluate("document.body.innerText")
            else:
                text = ""
            return json.dumps({"status": "success", "text": text, "selector": selector})
        except Exception as e:
            self._cleanup()
            raise e

    def close_session(self) -> str:
        """Closes a browser session.
        Args:
            session_id (str, optional): The session ID to close. If not provided, will use the current session.
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
