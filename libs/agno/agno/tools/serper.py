import json
from os import getenv
from typing import Any, Dict, List, Optional

import requests

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning


class SerperTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        location: str = "us",
        language: str = "en",
        num_results: int = 10,
        date_range: Optional[str] = None,
        **kwargs,
    ):
        """
        Initialize the SerperTools.

        Args:
            api_key Optional[str]: The Serper API key.
            location Optional[str]: The Google location code for search results.
            language Optional[str]: The language code for search results.
            num_results Optional[int]: The number of search results to retrieve.
            date_range Optional[str]: Default date range filter for searches.
        """
        self.api_key = api_key or getenv("SERPER_API_KEY")
        if not self.api_key:
            log_debug("No Serper API key provided")

        self.location = location
        self.language = language
        self.num_results = num_results
        self.date_range = date_range

        tools: List[Any] = []
        tools.append(self.search)
        tools.append(self.search_news)
        tools.append(self.search_scholar)
        tools.append(self.scrape_webpage)

        super().__init__(name="serper_tools", tools=tools, **kwargs)

    def _make_request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Makes a request to the Serper API.

        Args:
            endpoint (str): The API endpoint
            params (Dict[str, Any]): Request parameters

        Returns:
            Dict[str, Any]: Search response
        """
        try:
            if not self.api_key:
                log_error("No Serper API key provided")
                return {"success": False, "error": "Please provide a Serper API key"}

            url = f"https://google.serper.dev/{endpoint}"
            if endpoint == "scrape":
                url = "https://scrape.serper.dev"

            headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}

            # Add optional parameters
            if self.date_range:
                params["tbs"] = self.date_range
            if self.location:
                params["gl"] = self.location

            if self.language:
                params["hl"] = self.language

            payload = json.dumps(params)

            log_debug(f"Making request to {url} with params: {params}")
            response = requests.request("POST", url, headers=headers, data=payload)
            response.raise_for_status()

            log_debug(f"Successfully received response from {endpoint} endpoint")
            return {"success": True, "data": response.json(), "raw_response": response.text}
        except Exception as e:
            log_error(f"Serper API error: {str(e)}")
            return {"success": False, "error": str(e)}

    def search(
        self,
        query: str,
        num_results: Optional[int] = None,
    ) -> str:
        """
        Searches Google for the provided query using the Serper API.

        Args:
            query (str): The search query to search for on Google.
            num_results (int, optional): Number of search results to retrieve.

        Returns:
            str: A JSON-formatted string containing the search results or an error message if the search fails.
        """
        try:
            if not query:
                return json.dumps({"error": "Please provide a query to search for"}, indent=2)

            log_debug(f"Searching Google for: {query}")

            params = {
                "q": query,
                "num": num_results or self.num_results,
            }

            result = self._make_request("search", params)

            if result["success"]:
                log_debug(f"Successfully found Google search results for query: {query}")
                return result["raw_response"]
            else:
                log_error(f"Error searching Google for query {query}: {result['error']}")
                return json.dumps({"error": result["error"]}, indent=2)

        except Exception as e:
            log_error(f"Unexpected error searching Google for query {query}: {e}")
            return json.dumps({"error": f"An unexpected error occurred: {str(e)}"}, indent=2)

    def search_news(
        self,
        query: str,
        num_results: Optional[int] = None,
    ) -> str:
        """
        Searches for news articles using the Serper News API.

        Args:
            query (str): The search query for news articles.
            num_results (int, optional): Number of news results to retrieve.

        Returns:
            str: A JSON-formatted string containing the news search results or an error message.
        """
        try:
            if not query:
                return json.dumps({"error": "Please provide a query to search for news"}, indent=2)

            log_debug(f"Searching news for: {query}")

            params = {
                "q": query,
                "num": num_results or self.num_results,
            }

            result = self._make_request("news", params)

            if result["success"]:
                log_debug(f"Successfully found {num_results or self.num_results} news articles for query: {query}")
                return result["raw_response"]
            else:
                log_error(f"Error searching news for query {query}: {result['error']}")
                return json.dumps({"error": result["error"]}, indent=2)

        except Exception as e:
            log_error(f"Unexpected error searching news for query {query}: {e}")
            return json.dumps({"error": f"An unexpected error occurred: {str(e)}"}, indent=2)

    def search_scholar(
        self,
        query: str,
        num_results: Optional[int] = None,
    ) -> str:
        """
        Searches for academic papers using Google Scholar via Serper API.

        Args:
            query (str): The search query for academic papers.
            num_results (int, optional): Number of academic papers to retrieve.

        Returns:
            str: A JSON-formatted string containing the scholar search results or an error message.
        """
        try:
            if not query:
                return json.dumps({"error": "Please provide a query to search for academic papers"}, indent=2)

            log_debug(f"Searching scholar for: {query}")

            params = {
                "q": query,
                "num": num_results or self.num_results,
            }

            result = self._make_request("scholar", params)

            if result["success"]:
                log_debug(f"Successfully found academic papers for query: {query}")
                return result["raw_response"]
            else:
                log_error(f"Error searching scholar for query {query}: {result['error']}")
                return json.dumps({"error": result["error"]}, indent=2)

        except Exception as e:
            log_error(f"Unexpected error searching scholar for query {query}: {e}")
            return json.dumps({"error": f"An unexpected error occurred: {str(e)}"}, indent=2)

    def scrape_webpage(
        self,
        url: str,
        markdown: bool = False,
    ) -> str:
        """
        Scrapes and extracts content from a webpage using the Serper scraping API.

        Args:
            url (str): The URL of the webpage to scrape.
            markdown (bool, optional): Return content in markdown format (default: False).

        Returns:
            str: A JSON-formatted string containing the scraped webpage content or an error message.
        """
        try:
            if not url:
                log_warning("No URL provided to scrape")
                return json.dumps({"error": "Please provide a URL to scrape"}, indent=2)

            log_debug(f"Scraping webpage: {url}")

            params = {
                "url": url,
                "includeMarkdown": markdown,
            }

            result = self._make_request("scrape", params)

            if result["success"]:
                log_debug(f"Successfully scraped webpage: {url}")
                return result["raw_response"]
            else:
                log_error(f"Error scraping webpage {url}: {result['error']}")
                return json.dumps({"error": result["error"]}, indent=2)

        except Exception as e:
            log_error(f"Unexpected error scraping webpage {url}: {e}")
            return json.dumps({"error": f"An unexpected error occurred: {str(e)}"}, indent=2)
