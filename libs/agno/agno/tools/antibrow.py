import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from antibrow import launch
except ImportError:
    raise ImportError("`antibrow` not installed. Please install using `pip install antibrow`")


class AntibrowTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        profile: str = "agent",
        proxy: Optional[str] = None,
        temporary: bool = False,
        headless: bool = False,
        max_content_length: Optional[int] = 100000,
        enable_navigate_to: bool = True,
        enable_get_page_content: bool = True,
        enable_click: bool = True,
        enable_fill: bool = True,
        enable_screenshot: bool = True,
        enable_close_session: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize AntibrowTools.

        Args:
            api_key (str, optional): AntiBrow API key. Falls back to ANTIBROW_API_KEY.
            profile (str): Profile name. The same name always gets the same fingerprint,
                cookies and storage, so an agent that signed in on an earlier run is still
                signed in. Defaults to "agent".
            proxy (str, optional): Proxy URL for this profile (http, https or socks5, with
                credentials in the URL). The engine answers the challenge itself.
            temporary (bool): Discard the profile when the session closes. Defaults to False.
            headless (bool): Hide the window. Defaults to False.
            max_content_length (int, optional): Maximum character length for page content.
                Content over the limit is truncated with a notice. None for no limit.
            enable_navigate_to (bool): Enable the navigate_to tool. Defaults to True.
            enable_get_page_content (bool): Enable the get_page_content tool. Defaults to True.
            enable_click (bool): Enable the click tool. Defaults to True.
            enable_fill (bool): Enable the fill tool. Defaults to True.
            enable_screenshot (bool): Enable the screenshot tool. Defaults to True.
            enable_close_session (bool): Enable the close_session tool. Defaults to True.
            all (bool): Enable all tools. Defaults to False.
        """
        self.api_key = api_key or getenv("ANTIBROW_API_KEY")
        self.profile = profile
        self.proxy = proxy
        self.temporary = temporary
        self.headless = headless
        self.max_content_length = max_content_length

        self._browser = None
        self._page = None

        tools: List[Any] = []
        if all or enable_navigate_to:
            tools.append(self.navigate_to)
        if all or enable_get_page_content:
            tools.append(self.get_page_content)
        if all or enable_click:
            tools.append(self.click)
        if all or enable_fill:
            tools.append(self.fill)
        if all or enable_screenshot:
            tools.append(self.screenshot)
        if all or enable_close_session:
            tools.append(self.close_session)

        super().__init__(name="antibrow_tools", tools=tools, **kwargs)

    def _initialize_browser(self):
        """Launch the profile once; every tool then drives the same page."""
        if self._page is not None:
            return
        try:
            self._browser = launch(
                self.profile,
                api_key=self.api_key,
                proxy=self.proxy,
                temporary=self.temporary,
                headless=self.headless,
                focus_window=False,
            )
            self._page = self._browser.new_page()
            log_debug(f"Launched AntiBrow profile: {self.profile}")
        except Exception:
            logger.exception("Failed to launch the AntiBrow profile")
            self._cleanup()
            raise

    def _cleanup(self):
        """Close the browser. An abandoned one is a whole Chromium still running."""
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                logger.exception("Failed to close the AntiBrow profile")
        self._browser = None
        self._page = None

    def _truncate(self, text: str) -> str:
        if self.max_content_length is None or len(text) <= self.max_content_length:
            return text
        return text[: self.max_content_length] + "\n\n[content truncated]"

    def navigate_to(self, url: str) -> str:
        """Navigates the profile to a URL.

        Args:
            url (str): The URL to navigate to.

        Returns:
            JSON string with the HTTP status, the page title and the final URL.
        """
        self._initialize_browser()
        response = self._page.goto(url, wait_until="load")
        return json.dumps(
            {
                "status": response.status if response is not None else None,
                "title": self._page.title(),
                "url": self._page.url,
            }
        )

    def get_page_content(self, selector: Optional[str] = None) -> str:
        """Reads the visible text of the current page.

        Args:
            selector (str, optional): CSS selector to read. Omit for the whole page.

        Returns:
            JSON string with the URL and the visible text, truncated to max_content_length.
        """
        self._initialize_browser()
        text = self._page.locator(selector or "body").first.inner_text()
        return json.dumps({"url": self._page.url, "content": self._truncate(text)})

    def click(self, selector: str) -> str:
        """Clicks an element on the current page.

        Args:
            selector (str): CSS selector of the element to click.

        Returns:
            JSON string with the selector clicked and the resulting URL.
        """
        self._initialize_browser()
        self._page.locator(selector).first.click()
        return json.dumps({"clicked": selector, "url": self._page.url})

    def fill(self, selector: str, text: str) -> str:
        """Types text into an input on the current page.

        Args:
            selector (str): CSS selector of the input to fill.
            text (str): Text to type into it.

        Returns:
            JSON string confirming what was filled.
        """
        self._initialize_browser()
        self._page.locator(selector).first.fill(text)
        return json.dumps({"filled": selector, "characters": len(text)})

    def screenshot(self, path: str, full_page: bool = True) -> str:
        """Takes a screenshot of the current page.

        Args:
            path (str): Where to save the screenshot.
            full_page (bool): Whether to capture the full page. Defaults to True.

        Returns:
            JSON string confirming the screenshot was saved.
        """
        self._initialize_browser()
        self._page.screenshot(path=path, full_page=full_page)
        return json.dumps({"status": "success", "path": path})

    def close_session(self) -> str:
        """Closes the browser session. The profile itself is kept unless temporary=True.

        Returns:
            JSON string confirming the session is closed.
        """
        self._cleanup()
        return json.dumps({"status": "closed", "profile": self.profile})
