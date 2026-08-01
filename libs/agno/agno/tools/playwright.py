"""PlaywrightTools — local browser automation via Playwright.

Provides tools for navigating websites, taking screenshots, extracting content,
and interacting with pages using a local Playwright browser.

Requires:
    pip install playwright
    playwright install chromium  # or firefox, webkit
"""

import json
import re
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
except ImportError:
    raise ImportError(
        "`playwright` not installed. Please install using `pip install playwright` "
        "and run `playwright install chromium`"
    )


class PlaywrightTools(Toolkit):
    def __init__(
        self,
        headless: bool = True,
        browser: str = "chromium",
        user_agent: Optional[str] = None,
        timeout_ms: int = 30000,
        enable_navigate_to: bool = True,
        enable_go_back: bool = True,
        enable_screenshot: bool = True,
        enable_get_page_content: bool = True,
        enable_close_session: bool = True,
        enable_click: bool = False,
        enable_type: bool = False,
        enable_fill_form: bool = False,
        enable_get_element_text: bool = False,
        enable_wait_for: bool = False,
        enable_evaluate_js: bool = False,
        enable_save_pdf: bool = False,
        all: bool = False,
        record_video_dir: Optional[str] = None,
        parse_html: bool = True,
        max_content_length: Optional[int] = 100000,
        **kwargs,
    ):
        """Initialize PlaywrightTools.

        Args:
            headless (bool): Run browser in headless mode. Defaults to True.
            browser (str): Browser to use: chromium, firefox, or webkit. Defaults to chromium.
            user_agent (str, optional): Custom user agent string.
            timeout_ms (int): Default timeout in milliseconds. Defaults to 30000.
            enable_navigate_to (bool): Enable URL navigation. Defaults to True.
            enable_go_back (bool): Enable history back navigation. Defaults to True.
            enable_screenshot (bool): Enable screenshots. Defaults to True.
            enable_get_page_content (bool): Enable page content extraction. Defaults to True.
            enable_close_session (bool): Enable session cleanup. Defaults to True.
            enable_click (bool): Enable clicking elements. Defaults to False.
            enable_type (bool): Enable typing text. Defaults to False.
            enable_fill_form (bool): Enable form filling. Defaults to False.
            enable_get_element_text (bool): Enable element text extraction. Defaults to False.
            enable_wait_for (bool): Enable waiting for elements. Defaults to False.
            enable_evaluate_js (bool): Enable JavaScript execution. Defaults to False.
            enable_save_pdf (bool): Enable PDF generation. Defaults to False.
            all (bool): Enable all tools. Defaults to False.
            record_video_dir (str, optional): Directory to save video recordings.
            parse_html (bool): If True, extract only visible text content instead of raw HTML. Defaults to True.
            max_content_length (int, optional): Maximum character length for page content. Defaults to 100000.
        """
        self.headless = headless
        self.browser_type = browser
        self.user_agent = user_agent
        self.timeout_ms = timeout_ms
        self.record_video_dir = record_video_dir
        self.parse_html = parse_html
        self.max_content_length = max_content_length

        # Sync playwright state
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

        # Async playwright state
        self._async_playwright = None
        self._async_browser = None
        self._async_context = None
        self._async_page = None

        # Build tools lists
        tools: List[Any] = []
        async_tools: List[tuple] = []

        if all or enable_navigate_to:
            tools.append(self.navigate_to)
            async_tools.append((self.anavigate_to, "navigate_to"))
        if all or enable_go_back:
            tools.append(self.go_back)
            async_tools.append((self.ago_back, "go_back"))
        if all or enable_screenshot:
            tools.append(self.screenshot)
            async_tools.append((self.ascreenshot, "screenshot"))
        if all or enable_get_page_content:
            tools.append(self.get_page_content)
            async_tools.append((self.aget_page_content, "get_page_content"))
        if all or enable_close_session:
            tools.append(self.close_session)
            async_tools.append((self.aclose_session, "close_session"))
        if all or enable_click:
            tools.append(self.click)
            async_tools.append((self.aclick, "click"))
        if all or enable_type:
            tools.append(self.type_text)
            async_tools.append((self.atype_text, "type_text"))
        if all or enable_fill_form:
            tools.append(self.fill_form)
            async_tools.append((self.afill_form, "fill_form"))
        if all or enable_get_element_text:
            tools.append(self.get_element_text)
            async_tools.append((self.aget_element_text, "get_element_text"))
        if all or enable_wait_for:
            tools.append(self.wait_for)
            async_tools.append((self.await_for, "wait_for"))
        if all or enable_evaluate_js:
            tools.append(self.evaluate_js)
            async_tools.append((self.aevaluate_js, "evaluate_js"))
        if all or enable_save_pdf:
            tools.append(self.save_pdf)
            async_tools.append((self.asave_pdf, "save_pdf"))
        if record_video_dir:
            tools.append(self.get_recording)
            async_tools.append((self.aget_recording, "get_recording"))

        super().__init__(name="playwright_tools", tools=tools, async_tools=async_tools, **kwargs)

    def _initialize_browser(self):
        """Initialize sync browser if not already initialized."""
        if self._page:
            return

        self._playwright = sync_playwright().start()  # type: ignore[assignment]
        browser_launcher = getattr(self._playwright, self.browser_type)
        self._browser = browser_launcher.launch(headless=self.headless)

        context_options: Dict[str, Any] = {}
        if self.user_agent:
            context_options["user_agent"] = self.user_agent
        if self.record_video_dir:
            context_options["record_video_dir"] = self.record_video_dir

        context = self._browser.new_context(**context_options)  # type: ignore[attr-defined]
        context.set_default_timeout(self.timeout_ms)
        self._context = context
        self._page = context.new_page()
        log_debug(f"Playwright browser initialized: {self.browser_type}, headless={self.headless}")

    def _cleanup(self):
        """Clean up sync browser resources."""
        if self._context:
            self._context.close()
            self._context = None
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None
        self._page = None

    def _extract_text_content(self, html: str) -> str:
        """Extract visible text content from HTML, removing scripts, styles, and tags."""
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
        html = re.sub(r"<[^>]+>", " ", html)
        html = html.replace("&nbsp;", " ")
        html = html.replace("&amp;", "&")
        html = html.replace("&lt;", "<")
        html = html.replace("&gt;", ">")
        html = html.replace("&quot;", '"')
        html = html.replace("&#39;", "'")
        html = re.sub(r"\s+", " ", html)
        return html.strip()

    def _truncate_content(self, content: str) -> str:
        """Truncate content if it exceeds max_content_length."""
        if self.max_content_length is None or len(content) <= self.max_content_length:
            return content
        truncated = content[: self.max_content_length]
        return f"{truncated}\n\n[Content truncated. Original length: {len(content)} characters. Showing first {self.max_content_length} characters.]"

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
            result = {"status": "complete", "title": self._page.title() if self._page else "", "url": url}
            return json.dumps(result)
        except Exception as e:
            self._cleanup()
            raise e

    def go_back(self) -> str:
        """Navigates back in browser history.

        Returns:
            JSON string with navigation status
        """
        try:
            self._initialize_browser()
            if self._page:
                self._page.go_back(wait_until="networkidle")
            title = self._page.title() if self._page else ""
            url = self._page.url if self._page else ""
            return json.dumps({"status": "complete", "title": title, "url": url})
        except Exception as e:
            self._cleanup()
            raise e

    def screenshot(self, path: str, full_page: bool = True) -> str:
        """Takes a screenshot of the current page.

        Args:
            path (str): File path to save the screenshot
            full_page (bool): Whether to capture the full scrollable page

        Returns:
            JSON string confirming screenshot was saved
        """
        try:
            self._initialize_browser()
            if self._page:
                self._page.screenshot(path=path, full_page=full_page)
            return json.dumps({"status": "success", "path": path})
        except Exception as e:
            self._cleanup()
            raise e

    def get_page_content(self) -> str:
        """Gets the content of the current page.

        Returns:
            The page content (text-only if parse_html=True, otherwise raw HTML)
        """
        try:
            self._initialize_browser()
            if not self._page:
                return ""

            raw_content = self._page.content()

            if self.parse_html:
                content = self._extract_text_content(raw_content)
            else:
                content = raw_content

            return self._truncate_content(content)
        except Exception as e:
            self._cleanup()
            raise e

    def close_session(self) -> str:
        """Closes the browser session.

        Returns:
            JSON string with closure status
        """
        try:
            self._cleanup()
            return json.dumps({"status": "closed", "message": "Browser session closed"})
        except Exception as e:
            return json.dumps({"status": "warning", "message": f"Cleanup completed with warning: {str(e)}"})

    def click(self, selector: str) -> str:
        """Clicks an element on the page.

        Args:
            selector (str): CSS selector of element to click

        Returns:
            JSON string with click status
        """
        try:
            self._initialize_browser()
            if self._page:
                self._page.click(selector)
            return json.dumps({"status": "success", "selector": selector})
        except Exception as e:
            self._cleanup()
            raise e

    def type_text(self, selector: str, text: str) -> str:
        """Types text into an input element.

        Args:
            selector (str): CSS selector of input element
            text (str): Text to type

        Returns:
            JSON string with typing status
        """
        try:
            self._initialize_browser()
            if self._page:
                self._page.fill(selector, text)
            return json.dumps({"status": "success", "selector": selector})
        except Exception as e:
            self._cleanup()
            raise e

    def fill_form(self, form_data: Dict[str, str]) -> str:
        """Fills multiple form fields at once.

        Args:
            form_data (dict): Dictionary mapping CSS selectors to values

        Returns:
            JSON string with fill status
        """
        try:
            self._initialize_browser()
            if self._page:
                for selector, value in form_data.items():
                    self._page.fill(selector, value)
            return json.dumps({"status": "success", "filled": list(form_data.keys())})
        except Exception as e:
            self._cleanup()
            raise e

    def get_element_text(self, selector: str) -> str:
        """Gets text content of a specific element.

        Args:
            selector (str): CSS selector of element

        Returns:
            JSON string with the text content
        """
        try:
            self._initialize_browser()
            if not self._page:
                return json.dumps({"status": "error", "message": "No active page"})
            element = self._page.query_selector(selector)
            if element:
                return json.dumps({"status": "success", "text": element.inner_text()})
            return json.dumps({"status": "error", "message": f"Element not found: {selector}"})
        except Exception as e:
            self._cleanup()
            raise e

    def wait_for(self, selector: str, timeout_ms: Optional[int] = None) -> str:
        """Waits for an element to appear on the page.

        Args:
            selector (str): CSS selector to wait for
            timeout_ms (int, optional): Maximum time to wait in milliseconds

        Returns:
            JSON string with wait status
        """
        try:
            self._initialize_browser()
            if self._page:
                self._page.wait_for_selector(selector, timeout=timeout_ms or self.timeout_ms)
            return json.dumps({"status": "success", "selector": selector})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e), "selector": selector})

    def evaluate_js(self, expression: str) -> str:
        """Executes JavaScript on the page.

        Args:
            expression (str): JavaScript expression to evaluate

        Returns:
            JSON string with the evaluation result
        """
        try:
            self._initialize_browser()
            if not self._page:
                return json.dumps({"status": "error", "message": "No active page"})
            result = self._page.evaluate(expression)
            return json.dumps({"status": "success", "result": result})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    def save_pdf(self, path: str) -> str:
        """Generates a PDF of the current page. Chromium only.

        Args:
            path (str): File path to save the PDF

        Returns:
            JSON string confirming PDF was saved
        """
        try:
            self._initialize_browser()
            if self._page:
                self._page.pdf(path=path)
            return json.dumps({"status": "success", "path": path})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e), "path": path})

    def get_recording(self) -> str:
        """Gets the video recording path. Closes the session to finalize the video.

        Returns:
            JSON string with the video file path
        """
        try:
            if not self.record_video_dir:
                return json.dumps({"status": "error", "message": "Video recording not enabled"})
            if not self._page:
                return json.dumps({"status": "error", "message": "No active session"})
            video = self._page.video
            if not video:
                return json.dumps({"status": "error", "message": "No video available"})
            path = video.path()
            self._cleanup()
            return json.dumps({"status": "success", "path": path})
        except Exception as e:
            self._cleanup()
            return json.dumps({"status": "error", "message": str(e)})

    # Async methods

    async def _ainitialize_browser(self):
        """Initialize async browser if not already initialized."""
        if self._async_page:
            return

        try:
            from playwright.async_api import async_playwright  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError(
                "`playwright` not installed. Please install using `pip install playwright` "
                "and run `playwright install chromium`"
            )

        self._async_playwright = await async_playwright().start()  # type: ignore[assignment]
        browser_launcher = getattr(self._async_playwright, self.browser_type)
        self._async_browser = await browser_launcher.launch(headless=self.headless)

        context_options: Dict[str, Any] = {}
        if self.user_agent:
            context_options["user_agent"] = self.user_agent
        if self.record_video_dir:
            context_options["record_video_dir"] = self.record_video_dir

        context = await self._async_browser.new_context(**context_options)  # type: ignore[attr-defined]
        context.set_default_timeout(self.timeout_ms)
        self._async_context = context
        self._async_page = await context.new_page()
        log_debug(f"Async Playwright browser initialized: {self.browser_type}, headless={self.headless}")

    async def _acleanup(self):
        """Clean up async browser resources."""
        if self._async_context:
            await self._async_context.close()
            self._async_context = None
        if self._async_browser:
            await self._async_browser.close()
            self._async_browser = None
        if self._async_playwright:
            await self._async_playwright.stop()
            self._async_playwright = None
        self._async_page = None

    async def anavigate_to(self, url: str) -> str:
        """Navigates to a URL asynchronously.

        Args:
            url (str): The URL to navigate to

        Returns:
            JSON string with navigation status
        """
        try:
            await self._ainitialize_browser()
            if self._async_page:
                await self._async_page.goto(url, wait_until="networkidle")
            title = await self._async_page.title() if self._async_page else ""
            return json.dumps({"status": "complete", "title": title, "url": url})
        except Exception as e:
            await self._acleanup()
            raise e

    async def ago_back(self) -> str:
        """Navigates back in browser history asynchronously.

        Returns:
            JSON string with navigation status
        """
        try:
            await self._ainitialize_browser()
            if self._async_page:
                await self._async_page.go_back(wait_until="networkidle")
            title = await self._async_page.title() if self._async_page else ""
            url = self._async_page.url if self._async_page else ""
            return json.dumps({"status": "complete", "title": title, "url": url})
        except Exception as e:
            await self._acleanup()
            raise e

    async def ascreenshot(self, path: str, full_page: bool = True) -> str:
        """Takes a screenshot of the current page asynchronously.

        Args:
            path (str): File path to save the screenshot
            full_page (bool): Whether to capture the full scrollable page

        Returns:
            JSON string confirming screenshot was saved
        """
        try:
            await self._ainitialize_browser()
            if self._async_page:
                await self._async_page.screenshot(path=path, full_page=full_page)
            return json.dumps({"status": "success", "path": path})
        except Exception as e:
            await self._acleanup()
            raise e

    async def aget_page_content(self) -> str:
        """Gets the content of the current page asynchronously.

        Returns:
            The page content (text-only if parse_html=True, otherwise raw HTML)
        """
        try:
            await self._ainitialize_browser()
            if not self._async_page:
                return ""

            raw_content = await self._async_page.content()

            if self.parse_html:
                content = self._extract_text_content(raw_content)
            else:
                content = raw_content

            return self._truncate_content(content)
        except Exception as e:
            await self._acleanup()
            raise e

    async def aclose_session(self) -> str:
        """Closes the browser session asynchronously.

        Returns:
            JSON string with closure status
        """
        try:
            await self._acleanup()
            return json.dumps({"status": "closed", "message": "Browser session closed"})
        except Exception as e:
            return json.dumps({"status": "warning", "message": f"Cleanup completed with warning: {str(e)}"})

    async def aclick(self, selector: str) -> str:
        """Clicks an element on the page asynchronously.

        Args:
            selector (str): CSS selector of element to click

        Returns:
            JSON string with click status
        """
        try:
            await self._ainitialize_browser()
            if self._async_page:
                await self._async_page.click(selector)
            return json.dumps({"status": "success", "selector": selector})
        except Exception as e:
            await self._acleanup()
            raise e

    async def atype_text(self, selector: str, text: str) -> str:
        """Types text into an input element asynchronously.

        Args:
            selector (str): CSS selector of input element
            text (str): Text to type

        Returns:
            JSON string with typing status
        """
        try:
            await self._ainitialize_browser()
            if self._async_page:
                await self._async_page.fill(selector, text)
            return json.dumps({"status": "success", "selector": selector})
        except Exception as e:
            await self._acleanup()
            raise e

    async def afill_form(self, form_data: Dict[str, str]) -> str:
        """Fills multiple form fields at once asynchronously.

        Args:
            form_data (dict): Dictionary mapping CSS selectors to values

        Returns:
            JSON string with fill status
        """
        try:
            await self._ainitialize_browser()
            if self._async_page:
                for selector, value in form_data.items():
                    await self._async_page.fill(selector, value)
            return json.dumps({"status": "success", "filled": list(form_data.keys())})
        except Exception as e:
            await self._acleanup()
            raise e

    async def aget_element_text(self, selector: str) -> str:
        """Gets text content of a specific element asynchronously.

        Args:
            selector (str): CSS selector of element

        Returns:
            JSON string with the text content
        """
        try:
            await self._ainitialize_browser()
            if not self._async_page:
                return json.dumps({"status": "error", "message": "No active page"})
            element = await self._async_page.query_selector(selector)
            if element:
                text = await element.inner_text()
                return json.dumps({"status": "success", "text": text})
            return json.dumps({"status": "error", "message": f"Element not found: {selector}"})
        except Exception as e:
            await self._acleanup()
            raise e

    async def await_for(self, selector: str, timeout_ms: Optional[int] = None) -> str:
        """Waits for an element to appear on the page asynchronously.

        Args:
            selector (str): CSS selector to wait for
            timeout_ms (int, optional): Maximum time to wait in milliseconds

        Returns:
            JSON string with wait status
        """
        try:
            await self._ainitialize_browser()
            if self._async_page:
                await self._async_page.wait_for_selector(selector, timeout=timeout_ms or self.timeout_ms)
            return json.dumps({"status": "success", "selector": selector})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e), "selector": selector})

    async def aevaluate_js(self, expression: str) -> str:
        """Executes JavaScript on the page asynchronously.

        Args:
            expression (str): JavaScript expression to evaluate

        Returns:
            JSON string with the evaluation result
        """
        try:
            await self._ainitialize_browser()
            if not self._async_page:
                return json.dumps({"status": "error", "message": "No active page"})
            result = await self._async_page.evaluate(expression)
            return json.dumps({"status": "success", "result": result})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def asave_pdf(self, path: str) -> str:
        """Generates a PDF of the current page asynchronously. Chromium only.

        Args:
            path (str): File path to save the PDF

        Returns:
            JSON string confirming PDF was saved
        """
        try:
            await self._ainitialize_browser()
            if self._async_page:
                await self._async_page.pdf(path=path)
            return json.dumps({"status": "success", "path": path})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e), "path": path})

    async def aget_recording(self) -> str:
        """Gets the video recording path asynchronously. Closes the session to finalize the video.

        Returns:
            JSON string with the video file path
        """
        try:
            if not self.record_video_dir:
                return json.dumps({"status": "error", "message": "Video recording not enabled"})
            if not self._async_page:
                return json.dumps({"status": "error", "message": "No active session"})
            video = self._async_page.video
            if not video:
                return json.dumps({"status": "error", "message": "No video available"})
            path = await video.path()
            await self._acleanup()
            return json.dumps({"status": "success", "path": path})
        except Exception as e:
            await self._acleanup()
            return json.dumps({"status": "error", "message": str(e)})
