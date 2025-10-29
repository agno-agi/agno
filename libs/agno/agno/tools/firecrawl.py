import json
from os import getenv
from typing import Any, Dict, List, Optional

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
        enable_scrape (bool): Enable website scraping functionality. Default is True.
        enable_crawl (bool): Enable website crawling functionality. Default is False.
        enable_mapping (bool): Enable website mapping functionality. Default is False.
        enable_search (bool): Enable web search functionality. Default is False.
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
        enable_scrape: bool = True,
        enable_crawl: bool = False,
        enable_mapping: bool = False,
        enable_search: bool = False,
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

        tools: List[Any] = []
        if all or enable_scrape:
            tools.append(self.scrape_website)
        if all or enable_crawl:
            tools.append(self.crawl_website)
        if all or enable_mapping:
            tools.append(self.map_website)
        if all or enable_search:
            tools.append(self.search_web)

        super().__init__(name="firecrawl_tools", tools=tools, **kwargs)

    def scrape_website(self, url: str) -> str:
        """Use this function to scrape a website using Firecrawl.

        Args:
            url (str): The URL to scrape.
        """
        params = {}
        if self.formats:
            params["formats"] = self.formats

        scrape_result = self.app.scrape(url, **params)
        return json.dumps(scrape_result.model_dump(), cls=CustomJSONEncoder)

    def crawl_website(self, url: str, limit: Optional[int] = None) -> str:
        """Use this function to Crawls a website using Firecrawl.

        Args:
            url (str): The URL to crawl.
            limit (int): The maximum number of pages to crawl

        Returns:
            The results of the crawling.
        """
        params: Dict[str, Any] = {}
        if self.limit or limit:
            params["limit"] = self.limit or limit
        if self.formats:
            params["scrape_options"] = ScrapeOptions(formats=self.formats)  # type: ignore

        params["poll_interval"] = self.poll_interval

        crawl_result = self.app.crawl(url, **params)
        return json.dumps(crawl_result.model_dump(), cls=CustomJSONEncoder)

    def map_website(self, url: str) -> str:
        """Use this function to Map a website using Firecrawl.

        Args:
            url (str): The URL to map.

        """
        map_result = self.app.map(url)
        return json.dumps(map_result.model_dump(), cls=CustomJSONEncoder)

    def search_web(self, query: str, limit: Optional[int] = None):
        """Use this function to search for the web using Firecrawl.

        Args:
            query (str): The query to search for.
            limit (int): The maximum number of results to return.
        """
        params: Dict[str, Any] = {}
        if self.limit or limit:
            params["limit"] = self.limit or limit
        if self.formats:
            params["scrape_options"] = ScrapeOptions(formats=self.formats)  # type: ignore
        if self.search_params:
            params.update(self.search_params)

        search_result = self.app.search(query, **params)
        if search_result.success:
            return json.dumps(search_result.data, cls=CustomJSONEncoder)
        else:
            return "Error searching with the Firecrawl tool: " + search_result.error
