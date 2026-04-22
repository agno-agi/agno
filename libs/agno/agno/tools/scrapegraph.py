"""
ScrapeGraphTools — web scraping, extraction, search, and crawl via the ScrapeGraphAI API.

Prerequisites:
- Create a ScrapeGraphAI account and get an API key at https://scrapegraphai.com
- Set the API key as an environment variable:
    export SGAI_API_KEY=<your-api-key>

Tools:
- smartscraper: one-page structured extraction via an AI prompt
- markdownify: one-page URL -> markdown text
- scrape: one-page URL -> raw HTML
- searchscraper: web search + content extraction across top results
- crawl: multi-page extraction with a JSON schema (polls until complete)
"""

import json
import time
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

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


class ScrapeGraphTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_smartscraper: bool = True,
        enable_markdownify: bool = False,
        enable_searchscraper: bool = False,
        enable_crawl: bool = False,
        enable_scrape: bool = False,
        render_heavy_js: bool = False,
        headers: Optional[Dict[str, str]] = None,
        crawl_poll_interval: int = 3,
        crawl_max_wait: int = 180,
        all: bool = False,
        **kwargs,
    ):
        """Initialize ScrapeGraphTools and authenticate with the ScrapeGraphAI API.

        Args:
            api_key (Optional[str]): ScrapeGraphAI API key. Defaults to env var SGAI_API_KEY.
            enable_smartscraper (bool): Enable structured extraction via an AI prompt. Defaults to True.
            enable_markdownify (bool): Enable URL -> markdown conversion. Defaults to False.
            enable_searchscraper (bool): Enable web search with content extraction. Defaults to False.
            enable_crawl (bool): Enable multi-page crawl with structured extraction. Defaults to False.
            enable_scrape (bool): Enable raw HTML scraping. Defaults to False.
            render_heavy_js (bool): Request JavaScript rendering on every call. Defaults to False.
            headers (Optional[Dict[str, str]]): Custom HTTP headers to send with every outbound fetch (e.g. User-Agent, Cookie, Authorization). Applied to every tool call when set. Defaults to None.
            crawl_poll_interval (int): Seconds between crawl status polls. Defaults to 3. Raise this for very large crawls.
            crawl_max_wait (int): Max seconds to wait for a crawl to complete. Defaults to 180. Raise this if your crawls legitimately take longer.
            all (bool): Enable all tools. Defaults to False.
        """
        self.api_key: Optional[str] = api_key or getenv("SGAI_API_KEY")
        if not self.api_key:
            log_error("SGAI_API_KEY not set. Please set the SGAI_API_KEY environment variable.")

        self.client: ScrapeGraphAI = ScrapeGraphAI(api_key=self.api_key)
        self.render_heavy_js: bool = render_heavy_js
        self.headers: Optional[Dict[str, str]] = headers
        self.crawl_poll_interval: int = crawl_poll_interval
        self.crawl_max_wait: int = crawl_max_wait

        tools: List[Any] = []
        if all or enable_smartscraper:
            tools.append(self.smartscraper)
        if all or enable_markdownify:
            tools.append(self.markdownify)
        if all or enable_searchscraper:
            tools.append(self.searchscraper)
        if all or enable_crawl:
            tools.append(self.crawl)
        if all or enable_scrape:
            tools.append(self.scrape)

        super().__init__(name="scrapegraph_tools", tools=tools, **kwargs)

    def _fetch_config(self) -> Optional[FetchConfig]:
        config_kwargs: Dict[str, Any] = {}
        if self.render_heavy_js:
            config_kwargs["mode"] = "js"
        if self.headers:
            config_kwargs["headers"] = self.headers
        return FetchConfig(**config_kwargs) if config_kwargs else None

    def smartscraper(self, url: str, prompt: str) -> str:
        """Extract structured data from a webpage using an AI prompt.

        Args:
            url (str): The URL to scrape.
            prompt (str): Natural language prompt describing what to extract.

        Returns:
            str: JSON string with the extracted data, or an error message.
        """
        try:
            log_debug(f"ScrapeGraph smartscraper request for URL: {url}")
            response = self.client.extract(prompt=prompt, url=url, fetch_config=self._fetch_config())
            if response.status != "success" or response.data is None:
                return f"Error extracting from {url}: {response.error or 'unknown error'}"
            payload = response.data.json_data if response.data.json_data is not None else response.data.raw
            return json.dumps(payload)
        except Exception as error:
            return f"Error extracting from {url}: {type(error).__name__}: {error}"

    def markdownify(self, url: str) -> str:
        """Convert a webpage to markdown.

        Args:
            url (str): The URL to convert.

        Returns:
            str: The markdown content of the webpage, or an error message.
        """
        try:
            log_debug(f"ScrapeGraph markdownify request for URL: {url}")
            response = self.client.scrape(
                url,
                formats=[MarkdownFormatConfig()],
                fetch_config=self._fetch_config(),
            )
            if response.status != "success" or response.data is None:
                return f"Error converting {url} to markdown: {response.error or 'unknown error'}"
            markdown_field = response.data.results.get("markdown", {})
            if isinstance(markdown_field, dict):
                return str(markdown_field.get("data", ""))
            return str(markdown_field)
        except Exception as error:
            return f"Error converting {url} to markdown: {type(error).__name__}: {error}"

    def searchscraper(self, query: str) -> str:
        """Search the web and extract information from the top results.

        Args:
            query (str): The search query.

        Returns:
            str: JSON string with the search results, or an error message.
        """
        try:
            log_debug(f"ScrapeGraph searchscraper request (query_length={len(query)})")
            response = self.client.search(query, fetch_config=self._fetch_config())
            if response.status != "success" or response.data is None:
                return f"Error searching: {response.error or 'unknown error'}"
            return response.data.model_dump_json(by_alias=True)
        except Exception as error:
            return f"Error searching: {type(error).__name__}: {error}"

    def crawl(
        self,
        url: str,
        prompt: str,
        schema: Dict[str, Any],
        max_depth: int = 2,
        max_pages: int = 2,
    ) -> str:
        """Crawl a website and extract structured data across multiple pages.

        Starts a crawl job upstream and polls until it completes or `crawl_max_wait` elapses.

        Args:
            url (str): The URL to crawl.
            prompt (str): Natural language prompt describing what to extract.
            schema (Dict[str, Any]): JSON schema for extraction.
            max_depth (int): Max crawl depth. Defaults to 2.
            max_pages (int): Max number of pages to crawl. Defaults to 2.

        Returns:
            str: JSON string with the crawl result, or an error message.
        """
        try:
            log_debug(f"ScrapeGraph crawl start for URL: {url}")
            start_response = self.client.crawl.start(
                url,
                formats=[JsonFormatConfig(prompt=prompt, schema=schema)],
                max_depth=max_depth,
                max_pages=max_pages,
                fetch_config=self._fetch_config(),
            )
            if start_response.status != "success" or start_response.data is None:
                return f"Error starting crawl of {url}: {start_response.error or 'unknown error'}"

            crawl_data = start_response.data
            crawl_id = crawl_data.id
            deadline = time.monotonic() + self.crawl_max_wait
            while crawl_data.status == "running":
                if time.monotonic() > deadline:
                    return f"Error: crawl timed out after {self.crawl_max_wait}s (id={crawl_id})"
                time.sleep(self.crawl_poll_interval)
                status_response = self.client.crawl.get(crawl_id)
                if status_response.status != "success" or status_response.data is None:
                    return f"Error polling crawl {crawl_id}: {status_response.error or 'unknown error'}"
                crawl_data = status_response.data

            return crawl_data.model_dump_json(by_alias=True)
        except Exception as error:
            return f"Error crawling {url}: {type(error).__name__}: {error}"

    def scrape(self, url: str) -> str:
        """Get raw HTML content from a webpage.

        Args:
            url (str): The URL to scrape.

        Returns:
            str: JSON string with the scrape result, or an error message.
        """
        try:
            log_debug(f"ScrapeGraph scrape request for URL: {url}")
            response = self.client.scrape(
                url,
                formats=[HtmlFormatConfig()],
                fetch_config=self._fetch_config(),
            )
            if response.status != "success" or response.data is None:
                return f"Error scraping {url}: {response.error or 'unknown error'}"
            return response.data.model_dump_json(by_alias=True)
        except Exception as error:
            return f"Error scraping {url}: {type(error).__name__}: {error}"
