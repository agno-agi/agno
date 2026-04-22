"""ScrapeGraphTools — web scraping, extraction, search, and crawl via the ScrapeGraphAI API.

Setup:
    pip install scrapegraph-py
    export SGAI_API_KEY=<your key>

Get an API key at: https://scrapegraphai.com

Tools:
    - smartscraper: one page -> structured JSON extracted via a prompt
    - markdownify: one page -> markdown text
    - scrape: one page -> raw HTML
    - searchscraper: web search + content extraction across top results
    - crawl: multi-page extraction with a JSON schema (polls until completion)
"""

import json
import time
import warnings
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from scrapegraph_py import (
        FetchConfig,
        HtmlFormatConfig,
        JsonFormatConfig,
        MarkdownFormatConfig,
        ScrapeGraphAI,
    )
except ImportError:
    raise ImportError("`scrapegraph-py` not installed. Please install using `pip install scrapegraph-py`")

# Upstream crawl is an async job: start() returns immediately with status="running";
# real pages are available only after polling get(id) to completion.
_CRAWL_MAX_WAIT_SECONDS = 180
_CRAWL_POLL_INTERVAL_SECONDS = 3

# v1 params removed in scrapegraph-py v2 rewrite; swallow with a DeprecationWarning
# so existing user code doesn't TypeError on upgrade.
_REMOVED_INIT_PARAMS = frozenset({"enable_agentic_crawler"})
_REMOVED_CRAWL_PARAMS = frozenset({"cache_website", "same_domain_only", "batch_size", "use_session"})


def _unwrap(result: Any) -> Any:
    """Return result.data on success; raise RuntimeError with result.error otherwise."""
    if getattr(result, "status", None) == "success" and result.data is not None:
        return result.data
    raise RuntimeError(getattr(result, "error", None) or "ScrapeGraphAI request failed")


