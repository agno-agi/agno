import json
from typing import Any, List, Optional

try:
    from playwright.sync_api import Browser, Page, Playwright, sync_playwright
except ImportError:
    raise ImportError("Playwright is not installed. Please install it with 'pip install playwright'.")

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


class PlaywrightTools(Toolkit):
    def __init__(
        self,
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
        tools.append(self.scroll_page)
        tools.append(self.extract_page_text)
        tools.append(self.submit_form)
        tools.append(self.wait_for_element)

        super().__init__(name="playwright_tools", tools=tools, **kwargs)

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
        """Navigates to a URL using playwright browser."""
        self._ensure_browser_ready()
        self._page.goto(url, wait_until="networkidle", timeout=self.timeout)
        result = {"status": "complete", "title": self._page.title(), "url": url}
        return json.dumps(result)

    def screenshot(self, path: str, full_page: bool = True) -> str:
        """Takes a screenshot using playwright browser."""
        self._ensure_browser_ready()
        self._page.screenshot(path=path, full_page=full_page)
        return json.dumps({"status": "success", "path": path})

    def get_page_content(self) -> str:
        """Gets the HTML content using playwright browser."""
        self._ensure_browser_ready()
        return self._page.content()

    def get_current_url(self) -> str:
        """Gets the current URL using playwright browser."""
        self._ensure_browser_ready()
        current_url = self._page.url
        return json.dumps({"status": "success", "url": current_url})

    def go_back(self) -> str:
        """Navigates back in browser history using playwright browser."""
        self._ensure_browser_ready()
        self._page.go_back(wait_until="networkidle")
        new_url = self._page.url
        return json.dumps({"status": "success", "action": "go_back", "url": new_url})

    def go_forward(self) -> str:
        """Navigates forward in browser history using playwright browser."""
        self._ensure_browser_ready()
        self._page.go_forward(wait_until="networkidle")
        new_url = self._page.url
        return json.dumps({"status": "success", "action": "go_forward", "url": new_url})

    def reload_page(self) -> str:
        """Reloads/refreshes the current page using playwright browser."""
        self._ensure_browser_ready()
        self._page.reload(wait_until="networkidle")
        current_url = self._page.url
        return json.dumps({"status": "success", "action": "reload", "url": current_url})

    def click_element(self, selector: str) -> str:
        """Clicks on an element using playwright browser."""
        self._ensure_browser_ready()
        self._page.click(selector, timeout=self.timeout)
        return json.dumps({"status": "success", "action": "click", "selector": selector})

    def fill_input(self, selector: str, text: str) -> str:
        """Fills an input field using playwright browser."""
        self._ensure_browser_ready()
        self._page.fill(selector, text, timeout=self.timeout)
        return json.dumps({"status": "success", "action": "fill", "selector": selector, "text": text})

    def wait_for_element(self, selector: str) -> str:
        """Waits for an element to appear using playwright browser."""
        self._ensure_browser_ready()
        self._page.wait_for_selector(selector, timeout=self.timeout)
        return json.dumps({"status": "success", "action": "wait_for_element", "selector": selector})

    def scroll_page(self, direction: str = "down", pixels: int = 500) -> str:
        """Scrolls the page using playwright browser."""
        self._ensure_browser_ready()
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

    def extract_page_text(self) -> str:
        """Extracts all text content from the entire page."""
        self._ensure_browser_ready()

        try:
            # Wait for page to be fully loaded
            self._page.wait_for_load_state("networkidle", timeout=self.timeout)
            text = self._page.evaluate("document.body.textContent")

            return json.dumps({"status": "success", "text": text})

        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)})

    def submit_form(self, form_selector: str = "form", wait_for_navigation: bool = True) -> str:
        """Submits a form and optionally waits for navigation/page change.

        Args:
            form_selector: CSS selector for the form element
            wait_for_navigation: Whether to wait for page navigation after submission
        """
        self._ensure_browser_ready()

        try:
            if wait_for_navigation:
                # Wait for navigation to complete after form submission
                with self._page.expect_navigation(timeout=self.timeout):
                    self._page.evaluate(f"document.querySelector('{form_selector}').submit()")
            else:
                self._page.evaluate(f"document.querySelector('{form_selector}').submit()")

            # Wait for content to load after submission
            self._page.wait_for_load_state("networkidle", timeout=self.timeout)

            return json.dumps({"status": "success", "action": "form_submit", "selector": form_selector})

        except Exception as e:
            return json.dumps({"status": "error", "error": str(e), "selector": form_selector})

    def wait_and_extract_text(self, selector: str, max_attempts: int = 3, wait_seconds: int = 2) -> str:
        """Waits for content to load and extracts text with multiple attempts.

        Args:
            selector: CSS selector to target
            max_attempts: Maximum number of extraction attempts
            wait_seconds: Seconds to wait between attempts
        """
        self._ensure_browser_ready()

        for attempt in range(max_attempts):
            try:
                # Wait for element and network idle
                self._page.wait_for_selector(selector, timeout=self.timeout)
                self._page.wait_for_load_state("networkidle", timeout=self.timeout)

                # Additional wait for dynamic content
                self._page.wait_for_timeout(wait_seconds * 1000)

                # Try to extract text
                element = self._page.query_selector(selector)
                if element:
                    text = element.inner_text()
                    if text.strip():  # If we got non-empty text, return it
                        return json.dumps(
                            {"status": "success", "text": text, "selector": selector, "attempt": attempt + 1}
                        )

                # If no text found, wait a bit more for the next attempt
                if attempt < max_attempts - 1:
                    self._page.wait_for_timeout(wait_seconds * 1000)

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
        """Closes the local browser."""
        try:
            self._cleanup_resources()
            return json.dumps({"status": "closed", "message": "Local browser closed and resources cleaned up."})
        except Exception as e:
            return json.dumps({"status": "warning", "message": f"Cleanup completed with warning: {str(e)}"})
