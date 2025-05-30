import json
from os import getenv
from typing import Optional

from agno.tools import Toolkit
from agno.utils.log import log_info

try:
    from brave import Brave
except ImportError:
    raise ImportError("`brave-search` not installed. Please install using `pip install brave-search`")


class BraveSearchTools(Toolkit):
    """
    BraveSearch is a toolkit for searching Brave easily.

    Args:
        api_key (str, optional): Brave API key. If not provided, will use BRAVE_API_KEY environment variable.
        fixed_max_results (Optional[int]): A fixed number of maximum results.
        fixed_language (Optional[str]): A fixed language for the search results.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        fixed_max_results: Optional[int] = None,
        fixed_language: Optional[str] = None,
        **kwargs,
    ):
        self.api_key = api_key or getenv("BRAVE_API_KEY")
        if not self.api_key:
            raise ValueError("BRAVE_API_KEY is required. Please set the BRAVE_API_KEY environment variable.")

        self.fixed_max_results = fixed_max_results
        self.fixed_language = fixed_language

        self.brave_client = Brave(api_key=self.api_key)

        tools = []
        tools.append(self.brave_search)

        super().__init__(
            name="brave_search",
            tools=tools,
            **kwargs,
        )

    def brave_search(
        self,
        query: str,
        max_results: Optional[int] = None,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
    ) -> str:
        """
        Search Brave for the specified query and return the results.

        Args:
            query (str): The query to search for.
            max_results (int, optional): The maximum number of results to return. Default is 5.
            country (str, optional): The country code for search results. Default is "US".
            search_lang (str, optional): The language of the search results. Default is "en".
        Returns:
            str: A JSON formatted string containing the search results.
        """
        max_results = self.fixed_max_results or max_results
        search_lang = self.fixed_language or search_lang

        if not query:
            return json.dumps({"error": "Please provide a query to search for"})

        log_info(f"Searching Brave for: {query}")

        search_params = {
            "q": query,
            "count": max_results,
            "country": country,
            "search_lang": search_lang,
            "result_filter": "web",
        }

        search_results = self.brave_client.search(**search_params)

        filtered_results = {
            "web_results": [],
            "query": query,
            "total_results": 0,
        }

        if hasattr(search_results, "web") and search_results.web:
            web_results = []
            for result in search_results.web.results:
                web_result = {
                    "title": result.title,
                    "url": str(result.url),
                    "description": result.description,
                }
                web_results.append(web_result)
            filtered_results["web_results"] = web_results
            filtered_results["total_results"] = len(web_results)

        return json.dumps(filtered_results, indent=2)
