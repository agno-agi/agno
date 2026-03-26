"""CRW Tools — High-performance web scraper toolkit for Agno agents.

CRW is a Firecrawl-compatible web scraper optimized for AI agents.
Single binary, ~6 MB idle RAM, 5.5x faster than Firecrawl.

Works with both self-hosted CRW and fastcrw.com cloud.
No external SDK needed — uses httpx (already an Agno dependency).

Usage:
    from agno.agent import Agent
    from agno.models.openai import OpenAIChat
    from agno.tools.crw import CrwTools

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[CrwTools()],  # connects to localhost:3000
    )
    agent.print_response("Summarize https://example.com")
"""

import json
import time
from os import getenv
from typing import Any, Dict, List, Optional

import httpx

from agno.tools import Toolkit
from agno.utils.log import logger


class CrwTools(Toolkit):
    """
    CRW is a high-performance web scraper built for AI agents.
    Firecrawl-compatible API, single binary, ~6 MB idle RAM.

    Works with both self-hosted CRW and fastcrw.com cloud.

    Args:
        api_url: Base URL of the CRW server. Default: http://localhost:3000
        api_key: Bearer token for authentication. Falls back to CRW_API_KEY env var.
        formats: Output formats for scraping. Default: ["markdown"]
        max_content_length: Truncate response content to this many characters. Default: 50000
        timeout: HTTP request timeout in seconds. Default: 120
        render_js: Force JS rendering. None = auto-detect (recommended). Default: None
        only_main_content: Strip navigation, footer, sidebar. Default: True
        enable_scrape: Enable the scrape_url tool. Default: True
        enable_crawl: Enable the crawl_site tool. Default: False
        enable_map: Enable the map_site tool. Default: False
        enable_extract: Enable the extract_data tool. Default: False
        all: Enable all tools. Overrides individual flags. Default: False
    """

    def __init__(
        self,
        api_url: str = "http://localhost:3000",
        api_key: Optional[str] = None,
        formats: Optional[List[str]] = None,
        max_content_length: int = 50000,
        timeout: int = 120,
        render_js: Optional[bool] = None,
        only_main_content: bool = True,
        crawl_max_pages: int = 100,
        crawl_max_depth: int = 2,
        crawl_poll_interval: int = 5,
        enable_scrape: bool = True,
        enable_crawl: bool = False,
        enable_map: bool = False,
        enable_extract: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key or getenv("CRW_API_KEY")
        self.formats = formats or ["markdown"]
        self.max_content_length = max_content_length
        self.timeout = timeout
        self.render_js = render_js
        self.only_main_content = only_main_content
        self.crawl_max_pages = crawl_max_pages
        self.crawl_max_depth = crawl_max_depth
        self.crawl_poll_interval = crawl_poll_interval

        tools: List[Any] = []
        if all or enable_scrape:
            tools.append(self.scrape_url)
        if all or enable_crawl:
            tools.append(self.crawl_site)
        if all or enable_map:
            tools.append(self.map_site)
        if all or enable_extract:
            tools.append(self.extract_data)

        super().__init__(name="crw_tools", tools=tools, **kwargs)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _truncate(self, content: str) -> str:
        if len(content) > self.max_content_length:
            return content[: self.max_content_length] + "\n... (content truncated)"
        return content

    def scrape_url(self, url: str) -> str:
        """Scrape a single URL and return its content as markdown.

        Use this tool to fetch and extract the main content from any webpage.
        Returns clean markdown by default, stripping navigation, ads, and boilerplate.

        Args:
            url: The URL to scrape (must be http or https).

        Returns:
            JSON string with markdown content and metadata (title, status code, etc.).
        """
        try:
            payload: Dict[str, Any] = {
                "url": url,
                "formats": self.formats,
                "onlyMainContent": self.only_main_content,
            }
            if self.render_js is not None:
                payload["renderJs"] = self.render_js

            response = httpx.post(
                f"{self.api_url}/v1/scrape",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()

            if not result.get("success"):
                return json.dumps({"error": result.get("error", "Unknown error")})

            return self._truncate(json.dumps(result["data"], ensure_ascii=False))

        except Exception as e:
            error_msg = f"Error scraping {url}: {str(e)}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg})

    def crawl_site(self, url: str, max_pages: Optional[int] = None) -> str:
        """Crawl a website starting from the given URL and return content from multiple pages.

        Use this tool to scrape an entire site or section. Follows links (BFS) up to
        a configurable depth and page limit. Returns markdown for each discovered page.

        This is an async operation — the tool starts the crawl, polls for completion,
        and returns all results once finished.

        Args:
            url: The starting URL to crawl from.
            max_pages: Maximum number of pages to crawl. Default: 100.

        Returns:
            JSON string with an array of page results (markdown + metadata per page).
        """
        try:
            payload: Dict[str, Any] = {
                "url": url,
                "maxDepth": self.crawl_max_depth,
                "maxPages": max_pages or self.crawl_max_pages,
                "formats": self.formats,
                "onlyMainContent": self.only_main_content,
            }

            # Start crawl job
            response = httpx.post(
                f"{self.api_url}/v1/crawl",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()

            if not result.get("success"):
                return json.dumps({"error": result.get("error", "Unknown error")})

            job_id = result["id"]

            # Poll for completion
            while True:
                time.sleep(self.crawl_poll_interval)
                status_response = httpx.get(
                    f"{self.api_url}/v1/crawl/{job_id}",
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                status_response.raise_for_status()
                status = status_response.json()

                if status["status"] == "completed":
                    return self._truncate(
                        json.dumps(status["data"], ensure_ascii=False)
                    )
                elif status["status"] == "failed":
                    return json.dumps({"error": "Crawl job failed", "job_id": job_id})

        except Exception as e:
            error_msg = f"Error crawling {url}: {str(e)}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg})

    def map_site(self, url: str) -> str:
        """Discover all URLs on a website without scraping their content.

        Use this tool to get a site map — a list of all pages found on a domain.
        Useful for understanding site structure before deciding which pages to scrape.

        Args:
            url: The URL to discover links from.

        Returns:
            JSON string with an array of discovered URLs.
        """
        try:
            payload: Dict[str, Any] = {"url": url}

            response = httpx.post(
                f"{self.api_url}/v1/map",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()

            if not result.get("success"):
                return json.dumps({"error": result.get("error", "Unknown error")})

            return json.dumps(result["data"], ensure_ascii=False)

        except Exception as e:
            error_msg = f"Error mapping {url}: {str(e)}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg})

    def extract_data(self, url: str, json_schema: dict) -> str:
        """Scrape a URL and extract structured data using LLM-powered extraction.

        Use this tool when you need specific fields from a webpage (e.g., product name
        and price, article title and author). Provide a JSON Schema describing the
        desired output format, and the LLM will extract matching data from the page.

        Requires LLM extraction to be configured on the CRW server.

        Args:
            url: The URL to scrape and extract data from.
            json_schema: A JSON Schema object describing the desired output structure.
                Example: {"type": "object", "properties": {"title": {"type": "string"}}}

        Returns:
            JSON string with the extracted structured data.
        """
        try:
            payload: Dict[str, Any] = {
                "url": url,
                "formats": ["json"],
                "jsonSchema": json_schema,
                "onlyMainContent": self.only_main_content,
            }
            if self.render_js is not None:
                payload["renderJs"] = self.render_js

            response = httpx.post(
                f"{self.api_url}/v1/scrape",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()

            if not result.get("success"):
                return json.dumps({"error": result.get("error", "Unknown error")})

            return json.dumps(result["data"].get("json", {}), ensure_ascii=False)

        except Exception as e:
            error_msg = f"Error extracting data from {url}: {str(e)}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg})
