import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

from agno.document.base import Document
from agno.document.reader.base import Reader
from agno.utils.log import log_debug, logger

try:
    from playwright.async_api import async_playwright
    from playwright.sync_api import sync_playwright
except ImportError:
    raise ImportError("The `playwright` package is not installed. Please install it via `pip install playwright`.")

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:
    raise ImportError("The `bs4` package is not installed. Please install it via `pip install beautifulsoup4`.")


@dataclass
class BrowserWebsiteReader(Reader):
    """Browser-based Website Reader using Playwright"""

    max_depth: int = 3
    max_links: int = 10
    browser_type: str = "chromium"  # chromium, firefox, webkit
    headless: bool = True
    user_agent: Optional[str] = None
    proxy: Optional[Dict[str, str]] = None
    timeout: int = 10000  # Playwright timeout in milliseconds
    wait_for_load_state: str = "domcontentloaded"  # networkidle, load, domcontentloaded
    viewport_size: Optional[Dict[str, int]] = None
    extra_wait_time: float = 0  # Additional wait time in seconds after page load

    _visited: Set[str] = field(default_factory=set)
    _urls_to_crawl: List[Tuple[str, int]] = field(default_factory=list)

    def __init__(
        self,
        max_depth: int = 3,
        max_links: int = 10,
        browser_type: str = "chromium",
        headless: bool = True,
        user_agent: Optional[str] = None,
        proxy: Optional[Dict[str, str]] = None,
        timeout: int = 30000,
        wait_for_load_state: str = "domcontentloaded",
        viewport_size: Optional[Dict[str, int]] = None,
        extra_wait_time: float = 0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.max_depth = max_depth
        self.max_links = max_links
        self.browser_type = browser_type.lower()
        self.headless = headless
        self.user_agent = user_agent
        self.proxy = proxy
        self.timeout = timeout
        self.wait_for_load_state = wait_for_load_state
        self.viewport_size = viewport_size or {"width": 1920, "height": 1080}
        self.extra_wait_time = extra_wait_time

        self._visited = set()
        self._urls_to_crawl = []

        # Validate browser type
        if self.browser_type not in ["chromium", "firefox", "webkit"]:
            raise ValueError(f"Unsupported browser type: {self.browser_type}. Use 'chromium', 'firefox', or 'webkit'")

        # Validate wait_for_load_state
        if self.wait_for_load_state not in ["networkidle", "load", "domcontentloaded"]:
            raise ValueError(f"Invalid wait_for_load_state: {self.wait_for_load_state}")

    def delay(self, min_seconds: float = 1, max_seconds: float = 3):
        """Introduce a random delay."""
        sleep_time = random.uniform(min_seconds, max_seconds)
        time.sleep(sleep_time)

    async def async_delay(self, min_seconds: float = 1, max_seconds: float = 3):
        """Introduce a random delay asynchronously."""
        sleep_time = random.uniform(min_seconds, max_seconds)
        await asyncio.sleep(sleep_time)

    def _get_primary_domain(self, url: str) -> str:
        """Extract primary domain from the given URL."""
        domain_parts = urlparse(url).netloc.split(".")
        return ".".join(domain_parts[-2:])

    def _extract_main_content(self, soup: BeautifulSoup) -> str:
        """Extract the main content from a BeautifulSoup object."""

        def match(tag: Tag) -> bool:
            if tag.name in ["article", "main"]:
                return True
            if any(cls in ["content", "main-content", "post-content"] for cls in tag.get("class", [])):
                return True
            return False

        element = soup.find(match)
        if element:
            return element.get_text(strip=True, separator=" ")

        if soup.find("div") and not any(
            soup.find(class_=class_name) for class_name in ["content", "main-content", "post-content"]
        ):
            return ""

        return soup.get_text(strip=True, separator=" ")

    def _get_browser_launch_options(self) -> Dict:
        """Get browser launch options."""
        options = {
            "headless": self.headless,
        }

        if self.proxy:
            options["proxy"] = self.proxy

        return options

    def _get_context_options(self) -> Dict:
        """Get browser context options."""
        options = {
            "viewport": self.viewport_size,
        }

        if self.user_agent:
            options["user_agent"] = self.user_agent

        return options

    def crawl(self, url: str, starting_depth: int = 1) -> Dict[str, str]:
        """
        Crawls a website using Playwright and returns a dictionary of URLs and content.

        Args:
            url: The starting URL to begin the crawl
            starting_depth: The starting depth level for the crawl

        Returns:
            Dict[str, str]: A dictionary where each key is a URL and value is the content
        """
        num_links = 0
        crawler_result: Dict[str, str] = {}
        primary_domain = self._get_primary_domain(url)

        # Reset state for new crawl
        self._visited = set()
        self._urls_to_crawl = [(url, starting_depth)]

        with sync_playwright() as p:
            # Launch browser
            if self.browser_type == "chromium":
                browser = p.chromium.launch(**self._get_browser_launch_options())
            elif self.browser_type == "firefox":
                browser = p.firefox.launch(**self._get_browser_launch_options())
            else:  # webkit
                browser = p.webkit.launch(**self._get_browser_launch_options())

            try:
                context = browser.new_context(**self._get_context_options())
                page = context.new_page()
                page.set_default_timeout(self.timeout)

                while self._urls_to_crawl and num_links < self.max_links:
                    current_url, current_depth = self._urls_to_crawl.pop(0)

                    if (
                        current_url in self._visited
                        or not urlparse(current_url).netloc.endswith(primary_domain)
                        or current_depth > self.max_depth
                        or num_links >= self.max_links
                    ):
                        continue

                    self._visited.add(current_url)
                    self.delay()

                    try:
                        log_debug(f"Crawling with browser: {current_url}")

                        # Navigate to the page
                        page.goto(current_url)

                        # Wait for the specified load state
                        page.wait_for_load_state(self.wait_for_load_state)

                        # Additional wait time if specified
                        if self.extra_wait_time > 0:
                            time.sleep(self.extra_wait_time)

                        # Get page content
                        content = page.content()
                        soup = BeautifulSoup(content, "html.parser")

                        # Extract main content
                        main_content = self._extract_main_content(soup)
                        if main_content:
                            crawler_result[current_url] = main_content
                            num_links += 1

                        # Find links on the page
                        links = page.query_selector_all("a[href]")
                        for link in links:
                            href = link.get_attribute("href")
                            if href:
                                full_url = urljoin(current_url, href)
                                parsed_url = urlparse(full_url)

                                if parsed_url.netloc.endswith(primary_domain) and not any(
                                    parsed_url.path.endswith(ext)
                                    for ext in [
                                        ".pdf",
                                        ".jpg",
                                        ".png",
                                        ".gif",
                                        ".css",
                                        ".js",
                                    ]
                                ):
                                    if (
                                        full_url not in self._visited
                                        and (full_url, current_depth + 1) not in self._urls_to_crawl
                                    ):
                                        self._urls_to_crawl.append((full_url, current_depth + 1))

                    except Exception as e:
                        logger.warning(f"Failed to crawl {current_url}: {e}")
                        if current_url == url and not crawler_result:
                            raise RuntimeError(f"Failed to crawl starting URL {url}: {str(e)}") from e

            finally:
                browser.close()

        if not crawler_result:
            raise RuntimeError(f"Failed to extract any content from {url}")

        return crawler_result

    async def async_crawl(self, url: str, starting_depth: int = 1) -> Dict[str, str]:
        """
        Asynchronously crawls a website using Playwright.

        Args:
            url: The starting URL to begin the crawl
            starting_depth: The starting depth level for the crawl

        Returns:
            Dict[str, str]: A dictionary where each key is a URL and value is the content
        """
        num_links = 0
        crawler_result: Dict[str, str] = {}
        primary_domain = self._get_primary_domain(url)

        # Reset state for new crawl
        self._visited = set()
        self._urls_to_crawl = [(url, starting_depth)]

        async with async_playwright() as p:
            # Launch browser
            if self.browser_type == "chromium":
                browser = await p.chromium.launch(**self._get_browser_launch_options())
            elif self.browser_type == "firefox":
                browser = await p.firefox.launch(**self._get_browser_launch_options())
            else:  # webkit
                browser = await p.webkit.launch(**self._get_browser_launch_options())

            try:
                context = await browser.new_context(**self._get_context_options())
                page = await context.new_page()
                page.set_default_timeout(self.timeout)

                while self._urls_to_crawl and num_links < self.max_links:
                    current_url, current_depth = self._urls_to_crawl.pop(0)

                    if (
                        current_url in self._visited
                        or not urlparse(current_url).netloc.endswith(primary_domain)
                        or current_depth > self.max_depth
                        or num_links >= self.max_links
                    ):
                        continue

                    self._visited.add(current_url)
                    await self.async_delay()

                    try:
                        log_debug(f"Crawling asynchronously with browser: {current_url}")

                        # Navigate to the page
                        await page.goto(current_url)

                        # Wait for the specified load state
                        await page.wait_for_load_state(self.wait_for_load_state)

                        # Additional wait time if specified
                        if self.extra_wait_time > 0:
                            await asyncio.sleep(self.extra_wait_time)

                        # Get page content
                        content = await page.content()
                        soup = BeautifulSoup(content, "html.parser")

                        # Extract main content
                        main_content = self._extract_main_content(soup)
                        if main_content:
                            crawler_result[current_url] = main_content
                            num_links += 1

                        # Find links on the page
                        links = await page.query_selector_all("a[href]")
                        for link in links:
                            href = await link.get_attribute("href")
                            if href:
                                full_url = urljoin(current_url, href)
                                parsed_url = urlparse(full_url)

                                if parsed_url.netloc.endswith(primary_domain) and not any(
                                    parsed_url.path.endswith(ext)
                                    for ext in [
                                        ".pdf",
                                        ".jpg",
                                        ".png",
                                        ".gif",
                                        ".css",
                                        ".js",
                                    ]
                                ):
                                    if (
                                        full_url not in self._visited
                                        and (full_url, current_depth + 1) not in self._urls_to_crawl
                                    ):
                                        self._urls_to_crawl.append((full_url, current_depth + 1))

                    except Exception as e:
                        logger.warning(f"Failed to crawl asynchronously {current_url}: {e}")
                        if current_url == url and not crawler_result:
                            raise RuntimeError(f"Failed to crawl starting URL {url} asynchronously: {str(e)}") from e

            finally:
                await browser.close()

        if not crawler_result:
            raise RuntimeError(f"Failed to extract any content from {url} asynchronously")

        return crawler_result

    def read(self, url: str) -> List[Document]:
        """
        Reads a website using browser and returns a list of documents.

        Args:
            url: The URL of the website to read

        Returns:
            List[Document]: A list of documents containing the scraped content
        """
        log_debug(f"Reading with browser: {url}")
        try:
            crawler_result = self.crawl(url)
            documents = []
            for crawled_url, crawled_content in crawler_result.items():
                if self.chunk:
                    documents.extend(
                        self.chunk_document(
                            Document(
                                name=url,
                                id=str(crawled_url),
                                meta_data={
                                    "url": str(crawled_url),
                                    "reader_type": "browser",
                                },
                                content=crawled_content,
                            )
                        )
                    )
                else:
                    documents.append(
                        Document(
                            name=url,
                            id=str(crawled_url),
                            meta_data={
                                "url": str(crawled_url),
                                "reader_type": "browser",
                            },
                            content=crawled_content,
                        )
                    )
            return documents
        except Exception as e:
            logger.error(f"Error reading website with browser {url}: {e}")
            raise

    async def async_read(self, url: str) -> List[Document]:
        """
        Asynchronously reads a website using browser and returns a list of documents.

        Args:
            url: The URL of the website to read

        Returns:
            List[Document]: A list of documents containing the scraped content
        """
        log_debug(f"Reading asynchronously with browser: {url}")
        try:
            crawler_result = await self.async_crawl(url)
            documents = []

            # Process documents
            async def process_document(crawled_url, crawled_content):
                if self.chunk:
                    doc = Document(
                        name=url,
                        id=str(crawled_url),
                        meta_data={"url": str(crawled_url), "reader_type": "browser"},
                        content=crawled_content,
                    )
                    return self.chunk_document(doc)
                else:
                    return [
                        Document(
                            name=url,
                            id=str(crawled_url),
                            meta_data={
                                "url": str(crawled_url),
                                "reader_type": "browser",
                            },
                            content=crawled_content,
                        )
                    ]

            # Process all documents
            tasks = [
                process_document(crawled_url, crawled_content)
                for crawled_url, crawled_content in crawler_result.items()
            ]
            results = await asyncio.gather(*tasks)

            # Flatten the results
            for doc_list in results:
                documents.extend(doc_list)

            return documents
        except Exception as e:
            logger.error(f"Error reading website asynchronously with browser {url}: {e}")
            raise
