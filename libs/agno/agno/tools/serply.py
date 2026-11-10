import json
from os import getenv
from typing import Any, Dict, List, Optional

import requests

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning


class SerplyTools(Toolkit):
    """
    SerplyTools is a toolkit for searching the web using the Serply API.

    Serply provides Google web, Google News, and Google Scholar results as JSON.
    Get an API key at https://serply.io and see https://serply.io/docs for the API.

    Args:
        api_key (Optional[str]): Serply API key. If not provided, uses SERPLY_API_KEY env var.
        num_results (int): Default number of results to return. Default is 10.
        timeout (int): Request timeout in seconds. Default is 30.
        search_web (bool): Enable Google web search. Default is True.
        search_news (bool): Enable Google News search. Default is False.
        search_scholar (bool): Enable Google Scholar search. Default is False.
        all (bool): If True, enable every search tool regardless of the individual flags.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        num_results: int = 10,
        timeout: int = 30,
        search_web: bool = True,
        search_news: bool = False,
        search_scholar: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("SERPLY_API_KEY")
        if not self.api_key:
            log_warning("No Serply API key provided. Set the SERPLY_API_KEY environment variable.")

        self.num_results = num_results
        self.timeout = timeout
        self.base_url = "https://api.serply.io/v1"

        tools: List[Any] = []
        if all or search_web:
            tools.append(self.search_web)
        if all or search_news:
            tools.append(self.search_news)
        if all or search_scholar:
            tools.append(self.search_scholar)

        super().__init__(name="serply_tools", tools=tools, **kwargs)

    def _make_request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Makes a GET request to the Serply API.

        Args:
            endpoint (str): The API endpoint, e.g. "search", "news" or "scholar".
            params (Dict[str, Any]): Query parameters.

        Returns:
            Dict[str, Any]: The parsed JSON response or an error dict.
        """
        try:
            if not self.api_key:
                return {"error": "No Serply API key provided. Set the SERPLY_API_KEY environment variable."}

            headers = {
                "X-Api-Key": self.api_key,
                "Accept": "application/json",
                "User-Agent": "agno",
            }

            log_debug(f"Requesting Serply endpoint={endpoint} q={params.get('q')}")
            response = requests.get(
                f"{self.base_url}/{endpoint}/", headers=headers, params=params, timeout=self.timeout
            )
            response.raise_for_status()

            return response.json()  # type: ignore[no-any-return]
        except requests.exceptions.HTTPError as e:
            log_error(f"Serply HTTP error: {e}")
            return {"error": f"HTTP error: {e}"}
        except requests.exceptions.RequestException as e:
            log_error(f"Serply request error: {e}")
            return {"error": str(e)}
        except ValueError as e:
            log_error(f"Serply JSON decode error: {e}")
            return {"error": f"Invalid JSON response: {e}"}

    def _params(self, query: str, num_results: Optional[int]) -> Dict[str, Any]:
        return {
            "q": query,
            "num": num_results if num_results is not None else self.num_results,
        }

    def search_web(self, query: str, num_results: Optional[int] = None) -> str:
        """
        Search Google for the given query using Serply.

        Args:
            query (str): The search query.
            num_results (Optional[int]): Number of results to return. Defaults to instance setting.

        Returns:
            str: JSON string containing organic results and related searches.
        """
        if not query:
            return json.dumps({"error": "Please provide a query to search for"})

        log_debug(f"Searching Google for: {query}")

        data = self._make_request("search", self._params(query, num_results))

        if "error" in data:
            return json.dumps({"error": data["error"]})

        result = {
            "results": [
                {
                    "position": r.get("position"),
                    "title": r.get("title"),
                    "link": r.get("link"),
                    "description": r.get("description"),
                }
                for r in data.get("results", [])
            ],
            "related_searches": data.get("related_searches", []),
        }

        return json.dumps(result, indent=2)

    def search_news(self, query: str, num_results: Optional[int] = None) -> str:
        """
        Search Google News for the given query using Serply.

        Args:
            query (str): The search query.
            num_results (Optional[int]): Number of results to return. Defaults to instance setting.

        Returns:
            str: JSON string containing news articles with title, link, source and publish date.
        """
        if not query:
            return json.dumps({"error": "Please provide a query to search for"})

        log_debug(f"Searching Google News for: {query}")

        params = self._params(query, num_results)
        data = self._make_request("news", params)

        if "error" in data:
            return json.dumps({"error": data["error"]})

        # The news endpoint returns the full feed regardless of num, so trim here.
        result = {
            "news_results": [
                {
                    "title": e.get("title"),
                    "link": e.get("link"),
                    "source": (e.get("source") or {}).get("title"),
                    "published": e.get("published"),
                }
                for e in data.get("entries", [])[: params["num"]]
            ]
        }

        return json.dumps(result, indent=2)

    def search_scholar(self, query: str, num_results: Optional[int] = None) -> str:
        """
        Search Google Scholar for academic papers using Serply.

        Args:
            query (str): The search query.
            num_results (Optional[int]): Number of results to return. Defaults to instance setting.

        Returns:
            str: JSON string containing papers with title, link, authors, citation count and PDF link.
        """
        if not query:
            return json.dumps({"error": "Please provide a query to search for"})

        log_debug(f"Searching Google Scholar for: {query}")

        data = self._make_request("scholar", self._params(query, num_results))

        if "error" in data:
            return json.dumps({"error": data["error"]})

        result = {
            "scholar_results": [
                {
                    "title": a.get("title"),
                    "link": a.get("link"),
                    "description": a.get("description"),
                    "authors": (a.get("author") or {}).get("names"),
                    "citations": ((a.get("extras") or {}).get("citations") or {}).get("count"),
                    "pdf": (a.get("doc") or {}).get("link"),
                }
                for a in data.get("articles", [])
            ]
        }

        return json.dumps(result, indent=2)
