import json
import os
from typing import Any, List, Optional

from agno.tools import Toolkit

try:
    from scrapegraph_py import Client
except ImportError:
    raise ImportError("`scrapegraph-py` not installed. Please install using `pip install scrapegraph-py`")


class ScrapeGraphTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        smartscraper: bool = True,
        markdownify: bool = False,
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

        super().__init__(name="scrapegraph_tools", tools=tools, **kwargs)

    def smartscraper(self, url: str, prompt: str) -> str:
        """Use this function to extract structured data from a webpage using LLM.
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
        """Use this function to convert a webpage to markdown format.
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
