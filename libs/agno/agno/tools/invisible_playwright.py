"""InvisiblePlaywrightTools toolkit.

Firefox-based stealth browser toolkit, parallel to FirecrawlTools,
Crawl4aiTools, ScrapegraphTools. Wraps invisible_playwright, which drives
a patched Firefox 150 binary (feder-cr/invisible_firefox, MPL-2.0, same
license as Firefox upstream). Fingerprint patches at the C++ source code
level so there are no JS shims to detect.

Useful for sites where the existing Firecrawl, Crawl4ai, or Scrapegraph
toolkits hit Cloudflare, Akamai, Datadome, or hCaptcha walls.

Tracking discussion: #8128
Related open issues: #7943 (Playwright tool), #7104 (Cloudflare-bypass MCP),
#6997 (CloudflareBrowserRenderingTools).
"""

import json
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    from invisible_playwright import InvisiblePlaywright
    from invisible_playwright.async_api import InvisiblePlaywright as AsyncInvisiblePlaywright
except ImportError:
    raise ImportError(
        "`invisible_playwright` not installed. "
        "Install with `pip install invisible_playwright` and run "
        "`python -m invisible_playwright fetch` to download the patched Firefox binary."
    )


class InvisiblePlaywrightTools(Toolkit):
    """Firefox-based stealth browser toolkit.

    Args:
        enable_scrape: Enable single-page scrape. Default True.
        enable_crawl: Enable multi-page crawl within a domain. Default False.
        enable_search: Enable search engine query. Default False.
        all: Enable all tools. Overrides individual flags. Default False.
        seed: Integer seed for deterministic fingerprint across runs.
            Same seed produces identical fingerprint.
        headless: When True, render on a hidden virtual display so the
            browser stays in real headed mode without showing windows.
            Default True.
        proxy: Proxy dict ({"server": "...", "username": "...", "password": "..."}).
        locale: BCP-47 locale tag (e.g. "en-US"). Default "en-US".
        timezone: IANA timezone (e.g. "America/New_York"). Empty means host tz.
        max_pages: Default cap on pages per crawl. Default 10.
        max_depth: Default link-depth cap for crawl. Default 2.
        search_engine: Default search engine for search_web ("duckduckgo" or "bing").
            Default "duckduckgo" (no captcha pre-screen on the HTML endpoint).
        num_results: Default number of search results returned. Default 5.
        max_length: Truncate scrape/crawl output beyond this length. Default 5000.
            Set to None to disable truncation.
    """

    def __init__(
        self,
        enable_scrape: bool = True,
        enable_crawl: bool = False,
        enable_search: bool = False,
        all: bool = False,
        seed: Optional[int] = None,
        headless: bool = True,
        proxy: Optional[Dict[str, str]] = None,
        locale: str = "en-US",
        timezone: str = "",
        max_pages: int = 10,
        max_depth: int = 2,
        search_engine: str = "duckduckgo",
        num_results: int = 5,
        max_length: Optional[int] = 5000,
        **kwargs,
    ):
        tools: List[Any] = []
        async_tools: List[Any] = []
        if all or enable_scrape:
            tools.append(self.scrape_url)
            async_tools.append((self.ascrape_url, "scrape_url"))
        if all or enable_crawl:
            tools.append(self.crawl_site)
            async_tools.append((self.acrawl_site, "crawl_site"))
        if all or enable_search:
            tools.append(self.search_web)
            async_tools.append((self.asearch_web, "search_web"))

        super().__init__(
            name="invisible_playwright_tools",
            tools=tools,
            async_tools=async_tools,
            **kwargs,
        )

        self._seed = seed
        self._headless = headless
        self._proxy = proxy
        self._locale = locale
        self._timezone = timezone
        self._max_pages = max_pages
        self._max_depth = max_depth
        self._search_engine = search_engine.lower()
        self._num_results = num_results
        self._max_length = max_length

    def _launch(self) -> InvisiblePlaywright:
        """Build a fresh sync InvisiblePlaywright context manager."""
        return InvisiblePlaywright(
            seed=self._seed,
            headless=self._headless,
            proxy=self._proxy,
            locale=self._locale,
            timezone=self._timezone,
        )

    def _alaunch(self) -> AsyncInvisiblePlaywright:
        """Build a fresh async InvisiblePlaywright context manager."""
        return AsyncInvisiblePlaywright(
            seed=self._seed,
            headless=self._headless,
            proxy=self._proxy,
            locale=self._locale,
            timezone=self._timezone,
        )

    def _truncate(self, text: str) -> str:
        if self._max_length and len(text) > self._max_length:
            return text[: self._max_length] + "..."
        return text

    @staticmethod
    def _collect_results(
        page,
        result_selector: str,
        title_selector: str,
        snippet_selector: str,
        limit: int,
    ) -> List[Dict[str, str]]:
        """Extract search result items via sync Playwright element methods only.

        Avoids in-page eval so CSP-restricted SERPs (DuckDuckGo, others)
        don't reject the extraction.
        """
        items: List[Dict[str, str]] = []
        for el in page.query_selector_all(result_selector)[:limit]:
            title_el = el.query_selector(title_selector)
            snippet_el = el.query_selector(snippet_selector)
            items.append(
                {
                    "title": (title_el.inner_text() if title_el else "").strip(),
                    "url": (title_el.get_attribute("href") if title_el else "") or "",
                    "snippet": (snippet_el.inner_text() if snippet_el else "").strip(),
                }
            )
        return items

    @staticmethod
    async def _acollect_results(
        page,
        result_selector: str,
        title_selector: str,
        snippet_selector: str,
        limit: int,
    ) -> List[Dict[str, str]]:
        """Async variant of _collect_results. Same CSP-safe element-walk pattern."""
        items: List[Dict[str, str]] = []
        elements = await page.query_selector_all(result_selector)
        for el in elements[:limit]:
            title_el = await el.query_selector(title_selector)
            snippet_el = await el.query_selector(snippet_selector)
            title_text = (await title_el.inner_text()) if title_el else ""
            url = (await title_el.get_attribute("href")) if title_el else ""
            snippet_text = (await snippet_el.inner_text()) if snippet_el else ""
            items.append(
                {
                    "title": title_text.strip(),
                    "url": url or "",
                    "snippet": snippet_text.strip(),
                }
            )
        return items

    def scrape_url(self, url: str, wait_for_selector: Optional[str] = None) -> str:
        """Fetch the rendered HTML of a URL using a patched stealth Firefox.

        Use when sites behind Cloudflare, Akamai, Datadome, or hCaptcha return
        empty content or 403 from the standard Firecrawl/Crawl4ai/Scrapegraph
        toolkits.

        Args:
            url: The URL to fetch.
            wait_for_selector: Optional CSS selector to wait for before
                returning. Useful for JS-rendered pages.

        Returns:
            The page HTML, truncated to max_length if set.
        """
        if not url:
            return "Error: No URL provided"
        try:
            with self._launch() as browser:
                page = browser.new_page()
                page.goto(url)
                if wait_for_selector:
                    page.wait_for_selector(wait_for_selector)
                content = page.content()
                return self._truncate(content)
        except Exception as e:
            log_error(f"InvisiblePlaywrightTools.scrape_url failed for {url}: {e}")
            return f"Error fetching {url}: {e}"

    def crawl_site(
        self,
        url: str,
        max_pages: Optional[int] = None,
        max_depth: Optional[int] = None,
    ) -> str:
        """Crawl multiple pages from a starting URL, staying within the same domain.

        Breadth-first traversal capped by max_pages and max_depth. Reuses one
        browser session across all pages for efficiency.

        Args:
            url: The starting URL.
            max_pages: Override default page cap.
            max_depth: Override default depth cap.

        Returns:
            JSON object mapping each visited URL to its truncated HTML.
        """
        if not url:
            return "Error: No URL provided"
        page_cap = max_pages or self._max_pages
        depth_cap = max_depth or self._max_depth
        origin = urlparse(url).netloc
        seen: set = {url}
        results: Dict[str, str] = {}
        queue: List = [(url, 0)]
        try:
            with self._launch() as browser:
                page = browser.new_page()
                while queue and len(results) < page_cap:
                    current, depth = queue.pop(0)
                    try:
                        page.goto(current)
                        html = page.content()
                        results[current] = self._truncate(html)
                        log_debug(f"crawl_site: visited {current} ({len(results)}/{page_cap})")
                    except Exception as inner:
                        results[current] = f"Error: {inner}"
                        continue
                    if depth >= depth_cap:
                        continue
                    # query_selector_all + get_attribute avoids in-page eval() which
                    # some sites block via CSP (e.g. DuckDuckGo).
                    anchors = page.query_selector_all("a[href]")
                    for anchor in anchors:
                        href = anchor.get_attribute("href") or ""
                        if not href:
                            continue
                        # resolve relative links against the current page url
                        if href.startswith(("/", "?", "#")):
                            href = urljoin(current, href)
                        if href in seen:
                            continue
                        if urlparse(href).netloc != origin:
                            continue
                        seen.add(href)
                        queue.append((href, depth + 1))
            return json.dumps(results)
        except Exception as e:
            log_error(f"InvisiblePlaywrightTools.crawl_site failed for {url}: {e}")
            return f"Error crawling {url}: {e}"

    def search_web(self, query: str, num_results: Optional[int] = None) -> str:
        """Run a search engine query through stealth Firefox and return results.

        Defaults to DuckDuckGo HTML endpoint (no captcha pre-screen). Other
        supported engine: "bing". Google is intentionally not supported because
        the SERP HTML is volatile and captcha-walled even for real users.

        Args:
            query: The search query.
            num_results: Override default result count.

        Returns:
            JSON list of result objects with `title`, `url`, `snippet` fields.
        """
        if not query:
            return "Error: No query provided"
        n = num_results or self._num_results
        engine = self._search_engine
        try:
            with self._launch() as browser:
                page = browser.new_page()
                if engine == "duckduckgo":
                    page.goto(f"https://duckduckgo.com/html/?q={query}")
                    page.wait_for_selector(".result__title a", timeout=10000)
                    items = self._collect_results(
                        page,
                        result_selector=".result",
                        title_selector=".result__title a",
                        snippet_selector=".result__snippet",
                        limit=n,
                    )
                elif engine == "bing":
                    page.goto(f"https://www.bing.com/search?q={query}")
                    page.wait_for_selector("li.b_algo", timeout=10000)
                    items = self._collect_results(
                        page,
                        result_selector="li.b_algo",
                        title_selector="h2 a",
                        snippet_selector=".b_caption p",
                        limit=n,
                    )
                else:
                    return f"Error: unsupported search engine '{engine}'. Use 'duckduckgo' or 'bing'."
                return json.dumps(items)
        except Exception as e:
            log_error(f"InvisiblePlaywrightTools.search_web failed for {query!r}: {e}")
            return f"Error searching for {query!r}: {e}"

    # ------------------------------------------------------------------ #
    # Async surface (mirrors the sync methods above 1:1).                #
    # Pattern modelled on BrowserbaseTools (a-prefixed parallel methods) #
    # per maintainer guidance on PR #8129.                               #
    # ------------------------------------------------------------------ #

    async def ascrape_url(self, url: str, wait_for_selector: Optional[str] = None) -> str:
        """Async: fetch the rendered HTML of a URL using a patched stealth Firefox.

        See scrape_url for behaviour. Use this from async agents / asyncio
        event loops where the sync variant would block.

        Args:
            url: The URL to fetch.
            wait_for_selector: Optional CSS selector to wait for before
                returning. Useful for JS-rendered pages.

        Returns:
            The page HTML, truncated to max_length if set.
        """
        if not url:
            return "Error: No URL provided"
        try:
            async with self._alaunch() as browser:
                page = await browser.new_page()
                await page.goto(url)
                if wait_for_selector:
                    await page.wait_for_selector(wait_for_selector)
                content = await page.content()
                return self._truncate(content)
        except Exception as e:
            log_error(f"InvisiblePlaywrightTools.ascrape_url failed for {url}: {e}")
            return f"Error fetching {url}: {e}"

    async def acrawl_site(
        self,
        url: str,
        max_pages: Optional[int] = None,
        max_depth: Optional[int] = None,
    ) -> str:
        """Async: crawl multiple pages from a starting URL, staying within the same domain.

        See crawl_site for behaviour.

        Args:
            url: The starting URL.
            max_pages: Override default page cap.
            max_depth: Override default depth cap.

        Returns:
            JSON object mapping each visited URL to its truncated HTML.
        """
        if not url:
            return "Error: No URL provided"
        page_cap = max_pages or self._max_pages
        depth_cap = max_depth or self._max_depth
        origin = urlparse(url).netloc
        seen: set = {url}
        results: Dict[str, str] = {}
        queue: List = [(url, 0)]
        try:
            async with self._alaunch() as browser:
                page = await browser.new_page()
                while queue and len(results) < page_cap:
                    current, depth = queue.pop(0)
                    try:
                        await page.goto(current)
                        html = await page.content()
                        results[current] = self._truncate(html)
                        log_debug(f"acrawl_site: visited {current} ({len(results)}/{page_cap})")
                    except Exception as inner:
                        results[current] = f"Error: {inner}"
                        continue
                    if depth >= depth_cap:
                        continue
                    anchors = await page.query_selector_all("a[href]")
                    for anchor in anchors:
                        href = (await anchor.get_attribute("href")) or ""
                        if not href:
                            continue
                        if href.startswith(("/", "?", "#")):
                            href = urljoin(current, href)
                        if href in seen:
                            continue
                        if urlparse(href).netloc != origin:
                            continue
                        seen.add(href)
                        queue.append((href, depth + 1))
            return json.dumps(results)
        except Exception as e:
            log_error(f"InvisiblePlaywrightTools.acrawl_site failed for {url}: {e}")
            return f"Error crawling {url}: {e}"

    async def asearch_web(self, query: str, num_results: Optional[int] = None) -> str:
        """Async: run a search engine query through stealth Firefox and return results.

        See search_web for behaviour.

        Args:
            query: The search query.
            num_results: Override default result count.

        Returns:
            JSON list of result objects with `title`, `url`, `snippet` fields.
        """
        if not query:
            return "Error: No query provided"
        n = num_results or self._num_results
        engine = self._search_engine
        try:
            async with self._alaunch() as browser:
                page = await browser.new_page()
                if engine == "duckduckgo":
                    await page.goto(f"https://duckduckgo.com/html/?q={query}")
                    await page.wait_for_selector(".result__title a", timeout=10000)
                    items = await self._acollect_results(
                        page,
                        result_selector=".result",
                        title_selector=".result__title a",
                        snippet_selector=".result__snippet",
                        limit=n,
                    )
                elif engine == "bing":
                    await page.goto(f"https://www.bing.com/search?q={query}")
                    await page.wait_for_selector("li.b_algo", timeout=10000)
                    items = await self._acollect_results(
                        page,
                        result_selector="li.b_algo",
                        title_selector="h2 a",
                        snippet_selector=".b_caption p",
                        limit=n,
                    )
                else:
                    return f"Error: unsupported search engine '{engine}'. Use 'duckduckgo' or 'bing'."
                return json.dumps(items)
        except Exception as e:
            log_error(f"InvisiblePlaywrightTools.asearch_web failed for {query!r}: {e}")
            return f"Error searching for {query!r}: {e}"
