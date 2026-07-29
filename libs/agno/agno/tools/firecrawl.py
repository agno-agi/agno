import json
from os import getenv
from typing import Any, Callable, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error

try:
    from firecrawl import FirecrawlApp  # type: ignore[attr-defined]
    from firecrawl.types import ScrapeOptions
except ImportError:
    raise ImportError("`firecrawl-py` not installed. Please install using `pip install firecrawl-py`")


class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles non-serializable types by converting them to strings."""

    def default(self, obj):
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


class FirecrawlTools(Toolkit):
    """
    Firecrawl is a tool for scraping and crawling websites.

    Args:
        api_key (Optional[str]): The API key to use for the Firecrawl app.
        scrape (bool): Enable website scraping functionality. Default is True.
        crawl (bool): Enable website crawling functionality. Default is False.
        mapping (bool): Enable website mapping functionality. Default is False.
        search (bool): Enable web search functionality. Default is False.
        all (bool): Enable all tools. Overrides individual flags when True. Default is False.
        formats (Optional[List[str]]): The formats to use for the Firecrawl app.
        limit (int): The maximum number of pages to crawl.
        poll_interval (int): Polling interval for crawl operations.
        search_params (Optional[Dict[str, Any]]): Parameters for search operations.
        api_url (Optional[str]): The API URL to use for the Firecrawl app.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        scrape: bool = True,
        crawl: bool = False,
        mapping: bool = False,
        search: bool = False,
        all: bool = False,
        formats: Optional[List[str]] = None,
        limit: int = 10,
        poll_interval: int = 30,
        search_params: Optional[Dict[str, Any]] = None,
        api_url: Optional[str] = "https://api.firecrawl.dev",
        **kwargs,
    ):
        self.api_key: Optional[str] = api_key or getenv("FIRECRAWL_API_KEY")
        if not self.api_key:
            log_error("FIRECRAWL_API_KEY not set. Please set the FIRECRAWL_API_KEY environment variable.")

        self.formats: Optional[List[str]] = formats
        self.limit: int = limit
        self.poll_interval: int = poll_interval
        self.app: FirecrawlApp = FirecrawlApp(api_key=self.api_key, api_url=api_url)
        self.search_params = search_params

        tools: List[Callable] = []
        if all or scrape:
            tools.append(self.scrape_website)
        if all or crawl:
            tools.append(self.crawl_website)
        if all or mapping:
            tools.append(self.map_website)
        if all or search:
            tools.append(self.search_web)

        super().__init__(name="firecrawl_tools", tools=tools, **kwargs)

    def scrape_website(self, url: str) -> str:
        """Scrape a website using Firecrawl.

        Args:
            url: The URL to scrape.

        Returns:
            JSON with scraped content.
        """
        params = {}
        if self.formats:
            params["formats"] = self.formats

        scrape_result = self.app.scrape(url, **params)
        return json.dumps(scrape_result.model_dump(), cls=CustomJSONEncoder)

    def crawl_website(self, url: str, limit: Optional[int] = None) -> str:
        """Crawl a website using Firecrawl.

        Args:
            url: The URL to crawl.
            limit: Maximum pages to crawl. Defaults to toolkit limit.

        Returns:
            JSON with crawl results.
        """
        params: Dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        elif self.limit is not None:
            params["limit"] = self.limit
        if self.formats:
            params["scrape_options"] = ScrapeOptions(formats=self.formats)  # type: ignore

        params["poll_interval"] = self.poll_interval

        crawl_result = self.app.crawl(url, **params)
        return json.dumps(crawl_result.model_dump(), cls=CustomJSONEncoder)

    def map_website(self, url: str) -> str:
        """Map a website using Firecrawl.

        Args:
            url: The URL to map.

        Returns:
            JSON with site map.
        """
        map_result = self.app.map(url)
        return json.dumps(map_result.model_dump(), cls=CustomJSONEncoder)

    def search_web(self, query: str, limit: Optional[int] = None) -> str:
        """Search the web using Firecrawl.

        Args:
            query: The search query.
            limit: Maximum results to return. Defaults to toolkit limit.

        Returns:
            JSON with search results.
        """
        params: Dict[str, Any] = {}
        if self.limit is not None:
            params["limit"] = self.limit
        if self.formats:
            params["scrape_options"] = ScrapeOptions(formats=self.formats)  # type: ignore
        if self.search_params:
            params.update(self.search_params)
        # Applied after search_params so an explicit call argument always wins.
        if limit is not None:
            params["limit"] = limit

        search_result = self.app.search(query, **params)

        if hasattr(search_result, "success"):
            if search_result.success:
                return json.dumps(search_result.data, cls=CustomJSONEncoder)
            else:
                return json.dumps({"error": f"Firecrawl search failed: {search_result.error}"})
        else:
            return json.dumps(search_result.model_dump(), cls=CustomJSONEncoder)
