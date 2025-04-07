import json

try:
    from spider import Spider as ExternalSpider
except ImportError:
    raise ImportError("`spider-client` not installed. Please install using `pip install spider-client`")

from typing import Optional

from agno.tools.toolkit import Toolkit
from agno.utils.log import log_info, logger


class SpiderTools(Toolkit):
    def __init__(
        self,
        max_results: Optional[int] = None,
        url: Optional[str] = None,
        optional_params: Optional[dict] = None,
        **kwargs,
    ):
        super().__init__(name="spider", **kwargs)
        self.max_results = max_results
        self.url = url
        self.optional_params = optional_params or {}
        self.register(self.search)
        self.register(self.scrape)
        self.register(self.crawl)

    def search(self, query: str, max_results: int = 5) -> str:
        """Use this function to search the web.
        Args:
            query (str): The query to search the web with.
            max_results (int, optional): The maximum number of results to return. Defaults to 5.
        Returns:
            The results of the search.
        """
        max_results = self.max_results or max_results
        return self._search(query, max_results=max_results)

    def scrape(self, url: str) -> str:
        """Use this function to scrape the content of a webpage.
        Args:
            url (str): The URL of the webpage to scrape.
        Returns:
            Markdown of the webpage.
        """
        return self._scrape(url)

    def crawl(self, url: str, limit: Optional[int] = None) -> str:
        """Use this function to crawl the web.
        Args:
            url (str): The URL of the webpage to crawl.
            limit (int, optional): The maximum number of pages to crawl. Defaults to 10.
        Returns:
            The results of the crawl.
        """
        return self._crawl(url, limit=limit)

    def _search(self, query: str, max_results: int = 1) -> str:
        app = ExternalSpider()
        log_info(f"Fetching results from spider for query: {query} with max_results: {max_results}")
        try:
            options = {"fetch_page_content": False, "num": max_results, **self.optional_params}
            results = app.search(query, options)
            return json.dumps(results)
        except Exception as e:
            logger.error(f"Error fetching results from spider: {e}")
            return f"Error fetching results from spider: {e}"

    def _scrape(self, url: str) -> str:
        app = ExternalSpider()
        log_info(f"Fetching content from spider for url: {url}")
        try:
            options = {"return_format": "markdown", **self.optional_params}
            results = app.scrape_url(url, options)
            return json.dumps(results)
        except Exception as e:
            logger.error(f"Error fetching content from spider: {e}")
            return f"Error fetching content from spider: {e}"

    def _crawl(self, url: str, limit: Optional[int] = None) -> str:
        app = ExternalSpider()
        log_info(f"Fetching content from spider for url: {url}")
        try:
            if limit is None:
                limit = 10
            options = {"return_format": "markdown", "limit": limit, **self.optional_params}
            results = app.crawl_url(url, options)
            return json.dumps(results)
        except Exception as e:
            logger.error(f"Error fetching content from spider: {e}")
            return f"Error fetching content from spider: {e}"
