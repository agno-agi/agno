import json
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    from playwright.sync_api import Browser, Page, Playwright, sync_playwright
except ImportError:
    raise ImportError("`playwright` not installed. Please install using `pip install playwright && playwright install`")


class PlaywrightTools(Toolkit):
    def __init__(
        self,
        enable_navigate_to: bool = True,
        enable_screenshot: bool = False,
        enable_get_page_content: bool = True,
        enable_close_session: bool = True,
        enable_get_current_url: bool = True,
        enable_go_back: bool = True,
        enable_go_forward: bool = True,
        enable_reload_page: bool = False,
        enable_click_element: bool = True,
        enable_fill_input: bool = True,
        enable_wait_for_element: bool = False,
        enable_scroll_page: bool = True,
        enable_extract_page_text: bool = False,
        enable_submit_form: bool = True,
        enable_wait_and_extract_text: bool = False,
        all: bool = False,
        timeout: int = 60000,
        headless: bool = True,
        **kwargs,
    ):
        self.timeout = timeout
        self.headless = headless

        # Browser session state - initialized once and reused
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self._session_initialized = False

        tools: List[Any] = []
        if all or enable_navigate_to:
            tools.append(self.navigate_to)
        if all or enable_screenshot:
            tools.append(self.screenshot)
        if all or enable_get_page_content:
            tools.append(self.get_page_content)
        if all or enable_close_session:
            tools.append(self.close_session)
        if all or enable_get_current_url:
            tools.append(self.get_current_url)
        if all or enable_go_back:
            tools.append(self.go_back)
        if all or enable_go_forward:
            tools.append(self.go_forward)
        if all or enable_reload_page:
            tools.append(self.reload_page)
        if all or enable_click_element:
            tools.append(self.click_element)
        if all or enable_fill_input:
            tools.append(self.fill_input)
        if all or enable_wait_for_element:
            tools.append(self.wait_for_element)
        if all or enable_scroll_page:
            tools.append(self.scroll_page)
        if all or enable_extract_page_text:
            tools.append(self.extract_page_text)
        if all or enable_submit_form:
            tools.append(self.submit_form)
        if all or enable_wait_and_extract_text:
            tools.append(self.wait_and_extract_text)

        super().__init__(name="playwright", tools=tools, **kwargs)

    def _ensure_browser_ready(self):
        """Ensures local browser is ready. Creates and initializes if needed."""
        if self._session_initialized:
            return

        try:
            # Initialize local browser
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self.headless)

            # Create new context and page
            context = self._browser.new_context()
            self._page = context.new_page()

            self._session_initialized = True
            log_debug("Local Playwright browser initialized")

        except Exception as e:
            log_error(f"Failed to initialize playwright browser: {str(e)}")
            self._cleanup_resources()
            raise

    def _cleanup_resources(self):
        """Clean up browser resources."""
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._page = None
        self._session_initialized = False

    def navigate_to(self, url: str) -> str:
        """Navigates to a URL.

        Args:
            url (str): The URL to navigate to.

        Returns:
            str: JSON string with navigation status, page title, and URL.
        """
        self._ensure_browser_ready()
        self._page.goto(url, wait_until="networkidle", timeout=self.timeout)  # type: ignore[union-attr]
        result = {"status": "complete", "title": self._page.title(), "url": url}  # type: ignore[union-attr]
        return json.dumps(result)

    def screenshot(self, path: str, full_page: bool = True) -> str:
        """Takes a screenshot of the current page.

        Args:
            path (str): File path where the screenshot will be saved.
            full_page (bool, optional): Whether to take a full page screenshot. Default is True.

        Returns:
            str: JSON string with success status and file path.
        """
        self._ensure_browser_ready()
        self._page.screenshot(path=path, full_page=full_page)  # type: ignore[union-attr]
        return json.dumps({"status": "success", "path": path})

    def get_page_content(self) -> str:
        """Gets the HTML content of the current page.

        Returns:
            str: HTML content of the page.
        """
        self._ensure_browser_ready()
        return self._page.content()  # type: ignore[union-attr]

    def get_current_url(self) -> str:
        """Gets the current URL of the page.

        Returns:
            str: JSON string with success status and current URL.
        """
        self._ensure_browser_ready()
        current_url = self._page.url  # type: ignore[union-attr]
        return json.dumps({"status": "success", "url": current_url})

    def go_back(self) -> str:
        """Navigates back in browser history.

        Returns:
            str: JSON string with success status, action, and new URL.
        """
        self._ensure_browser_ready()
        self._page.go_back(wait_until="networkidle")  # type: ignore[union-attr]
        new_url = self._page.url  # type: ignore[union-attr]
        return json.dumps({"status": "success", "action": "go_back", "url": new_url})

    def go_forward(self) -> str:
        """Navigates forward in browser history.

        Returns:
            str: JSON string with success status, action, and new URL.
        """
        self._ensure_browser_ready()
        self._page.go_forward(wait_until="networkidle")  # type: ignore[union-attr]
        new_url = self._page.url  # type: ignore[union-attr]
        return json.dumps({"status": "success", "action": "go_forward", "url": new_url})

    def reload_page(self) -> str:
        """Reloads/refreshes the current page.

        Returns:
            str: JSON string with success status, action, and current URL.
        """
        self._ensure_browser_ready()
        self._page.reload(wait_until="networkidle")  # type: ignore[union-attr]
        current_url = self._page.url  # type: ignore[union-attr]
        return json.dumps({"status": "success", "action": "reload", "url": current_url})

    def click_element(self, selector: str) -> str:
        """Clicks on an element identified by CSS selector.

        Args:
            selector (str): CSS selector for the element to click.

        Returns:
            str: JSON string with success status, action, and selector.
        """
        self._ensure_browser_ready()
        self._page.click(selector, timeout=self.timeout)  # type: ignore[union-attr]
        return json.dumps({"status": "success", "action": "click", "selector": selector})

    def fill_input(self, selector: str, text: str) -> str:
        """Fills an input field identified by CSS selector.

        Args:
            selector (str): CSS selector for the input element.
            text (str): Text to fill into the input field.

        Returns:
            str: JSON string with success status, action, selector, and text.
        """
        self._ensure_browser_ready()
        self._page.fill(selector, text, timeout=self.timeout)  # type: ignore[union-attr]
        return json.dumps({"status": "success", "action": "fill", "selector": selector, "text": text})

    def wait_for_element(self, selector: str) -> str:
        """Waits for an element to appear on the page.

        Args:
            selector (str): CSS selector for the element to wait for.

        Returns:
            str: JSON string with success status, action, and selector.
        """
        self._ensure_browser_ready()
        self._page.wait_for_selector(selector, timeout=self.timeout)  # type: ignore[union-attr]
        return json.dumps({"status": "success", "action": "wait_for_element", "selector": selector})

    def scroll_page(self, direction: str = "down", pixels: int = 500) -> str:
        """Scrolls the page in the specified direction.

        Args:
            direction (str, optional): Direction to scroll ('up', 'down', 'left', 'right'). Default is "down".
            pixels (int, optional): Number of pixels to scroll. Default is 500.

        Returns:
            str: JSON string with success status, action, direction, and pixels.

        Raises:
            ValueError: If an invalid direction is provided.
        """
        self._ensure_browser_ready()
        if direction == "down":
            self._page.evaluate(f"window.scrollBy(0, {pixels})")  # type: ignore[union-attr]
        elif direction == "up":
            self._page.evaluate(f"window.scrollBy(0, -{pixels})")  # type: ignore[union-attr]
        elif direction == "right":
            self._page.evaluate(f"window.scrollBy({pixels}, 0)")  # type: ignore[union-attr]
        elif direction == "left":
            self._page.evaluate(f"window.scrollBy(-{pixels}, 0)")  # type: ignore[union-attr]
        else:
            raise ValueError(f"Invalid direction: {direction}. Use 'up', 'down', 'left', or 'right'")
        return json.dumps({"status": "success", "action": "scroll", "direction": direction, "pixels": pixels})

    def extract_page_text(self) -> str:
        """Extracts all text content from the entire page.

        Returns:
            str: JSON string with success status and extracted text, or error status if failed.
        """
        self._ensure_browser_ready()

        try:
            # Wait for page to be fully loaded
            self._page.wait_for_load_state("networkidle", timeout=self.timeout)  # type: ignore[union-attr]
            text = self._page.evaluate("document.body.textContent")  # type: ignore[union-attr]

            return json.dumps({"status": "success", "text": text})

        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)})

    def submit_form(self, form_selector: str = "form", wait_for_navigation: bool = True) -> str:
        """Submits a form and optionally waits for navigation/page change.

        Args:
            form_selector (str, optional): CSS selector for the form element. Default is "form".
            wait_for_navigation (bool, optional): Whether to wait for page navigation after submission. Default is True.

        Returns:
            str: JSON string with success status, action, and selector, or error status if failed.
        """
        self._ensure_browser_ready()

        try:
            if wait_for_navigation:
                # Wait for navigation to complete after form submission
                with self._page.expect_navigation(timeout=self.timeout):  # type: ignore[union-attr]
                    self._page.evaluate(f"document.querySelector('{form_selector}').submit()")  # type: ignore[union-attr]
            else:
                self._page.evaluate(f"document.querySelector('{form_selector}').submit()")  # type: ignore[union-attr]

            # Wait for content to load after submission
            self._page.wait_for_load_state("networkidle", timeout=self.timeout)  # type: ignore[union-attr]

            return json.dumps({"status": "success", "action": "form_submit", "selector": form_selector})

        except Exception as e:
            return json.dumps({"status": "error", "error": str(e), "selector": form_selector})

    def wait_and_extract_text(self, selector: str, max_attempts: int = 3, wait_seconds: int = 2) -> str:
        """Waits for content to load and extracts text with multiple attempts.

        Args:
            selector (str): CSS selector to target.
            max_attempts (int, optional): Maximum number of extraction attempts. Default is 3.
            wait_seconds (int, optional): Seconds to wait between attempts. Default is 2.

        Returns:
            str: JSON string with success status and extracted text, warning status if no content found, or error status if failed.
        """
        self._ensure_browser_ready()

        for attempt in range(max_attempts):
            try:
                # Wait for element and network idle
                self._page.wait_for_selector(selector, timeout=self.timeout)  # type: ignore[union-attr]
                self._page.wait_for_load_state("networkidle", timeout=self.timeout)  # type: ignore[union-attr]

                # Additional wait for dynamic content
                self._page.wait_for_timeout(wait_seconds * 1000)  # type: ignore[union-attr]

                # Try to extract text
                element = self._page.query_selector(selector)  # type: ignore[union-attr]
                if element:
                    text = element.inner_text()
                    if text.strip():  # If we got non-empty text, return it
                        return json.dumps(
                            {"status": "success", "text": text, "selector": selector, "attempt": attempt + 1}
                        )

                # If no text found, wait a bit more for the next attempt
                if attempt < max_attempts - 1:
                    self._page.wait_for_timeout(wait_seconds * 1000)  # type: ignore[union-attr]

            except Exception as e:
                if attempt == max_attempts - 1:  # Last attempt
                    return json.dumps(
                        {"status": "error", "error": str(e), "selector": selector, "attempts": max_attempts}
                    )

        return json.dumps(
            {
                "status": "warning",
                "text": "",
                "selector": selector,
                "message": f"No content found after {max_attempts} attempts",
            }
        )

    def close_session(self) -> str:
        """Closes the browser session and cleans up resources.

        Returns:
            str: JSON string with closed status and message, or warning status if cleanup had issues.
        """
        try:
            self._cleanup_resources()
            return json.dumps({"status": "closed", "message": "Local browser closed and resources cleaned up."})
        except Exception as e:
            return json.dumps({"status": "warning", "message": f"Cleanup completed with warning: {str(e)}"})
