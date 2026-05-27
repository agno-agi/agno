"""InvisiblePlaywrightTools toolkit.

Optional Firefox-based stealth browser toolkit, parallel to FirecrawlTools,
Crawl4aiTools, ScrapegraphTools. Selected by the user when constructing the
agent. Optional dependency.

Tracking discussion: TBD
Related open issues: #7943 (Playwright tool), #7104 (Cloudflare-bypass MCP),
#6997 (CloudflareBrowserRenderingTools).
"""

from typing import Optional

from agno.tools import Toolkit
from agno.utils.log import log_error

try:
    from invisible_playwright import InvisiblePlaywright
except ImportError:
    raise ImportError(
        "`invisible_playwright` not installed. "
        "Install with `pip install invisible_playwright` and run "
        "`python -m invisible_playwright fetch` to download the patched Firefox binary."
    )


class InvisiblePlaywrightTools(Toolkit):
    """Firefox-based stealth browser toolkit.

    Wraps `invisible_playwright`, which drives a patched Firefox 150 binary
    (feder-cr/invisible_firefox, MPL-2.0, same license as Firefox upstream).
    Fingerprint patches at the C++ source code level so there are no JS
    shims to detect. Useful for sites where the existing Firecrawl, Crawl4ai
    or Scrapegraph toolkits hit Cloudflare, Akamai, Datadome, or hCaptcha
    walls.

    Args:
        seed: Optional integer seed for deterministic fingerprint across runs.
        headless: When True, render on a hidden virtual display so the browser
            stays in real headed mode (coherent fingerprint) without showing
            windows. Default True.
        proxy: Optional proxy dict ({"server": "...", "username": "...",
            "password": "..."}).
    """

    def __init__(
        self,
        seed: Optional[int] = None,
        headless: bool = True,
        proxy: Optional[dict] = None,
        **kwargs,
    ):
        super().__init__(name="invisible_playwright_tools", **kwargs)
        self._seed = seed
        self._headless = headless
        self._proxy = proxy
        self.register(self.fetch_page)

    def fetch_page(self, url: str, wait_for_selector: Optional[str] = None) -> str:
        """Fetch the rendered HTML of a URL using a patched stealth Firefox.

        Args:
            url: The URL to fetch.
            wait_for_selector: Optional CSS selector to wait for before
                returning. Useful for JS-rendered pages.

        Returns:
            The page HTML, or an error string if the fetch failed.
        """
        try:
            with InvisiblePlaywright(
                seed=self._seed,
                headless=self._headless,
                proxy=self._proxy,
            ) as browser:
                page = browser.new_page()
                page.goto(url)
                if wait_for_selector:
                    page.wait_for_selector(wait_for_selector)
                return page.content()
        except Exception as e:
            log_error(f"InvisiblePlaywrightTools.fetch_page failed: {e}")
            return f"Error fetching {url}: {e}"
