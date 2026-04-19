import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    from scrapegraph_py import (
        CrawlRequest,
        ExtractRequest,
        FetchConfig,
        HtmlFormatConfig,
        JsonFormatConfig,
        MarkdownFormatConfig,
        ScrapeGraphAI,
        ScrapeRequest,
        SearchRequest,
    )
except ImportError:
    raise ImportError("`scrapegraph-py>=2.0.0` not installed. Please install using `pip install scrapegraph-py`")


def _unwrap(result: Any) -> Any:
    """Return result.data on success, otherwise raise with result.error."""
    if getattr(result, "status", None) == "success":
        return result.data
    raise RuntimeError(getattr(result, "error", None) or "ScrapeGraphAI request failed")


class ScrapeGraphTools(Toolkit):
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
        self.api_key: Optional[str] = api_key or getenv("SGAI_API_KEY")
        self.client = ScrapeGraphAI(api_key=self.api_key)
        self.render_heavy_js = render_heavy_js

        # Start with smartscraper by default
        # Only enable markdownify if smartscraper is False
        if not enable_smartscraper and not all:
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

        super().__init__(name="scrapegraph_tools", tools=tools, **kwargs)

    def _fetch_config(self) -> Optional[FetchConfig]:
        if self.render_heavy_js:
            return FetchConfig(mode="js")
        return None

    def smartscraper(self, url: str, prompt: str) -> str:
        """Extract structured data from a webpage using AI.

        Args:
            url (str): The URL to scrape
            prompt (str): Natural language prompt describing what to extract

        Returns:
            The structured data extracted from the webpage (JSON string)
        """
        try:
            log_debug(f"ScrapeGraph smartscraper (extract) request for URL: {url}")
            response = self.client.extract(ExtractRequest(url=url, prompt=prompt, fetch_config=self._fetch_config()))
            data = _unwrap(response)
            payload = data.json_data if data.json_data is not None else data.raw
            return json.dumps(payload)
        except Exception as e:
            error_msg = f"Smartscraper failed: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"

    def markdownify(self, url: str) -> str:
        """Convert a webpage to markdown format.

        Args:
            url (str): The URL to convert

        Returns:
            The markdown version of the webpage
        """
        try:
            log_debug(f"ScrapeGraph markdownify request for URL: {url}")
            response = self.client.scrape(
                ScrapeRequest(
                    url=url,
                    formats=[MarkdownFormatConfig()],
                    fetch_config=self._fetch_config(),
                )
            )
            data = _unwrap(response)
            markdown = data.results.get("markdown", {})
            value = markdown.get("data", "") if isinstance(markdown, dict) else markdown
            if isinstance(value, list):
                value = "\n\n".join(str(v) for v in value)
            return str(value)
        except Exception as e:
            error_msg = f"Markdownify failed: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"

    def crawl(
        self,
        url: str,
        prompt: str,
        schema: dict,
        depth: int = 2,
        max_pages: int = 2,
    ) -> str:
        """Crawl a website and extract structured data.

        Args:
            url (str): The URL to crawl
            prompt (str): Natural language prompt describing what to extract
            schema (dict): JSON schema for extraction
            depth (int): Crawl depth
            max_pages (int): Max number of pages to crawl

        Returns:
            The structured data extracted from the website (JSON string)
        """
        try:
            log_debug(f"ScrapeGraph crawl request for URL: {url}")
            response = self.client.crawl.start(
                CrawlRequest(
                    url=url,
                    formats=[JsonFormatConfig(prompt=prompt, schema=schema)],
                    max_depth=depth,
                    max_pages=max_pages,
                    fetch_config=self._fetch_config(),
                )
            )
            data = _unwrap(response)
            return data.model_dump_json(indent=2, by_alias=True)
        except Exception as e:
            error_msg = f"Crawl failed: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"

    def searchscraper(self, user_prompt: str) -> str:
        """Search the web and extract information.

        Args:
            user_prompt (str): Search query

        Returns:
            JSON of the search results
        """
        try:
            log_debug(f"ScrapeGraph searchscraper (search) request with prompt: {user_prompt}")
            response = self.client.search(SearchRequest(query=user_prompt))
            data = _unwrap(response)
            return data.model_dump_json(by_alias=True)
        except Exception as e:
            error_msg = f"Searchscraper failed: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"

    def scrape(
        self,
        website_url: str,
        headers: Optional[dict] = None,
    ) -> str:
        """Get raw HTML content from a website using the ScrapeGraphAI scrape API.

        Args:
            website_url (str): The URL of the website to scrape
            headers (Optional[dict]): Optional headers to send with the request

        Returns:
            JSON string containing the HTML content and metadata
        """
        try:
            log_debug(f"ScrapeGraph scrape request for URL: {website_url}")
            fetch_config = self._fetch_config()
            if headers:
                fetch_config = FetchConfig(
                    mode=fetch_config.mode if fetch_config else "auto",
                    headers=headers,
                )
            response = self.client.scrape(
                ScrapeRequest(
                    url=website_url,
                    formats=[HtmlFormatConfig()],
                    fetch_config=fetch_config,
                )
            )
            data = _unwrap(response)
            return data.model_dump_json(indent=2, by_alias=True)
        except Exception as e:
            error_msg = f"Scrape failed: {str(e)}"
            log_error(error_msg)
            return f"Error: {error_msg}"