class ScrapeGraphTools(Toolkit):
    """Tools for web scraping, extraction, search, and crawl via the ScrapeGraphAI API.

    Args:
        api_key: ScrapeGraphAI API key. Defaults to env var `SGAI_API_KEY`.
        enable_smartscraper: Register `smartscraper` (structured extraction via prompt). Defaults to True.
        enable_markdownify: Register `markdownify` (URL -> markdown). Defaults to False.
        enable_crawl: Register `crawl` (multi-page extraction with schema). Defaults to False.
        enable_searchscraper: Register `searchscraper` (web search + extraction). Defaults to False.
        enable_scrape: Register `scrape` (URL -> raw HTML). Defaults to False.
        render_heavy_js: Use JavaScript rendering mode for every request. Defaults to False.
        all: Register all five tools. Defaults to False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_smartscraper: bool = True,
        enable_markdownify: bool = False,
        enable_crawl: bool = False,
        enable_searchscraper: bool = False,
        enable_scrape: bool = False,
        render_heavy_js: bool = False,
        all: bool = False,
        **kwargs,
    ):
        for removed in _REMOVED_INIT_PARAMS:
            if kwargs.pop(removed, None) is not None:
                warnings.warn(
                    f"`{removed}` was removed in scrapegraph-py v2 (the agentic_crawler "
                    "endpoint no longer exists). Ignoring.",
                    DeprecationWarning,
                    stacklevel=2,
                )

        self.api_key: Optional[str] = api_key or getenv("SGAI_API_KEY")
        self.client = ScrapeGraphAI(api_key=self.api_key)
        self.render_heavy_js = render_heavy_js

        # If the caller disabled smartscraper without enabling any other tool,
        # fall back to markdownify so the toolkit always exposes at least one tool.
        if not any([enable_smartscraper, enable_markdownify, enable_crawl, enable_searchscraper, enable_scrape, all]):
            enable_markdownify = True

        tools: List[Any] = []
        if enable_smartscraper or all:
            tools.append(self.smartscraper)
        if enable_markdownify or all:
            tools.append(self.markdownify)
        if enable_crawl or all:
            tools.append(self.crawl)
        if enable_searchscraper or all:
            tools.append(self.searchscraper)
        if enable_scrape or all:
            tools.append(self.scrape)

        tool_names = [t.__name__ for t in tools]
        built_instructions = self._build_instructions(tool_names)
        if built_instructions:
            kwargs.setdefault("instructions", built_instructions)
            kwargs.setdefault("add_instructions", True)

        super().__init__(name="scrapegraph_tools", tools=tools, **kwargs)

    @staticmethod
    def _build_instructions(tool_names: List[str]) -> str:
        enabled = set(tool_names)
        sections: List[str] = []

        if "smartscraper" in enabled:
            sections.append(
                "**smartscraper** — one page, structured output. Pass a URL and a natural-language "
                "extraction prompt; returns JSON shaped by the prompt."
            )
        if "markdownify" in enabled:
            sections.append(
                "**markdownify** — one page, converted to markdown. Use when you need the page text "
                "for reading or downstream summarisation."
            )
        if "scrape" in enabled:
            sections.append("**scrape** — one page, raw HTML. Use when you need the source markup (not the text).")
        if "searchscraper" in enabled:
            sections.append("**searchscraper** — web search with automatic content extraction across the top results.")
        if "crawl" in enabled:
            sections.append(
                "**crawl** — multi-page extraction with a JSON schema. Expect up to ~3 minutes for larger "
                "jobs (the tool polls the crawl job until it finishes)."
            )

        overlapping = {"smartscraper", "markdownify", "scrape"} & enabled
        if len(overlapping) >= 2:
            sections.append(
                "When you have one URL and need structured fields → `smartscraper`. "
                "When you need the page's prose → `markdownify`. "
                "When you need the raw HTML markup → `scrape`."
            )

        if len(sections) < 2:
            return ""
        return "## ScrapeGraph tool selection\n\n" + "\n\n".join(sections)

    def _fetch_config(self) -> Optional[FetchConfig]:
        if self.render_heavy_js:
            return FetchConfig(mode="js")
        return None

    def smartscraper(self, url: str, prompt: str) -> str:
        """Extract structured data from a webpage using AI.

        Args:
            url: The URL to scrape.
            prompt: Natural language prompt describing what to extract.

        Returns:
            JSON string with the extracted structured data, or an `error` key on failure.
        """
        try:
            log_debug(f"ScrapeGraph smartscraper (extract) request for URL: {url}")
            response = self.client.extract(
                prompt=prompt,
                url=url,
                fetch_config=self._fetch_config(),
            )
            extracted = _unwrap(response)
            extracted_payload = extracted.json_data if extracted.json_data is not None else extracted.raw
            return json.dumps(extracted_payload)
        except Exception as e:
            logger.exception(f"Smartscraper failed for {url}")
            return json.dumps({"error": str(e)})

    def markdownify(self, url: str) -> str:
        """Convert a webpage to markdown format.

        Args:
            url: The URL to convert.

        Returns:
            JSON string with `markdown` and `url` keys, or an `error` key on failure.
        """
        try:
            log_debug(f"ScrapeGraph markdownify request for URL: {url}")
            response = self.client.scrape(
                url,
                formats=[MarkdownFormatConfig()],
                fetch_config=self._fetch_config(),
            )
            scraped = _unwrap(response)
            # Contract: {"results": {"markdown": {"data": "..."}}}. Defensive:
            # also accept the legacy shape where "markdown" is a bare string or
            # a list of chunks so a minor upstream change doesn't crash us.
            markdown_field = scraped.results.get("markdown", {})
            if isinstance(markdown_field, dict):
                markdown_text = markdown_field.get("data", "")
            else:
                markdown_text = markdown_field
            if isinstance(markdown_text, list):
                markdown_text = "\n\n".join(str(chunk) for chunk in markdown_text)
            return json.dumps({"markdown": str(markdown_text), "url": url})
        except Exception as e:
            logger.exception(f"Markdownify failed for {url}")
            return json.dumps({"error": str(e)})

    def crawl(
        self,
        url: str,
        prompt: str,
        schema: dict,
        depth: int = 2,
        max_pages: int = 2,
        **kwargs,
    ) -> str:
        """Crawl a website and extract structured data.

        Starts a crawl job upstream and polls `crawl.get(id)` until the job completes
        or the deadline (~3 minutes) is reached.

        Args:
            url: The URL to crawl.
            prompt: Natural language prompt describing what to extract.
            schema: JSON schema for extraction.
            depth: Max crawl depth.
            max_pages: Max number of pages to crawl.

        Returns:
            JSON string with the completed crawl response (pages + extracted data),
            or an `error` key on failure or timeout.
        """
        # v1 kwargs (cache_website, same_domain_only, batch_size, use_session) are no
        # longer supported; silently ignore them with a one-time DeprecationWarning so
        # pre-v2 user code doesn't TypeError on upgrade.
        removed = set(kwargs) & _REMOVED_CRAWL_PARAMS
        if removed:
            warnings.warn(
                f"crawl() kwargs {sorted(removed)} were removed in scrapegraph-py v2. Ignoring.",
                DeprecationWarning,
                stacklevel=2,
            )

        try:
            log_debug(f"ScrapeGraph crawl start for URL: {url}")
            start_response = self.client.crawl.start(
                url,
                formats=[JsonFormatConfig(prompt=prompt, schema=schema)],
                max_depth=depth,
                max_pages=max_pages,
                fetch_config=self._fetch_config(),
            )
            crawl_data = _unwrap(start_response)
            crawl_id = crawl_data.id
            status = crawl_data.status

            deadline = time.monotonic() + _CRAWL_MAX_WAIT_SECONDS
            while status == "running":
                if time.monotonic() > deadline:
                    return json.dumps(
                        {
                            "error": f"Crawl timed out after {_CRAWL_MAX_WAIT_SECONDS}s",
                            "crawl_id": crawl_id,
                        }
                    )
                time.sleep(_CRAWL_POLL_INTERVAL_SECONDS)
                status_response = self.client.crawl.get(crawl_id)
                crawl_data = _unwrap(status_response)
                status = crawl_data.status

            return crawl_data.model_dump_json(by_alias=True)
        except Exception as e:
            logger.exception(f"Crawl failed for {url}")
            return json.dumps({"error": str(e)})

    def searchscraper(self, user_prompt: str) -> str:
        """Search the web and extract information from the top results.

        Args:
            user_prompt: Search query.

        Returns:
            JSON string with the search results, or an `error` key on failure.
        """
        try:
            # Log the query length rather than its content — search queries can
            # carry sensitive user context.
            log_debug(f"ScrapeGraph searchscraper request (query_length={len(user_prompt)})")
            response = self.client.search(user_prompt)
            search_data = _unwrap(response)
            return search_data.model_dump_json(by_alias=True)
        except Exception as e:
            logger.exception("Searchscraper failed")
            return json.dumps({"error": str(e)})

    def scrape(
        self,
        website_url: str,
        headers: Optional[dict] = None,
    ) -> str:
        """Get raw HTML content from a webpage.

        Args:
            website_url: The URL to scrape.
            headers: Optional HTTP headers to send with the request.

        Returns:
            JSON string with the HTML content and metadata, or an `error` key on failure.
        """
        try:
            log_debug(f"ScrapeGraph scrape request for URL: {website_url}")
            # Build fetch_config fresh so render_heavy_js and headers combine
            # cleanly — avoids reconstructing a FetchConfig only to overwrite it.
            fetch_config_kwargs: dict = {}
            if self.render_heavy_js:
                fetch_config_kwargs["mode"] = "js"
            if headers:
                fetch_config_kwargs["headers"] = headers
            fetch_config = FetchConfig(**fetch_config_kwargs) if fetch_config_kwargs else None

            response = self.client.scrape(
                website_url,
                formats=[HtmlFormatConfig()],
                fetch_config=fetch_config,
            )
            scraped = _unwrap(response)
            return scraped.model_dump_json(by_alias=True)
        except Exception as e:
            logger.exception(f"Scrape failed for {website_url}")
            return json.dumps({"error": str(e)})
