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
        enable_brave_search: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("BRAVE_API_KEY")
        if not self.api_key:
            raise ValueError("BRAVE_API_KEY is required. Please set the BRAVE_API_KEY environment variable.")

        self.fixed_max_results = fixed_max_results
        self.fixed_language = fixed_language

        self.brave_client = Brave(api_key=self.api_key)

        tools = []
        if all or enable_brave_search:
            tools.append(self.brave_search)

        super().__init__(
            name="brave_search",
            tools=tools,
            **kwargs,
        )

    def brave_search(
        self,
        query: str,
        max_results: int = 5,
        country: str = "US",
        search_lang: str = "en",
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
        final_max_results = self.fixed_max_results if self.fixed_max_results is not None else max_results
        final_search_lang = self.fixed_language if self.fixed_language is not None else search_lang

        if not query:
            return json.dumps({"error": "Please provide a query to search for"})

        log_info(f"Searching Brave for: {query}")

        search_params = {
            "q": query,
            "count": final_max_results,
            "country": country,
            "search_lang": final_search_lang,
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
