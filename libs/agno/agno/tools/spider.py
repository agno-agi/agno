import json
from os import getenv
from typing import Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_exception, log_info

try:
    from spider import Spider as ExternalSpider
except ImportError:
    raise ImportError("`spider-client` not installed. Please install using `pip install spider-client`")


class SpiderTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        default_url: Optional[str] = None,
        max_results: Optional[int] = None,
        optional_params: Optional[dict] = None,
        search: bool = True,
        scrape: bool = True,
        crawl: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize SpiderTools for web searching, scraping, and crawling.

        Args:
            api_key: Spider API key. Falls back to SPIDER_API_KEY env var.
            default_url: Default URL for scrape/crawl operations. Agent can override.
            max_results: Default maximum number of search results.
            optional_params: Additional parameters for operations.
            search: Enable web search. Defaults to True.
            scrape: Enable web scraping. Defaults to True (token heavy).
            crawl: Enable web crawling. Defaults to True (token heavy).
            all: Enable all tools. Defaults to False.
        """
        self.api_key = api_key or getenv("SPIDER_API_KEY")
        self.default_url = default_url
        self.max_results = max_results
        self.optional_params = optional_params or {}
        self._client: Optional[ExternalSpider] = None

        tools: List[Callable] = []
        if all or search:
            tools.append(self.spider_search_web)
        if all or scrape:
            tools.append(self.spider_scrape)
        if all or crawl:
            tools.append(self.spider_crawl)

        super().__init__(name="spider", tools=tools, **kwargs)

    @property
    def client(self) -> ExternalSpider:
        if self._client is None:
            self._client = ExternalSpider(api_key=self.api_key)
        return self._client

    def spider_search_web(self, query: str, max_results: Optional[int] = None) -> str:
        """Use this function to search the web.
        Args:
            query (str): The query to search the web with.
            max_results (int, optional): The maximum number of results to return. Defaults to the value set on the toolkit, or 5.
        Returns:
            The results of the search.
        """
        return self._search(query, max_results=max_results)

    def spider_scrape(self, url: Optional[str] = None) -> str:
        """Use this function to scrape the content of a webpage.
        Args:
            url (str, optional): The URL of the webpage to scrape. Uses default_url if not provided.
        Returns:
            Markdown of the webpage.
        """
        target = url or self.default_url
        if not target:
            return json.dumps({"error": "No URL provided. Pass a url or set default_url on the toolkit."})
        return self._scrape(target)

    def spider_crawl(self, url: Optional[str] = None, limit: Optional[int] = None) -> str:
        """Use this function to crawl the web.
        Args:
            url (str, optional): The URL of the webpage to crawl. Uses default_url if not provided.
            limit (int, optional): The maximum number of pages to crawl. Defaults to 10.
        Returns:
            The results of the crawl.
        """
        target = url or self.default_url
        if not target:
            return json.dumps({"error": "No URL provided. Pass a url or set default_url on the toolkit."})
        return self._crawl(target, limit=limit)

    def _search(self, query: str, max_results: Optional[int] = None) -> str:
        try:
            options = {"fetch_page_content": False, "num": self.max_results or 5, **self.optional_params}
            if max_results is not None:
                options["num"] = max_results
            log_info(f"Fetching results from spider for query: {query} with max_results: {options['num']}")
            results = self.client.search(query, options)
            return json.dumps(results)
        except Exception as e:
            log_exception("Error fetching results from spider")
            return json.dumps({"error": f"Error fetching results from spider: {e}"})

    def _scrape(self, url: str) -> str:
        try:
            log_info(f"Fetching content from spider for url: {url}")
            options = {"return_format": "markdown", **self.optional_params}
            results = self.client.scrape_url(url, options)
            return json.dumps(results)
        except Exception as e:
            log_exception("Error fetching content from spider")
            return json.dumps({"error": f"Error fetching content from spider: {e}"})

    def _crawl(self, url: str, limit: Optional[int] = None) -> str:
        try:
            log_info(f"Fetching content from spider for url: {url}")
            options = {"return_format": "markdown", "limit": 10, **self.optional_params}
            if limit is not None:
                options["limit"] = limit
            results = self.client.crawl_url(url, options)
            return json.dumps(results)
        except Exception as e:
            log_exception("Error fetching content from spider")
            return json.dumps({"error": f"Error fetching content from spider: {e}"})
