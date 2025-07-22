import json
import os
from typing import Any, List, Optional

from agno.tools import Toolkit

try:
    from scrapegraph_py import Client
    from scrapegraph_py.logger import sgai_logger
except ImportError:
    raise ImportError("`scrapegraph-py` not installed. Please install using `pip install scrapegraph-py`")

# Set logging level
sgai_logger.set_logging(level="INFO")


class ScrapeGraphTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        smartscraper: bool = True,
        markdownify: bool = False,
        crawl: bool = False,
        searchscraper: bool = False,
        **kwargs,
    ):
        self.api_key: Optional[str] = api_key or os.getenv("SGAI_API_KEY")
        self.client = Client(api_key=self.api_key)

        # Start with smartscraper by default
        # Only enable markdownify if smartscraper is False
        if not smartscraper:
            markdownify = True

        tools: List[Any] = []
        if smartscraper:
            tools.append(self.smartscraper)
        if markdownify:
            tools.append(self.markdownify)
        if crawl:
            tools.append(self.crawl)
        if searchscraper:
            tools.append(self.searchscraper)

        super().__init__(name="scrapegraph_tools", tools=tools, **kwargs)

    def smartscraper(self, url: str, prompt: str) -> str:
        """Extract structured data from a webpage using LLM.
        Args:
            url (str): The URL to scrape
            prompt (str): Natural language prompt describing what to extract
        Returns:
            The structured data extracted from the webpage
        """
        try:
            response = self.client.smartscraper(website_url=url, user_prompt=prompt)
            return json.dumps(response["result"])
        except Exception as e:
            return json.dumps({"error": str(e)})

    def markdownify(self, url: str) -> str:
        """Convert a webpage to markdown format.
        Args:
            url (str): The URL to convert
        Returns:
            The markdown version of the webpage
        """
        try:
            response = self.client.markdownify(website_url=url)
            return response["result"]
        except Exception as e:
            return f"Error converting to markdown: {str(e)}"

    def crawl(
        self,
        url: str,
        prompt: str,
        schema: dict,
        cache_website: bool = True,
        depth: int = 2,
        max_pages: int = 2,
        same_domain_only: bool = True,
        batch_size: int = 1,
    ) -> str:
        """Crawl a website and extract structured data
        Args:
            url (str): The URL to crawl
            prompt (str): Natural language prompt describing what to extract
            schema (dict): JSON schema for extraction
            cache_website (bool): Whether to cache the website
            depth (int): Crawl depth
            max_pages (int): Max number of pages to crawl
            same_domain_only (bool): Restrict to same domain
            batch_size (int): Batch size for crawling
        Returns:
            The structured data extracted from the website
        """
        try:
            response = self.client.crawl(
                url=url,
                prompt=prompt,
                schema=schema,
                cache_website=cache_website,
                depth=depth,
                max_pages=max_pages,
                same_domain_only=same_domain_only,
                batch_size=batch_size,
            )
            return json.dumps(response, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def searchscraper(self, prompt: str) -> str:
        """Search the web and extract information from the web.
        Args:
            prompt (str): Search query
        Returns:
            JSON of the search results
        """
        try:
            response = self.client.searchscraper(user_prompt=prompt)
            if hasattr(response, "result"):
                return json.dumps(response.result)
            elif isinstance(response, dict) and "result" in response:
                return json.dumps(response["result"])
            else:
                return json.dumps(response)
        except Exception as e:
            return json.dumps({"error": str(e)})
