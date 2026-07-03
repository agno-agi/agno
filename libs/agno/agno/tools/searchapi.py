import json
from os import getenv
from typing import Any, Dict, List, Optional

import requests

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning


class SearchApiTools(Toolkit):
    """
    SearchApiTools is a toolkit for searching the web using the SearchAPI.io API.

    SearchAPI provides real-time SERP data for Google, Google News, Google Images,
    YouTube, and more.

    Args:
        api_key (Optional[str]): SearchAPI key. If not provided, uses SEARCHAPI_API_KEY env var.
        num_results (int): Default number of results to return. Default is 5.
        timeout (int): Request timeout in seconds. Default is 30.
        enable_search_google (bool): Enable Google web search. Default is True.
        enable_search_news (bool): Enable Google News search. Default is False.
        enable_search_images (bool): Enable Google Images search. Default is False.
        enable_search_youtube (bool): Enable YouTube search. Default is False.
        all (bool): If True, enable every search engine regardless of the individual flags.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        num_results: int = 5,
        timeout: int = 30,
        enable_search_google: bool = True,
        enable_search_news: bool = False,
        enable_search_images: bool = False,
        enable_search_youtube: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("SEARCHAPI_API_KEY")
        if not self.api_key:
            log_warning("No SearchAPI key provided. Set the SEARCHAPI_API_KEY environment variable.")

        self.num_results = num_results
        self.timeout = timeout
        self.base_url = "https://www.searchapi.io/api/v1/search"

        tools: List[Any] = []
        if all or enable_search_google:
            tools.append(self.search_google)
        if all or enable_search_news:
            tools.append(self.search_news)
        if all or enable_search_images:
            tools.append(self.search_images)
        if all or enable_search_youtube:
            tools.append(self.search_youtube)

        super().__init__(name="searchapi_tools", tools=tools, **kwargs)

    def _make_request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Makes a GET request to the SearchAPI.io API.

        Args:
            params (Dict[str, Any]): Query parameters including engine and search terms.

        Returns:
            Dict[str, Any]: The parsed JSON response or an error dict.
        """
        try:
            if not self.api_key:
                return {"error": "No SearchAPI key provided. Set the SEARCHAPI_API_KEY environment variable."}

            request_params = {**params, "api_key": self.api_key}

            log_debug(f"Requesting SearchAPI engine={params.get('engine')} q={params.get('q')}")
            response = requests.get(self.base_url, params=request_params, timeout=self.timeout)
            response.raise_for_status()

            return response.json()  # type: ignore[no-any-return]
        except requests.exceptions.HTTPError as e:
            log_error(f"SearchAPI HTTP error: {e}")
            return {"error": f"HTTP error: {e}"}
        except requests.exceptions.RequestException as e:
            log_error(f"SearchAPI request error: {e}")
            return {"error": str(e)}
        except ValueError as e:
            log_error(f"SearchAPI JSON decode error: {e}")
            return {"error": f"Invalid JSON response: {e}"}

    def search_google(
        self,
        query: str,
        num_results: Optional[int] = None,
        location: Optional[str] = None,
        language: Optional[str] = None,
    ) -> str:
        """
        Search Google for the given query using SearchAPI.

        Args:
            query (str): The search query.
            num_results (Optional[int]): Number of results to return. Defaults to instance setting.
            location (Optional[str]): Location for localized results, e.g. "New York,United States".
            language (Optional[str]): Language code for results, e.g. "en".

        Returns:
            str: JSON string containing organic results, knowledge graph, and related questions.
        """
        if not query:
            return json.dumps({"error": "Please provide a query to search for"})

        log_debug(f"Searching Google for: {query}")

        params: Dict[str, Any] = {
            "engine": "google",
            "q": query,
            "num": num_results or self.num_results,
        }
        if location:
            params["location"] = location
        if language:
            params["hl"] = language

        data = self._make_request(params)

        if "error" in data:
            return json.dumps({"error": data["error"]})

        result = {
            "organic_results": [
                {
                    "position": r.get("position"),
                    "title": r.get("title"),
                    "link": r.get("link"),
                    "snippet": r.get("snippet"),
                    "source": r.get("source"),
                }
                for r in data.get("organic_results", [])
            ],
            "knowledge_graph": data.get("knowledge_graph"),
            "related_questions": [
                {"question": q.get("question"), "snippet": q.get("snippet")} for q in data.get("related_questions", [])
            ],
            "search_information": data.get("search_information"),
        }

        return json.dumps(result, indent=2)

    def search_news(
        self,
        query: str,
        num_results: Optional[int] = None,
        language: Optional[str] = None,
        country: Optional[str] = None,
    ) -> str:
        """
        Search Google News for the given query using SearchAPI.

        Args:
            query (str): The news search query.
            num_results (Optional[int]): Number of results to return. Defaults to instance setting.
            language (Optional[str]): Language code for results, e.g. "en".
            country (Optional[str]): Country code for results, e.g. "us".

        Returns:
            str: JSON string containing news articles with title, link, source, and date.
        """
        if not query:
            return json.dumps({"error": "Please provide a query to search for"})

        log_debug(f"Searching Google News for: {query}")

        params: Dict[str, Any] = {
            "engine": "google_news",
            "q": query,
            "num": num_results or self.num_results,
        }
        if language:
            params["hl"] = language
        if country:
            params["gl"] = country

        data = self._make_request(params)

        if "error" in data:
            return json.dumps({"error": data["error"]})

        result = {
            "news_results": [
                {
                    "position": r.get("position"),
                    "title": r.get("title"),
                    "link": r.get("link"),
                    "source": r.get("source", {}).get("name") if isinstance(r.get("source"), dict) else r.get("source"),
                    "date": r.get("date"),
                    "snippet": r.get("snippet"),
                    "thumbnail": r.get("thumbnail"),
                }
                for r in data.get("news_results", [])
            ]
        }

        return json.dumps(result, indent=2)

    def search_images(
        self,
        query: str,
        num_results: Optional[int] = None,
        safe_search: Optional[str] = None,
    ) -> str:
        """
        Search Google Images for the given query using SearchAPI.

        Args:
            query (str): The image search query.
            num_results (Optional[int]): Number of results to return. Defaults to instance setting.
            safe_search (Optional[str]): Safe search setting: "active" or "off".

        Returns:
            str: JSON string containing image results with title, link, and thumbnail.
        """
        if not query:
            return json.dumps({"error": "Please provide a query to search for"})

        log_debug(f"Searching Google Images for: {query}")

        params: Dict[str, Any] = {
            "engine": "google_images",
            "q": query,
            "num": num_results or self.num_results,
        }
        if safe_search:
            params["safe"] = safe_search

        data = self._make_request(params)

        if "error" in data:
            return json.dumps({"error": data["error"]})

        result = {
            "image_results": [
                {
                    "position": r.get("position"),
                    "title": r.get("title"),
                    "link": r.get("link"),
                    "original": r.get("original"),
                    "thumbnail": r.get("thumbnail"),
                    "source": r.get("source"),
                }
                for r in data.get("image_results", [])
            ]
        }

        return json.dumps(result, indent=2)

    def search_youtube(
        self,
        query: str,
        num_results: Optional[int] = None,
    ) -> str:
        """
        Search YouTube for the given query using SearchAPI.

        Args:
            query (str): The YouTube search query.
            num_results (Optional[int]): Maximum number of results to return. SearchAPI's
                YouTube engine has no server-side count parameter (it paginates via
                next_page_token), so this is applied client-side by slicing the response.

        Returns:
            str: JSON string containing video results with title, link, channel, length, views,
                published_time, description, and thumbnail.
        """
        if not query:
            return json.dumps({"error": "Please provide a query to search for"})

        log_debug(f"Searching YouTube for: {query}")

        params: Dict[str, Any] = {
            "engine": "youtube",
            "q": query,
        }

        data = self._make_request(params)

        if "error" in data:
            return json.dumps({"error": data["error"]})

        limit = num_results or self.num_results
        videos = data.get("videos", []) or []
        result = {
            "video_results": [
                {
                    "position": r.get("position"),
                    "id": r.get("id"),
                    "title": r.get("title"),
                    "link": r.get("link"),
                    "channel": r.get("channel", {}).get("title")
                    if isinstance(r.get("channel"), dict)
                    else r.get("channel"),
                    "length": r.get("length"),
                    "views": r.get("views"),
                    "published_time": r.get("published_time"),
                    "description": r.get("description"),
                    "thumbnail": r.get("thumbnail", {}).get("static")
                    if isinstance(r.get("thumbnail"), dict)
                    else r.get("thumbnail"),
                }
                for r in videos[:limit]
            ]
        }

        return json.dumps(result, indent=2)
