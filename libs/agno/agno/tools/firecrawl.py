import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from firecrawl import FirecrawlApp
except ImportError:
    raise ImportError("`firecrawl-py` not installed. Please install using `pip install firecrawl-py`")


class FirecrawlTools(Toolkit):
    """
    Firecrawl is a tool for scraping and crawling websites.
    Args:
        api_key (Optional[str]): The API key to use for the Firecrawl app.
        formats (Optional[List[str]]): The formats to use for the Firecrawl app.
        limit (int): The maximum number of pages to crawl.
        scrape (bool): Whether to scrape the website.
        crawl (bool): Whether to crawl the website.
        api_url (Optional[str]): The API URL to use for the Firecrawl app.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        formats: Optional[List[str]] = None,
        limit: int = 10,
        scrape: bool = True,
        crawl: bool = False,
        api_url: Optional[str] = "https://api.firecrawl.dev",
        **kwargs,
    ):
        super().__init__(name="firecrawl_tools", **kwargs)

        self.api_key: Optional[str] = api_key or getenv("FIRECRAWL_API_KEY")
        if not self.api_key:
            logger.error("FIRECRAWL_API_KEY not set. Please set the FIRECRAWL_API_KEY environment variable.")

        self.formats: Optional[List[str]] = formats
        self.limit: int = limit
        self.app: FirecrawlApp = FirecrawlApp(api_key=self.api_key, api_url=api_url)

        # Start with scrape by default. But if crawl is set, then set scrape to False.
        if crawl:
            scrape = False
        elif not scrape:
            crawl = True

        if scrape:
            self.register(self.scrape_website)
        if crawl:
            self.register(self.crawl_website)

    def scrape_website(self, url: str) -> str:
        """Use this function to Scrapes a website using Firecrawl.

        Args:
            url (str): The URL to scrape.

        Returns:
            The results of the scraping.
        """
        if url is None:
            return "No URL provided"

        params = {}
        if self.formats:
            params["formats"] = self.formats

        scrape_result = self.app.scrape_url(url, params=params)
        return json.dumps(scrape_result)

    def crawl_website(self, url: str, limit: Optional[int] = None) -> str:
        """Use this function to Crawls a website using Firecrawl.

        Args:
            url (str): The URL to crawl.
            limit (int): The maximum number of pages to crawl

        Returns:
            The results of the crawling.
        """
        if url is None:
            return "No URL provided"

        params: Dict[str, Any] = {}
        if self.limit or limit:
            params["limit"] = self.limit or limit
            if self.formats:
                params["scrapeOptions"] = {"formats": self.formats}

        crawl_result = self.app.crawl_url(url, params=params, poll_interval=30)
        return json.dumps(crawl_result)
