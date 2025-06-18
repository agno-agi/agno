import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_info, logger

try:
    import serpapi
except ImportError:
    raise ImportError("`google-search-results` not installed.")


class SerpApiTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        search_youtube: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("SERP_API_KEY")
        if not self.api_key:
            logger.warning("No Serpapi API key provided")

        tools: List[Any] = []
        tools.append(self.search_google)
        if search_youtube:
            tools.append(self.search_youtube)

        super().__init__(name="serpapi_tools", tools=tools, **kwargs)

    def search_google(self, query: str, num_results: int = 10) -> str:
        """
        Search Google using the Serpapi API. Returns the search results.

        Args:
            query(str): The query to search for.
            num_results(int): The number of results to return.

        Returns:
            str: The search results from Google.
                Keys:
                    - 'search_results': List of organic search results.
                    - 'recipes_results': List of recipes search results.
                    - 'shopping_results': List of shopping search results.
                    - 'knowledge_graph': The knowledge graph.
                    - 'related_questions': List of related questions.
        """

        try:
            if not self.api_key:
                return "Please provide an API key"
            if not query:
                return "Please provide a query to search for"

            log_info(f"Searching Google for: {query}")

            params = {"q": query, "api_key": self.api_key, "num": num_results}

            search = serpapi.GoogleSearch(params)
            results = search.get_dict()

            filtered_results = {
                "search_results": results.get("organic_results", ""),
                "recipes_results": results.get("recipes_results", ""),
                "shopping_results": results.get("shopping_results", ""),
                "knowledge_graph": results.get("knowledge_graph", ""),
                "related_questions": results.get("related_questions", ""),
            }

            return json.dumps(filtered_results)

        except Exception as e:
            return f"Error searching for the query {query}: {e}"

    def search_youtube(self, query: str) -> str:
        """
        Search Youtube using the Serpapi API. Returns the search results.

        Args:
            query(str): The query to search for.

        Returns:
            str: The video search results from Youtube.
                Keys:
                    - 'video_results': List of video results.
                    - 'movie_results': List of movie results.
                    - 'channel_results': List of channel results.
        """

        try:
            if not self.api_key:
                return "Please provide an API key"
            if not query:
                return "Please provide a query to search for"

            log_info(f"Searching Youtube for: {query}")

            params = {"search_query": query, "api_key": self.api_key}

            search = serpapi.YoutubeSearch(params)
            results = search.get_dict()

            filtered_results = {
                "video_results": results.get("video_results", ""),
                "movie_results": results.get("movie_results", ""),
                "channel_results": results.get("channel_results", ""),
            }

            return json.dumps(filtered_results)

        except Exception as e:
            return f"Error searching for the query {query}: {e}"
