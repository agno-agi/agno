import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, logger

try:
    from scavio import ScavioClient
except ImportError:
    raise ImportError("`scavio` not installed. Please install using `pip install scavio`")


class ScavioTools(Toolkit):
    """Scavio is a unified Search API for AI agents covering Google, YouTube,
    Amazon, Walmart, Reddit, TikTok, and Instagram.

    Args:
        api_key: Scavio API key. Retrieved from SCAVIO_API_KEY env variable if not provided.
        enable_google: Enable Google web search. Default is True.
        enable_youtube: Enable YouTube search. Default is False.
        enable_amazon: Enable Amazon product search. Default is False.
        enable_walmart: Enable Walmart product search. Default is False.
        enable_reddit: Enable Reddit search. Default is False.
        enable_tiktok: Enable TikTok search. Default is False.
        enable_instagram: Enable Instagram search. Default is False.
        all: Enable all tools. Overrides individual flags when True. Default is False.
        max_results: Default maximum number of results to include in tool output. Default is 5.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_google: bool = True,
        enable_youtube: bool = False,
        enable_amazon: bool = False,
        enable_walmart: bool = False,
        enable_reddit: bool = False,
        enable_tiktok: bool = False,
        enable_instagram: bool = False,
        all: bool = False,
        max_results: int = 5,
        **kwargs,
    ):
        self.api_key = api_key or getenv("SCAVIO_API_KEY")
        if not self.api_key:
            log_error("SCAVIO_API_KEY not provided")
            raise ValueError(
                "No Scavio API key provided. Please provide an api_key or set the SCAVIO_API_KEY environment variable."
            )

        self.client = ScavioClient(api_key=self.api_key)
        self.max_results = max_results

        tools: List[Any] = []
        if all or enable_google:
            tools.append(self.google_search)
        if all or enable_youtube:
            tools.append(self.youtube_search)
        if all or enable_amazon:
            tools.append(self.amazon_search)
        if all or enable_walmart:
            tools.append(self.walmart_search)
        if all or enable_reddit:
            tools.append(self.reddit_search)
        if all or enable_tiktok:
            tools.append(self.tiktok_search)
        if all or enable_instagram:
            tools.append(self.instagram_search)

        super().__init__(name="scavio_tools", tools=tools, **kwargs)

    def google_search(
        self,
        query: str,
        country_code: Optional[str] = None,
        language: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> str:
        """Search the web using Google via Scavio.

        Args:
            query (str): The search query.
            country_code (Optional[str]): Two-letter country code for localized results.
            language (Optional[str]): Two-letter language code.
            max_results (Optional[int]): Maximum number of results to return.

        Returns:
            str: Search results formatted as JSON.
        """
        try:
            response = self.client.google.search(
                query,
                country_code=country_code,
                language=language,
            )
            return self._format_google_results(response, max_results or self.max_results)
        except Exception as e:
            logger.exception(f"Error searching Google for: {query}")
            return f"Error searching Google: {e}"

    def youtube_search(
        self,
        query: str,
        sort_by: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> str:
        """Search YouTube videos via Scavio.

        Args:
            query (str): The search query.
            sort_by (Optional[str]): Sort order - 'relevance', 'date', 'views', or 'rating'.
            max_results (Optional[int]): Maximum number of results to return.

        Returns:
            str: Search results formatted as JSON.
        """
        try:
            response = self.client.youtube.search(query, sort_by=sort_by)
            return self._format_youtube_results(response, max_results or self.max_results)
        except Exception as e:
            logger.exception(f"Error searching YouTube for: {query}")
            return f"Error searching YouTube: {e}"

    def amazon_search(
        self,
        query: str,
        domain: Optional[str] = None,
        sort_by: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> str:
        """Search Amazon products via Scavio.

        Args:
            query (str): The search query.
            domain (Optional[str]): Amazon domain (e.g., 'com', 'co.uk', 'de').
            sort_by (Optional[str]): Sort order for results.
            max_results (Optional[int]): Maximum number of results to return.

        Returns:
            str: Search results formatted as JSON.
        """
        try:
            response = self.client.amazon.search(query, domain=domain, sort_by=sort_by)
            return self._format_results(response, max_results or self.max_results)
        except Exception as e:
            logger.exception(f"Error searching Amazon for: {query}")
            return f"Error searching Amazon: {e}"

    def walmart_search(
        self,
        query: str,
        sort_by: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> str:
        """Search Walmart products via Scavio.

        Args:
            query (str): The search query.
            sort_by (Optional[str]): Sort order for results.
            max_results (Optional[int]): Maximum number of results to return.

        Returns:
            str: Search results formatted as JSON.
        """
        try:
            response = self.client.walmart.search(query, sort_by=sort_by)
            return self._format_results(response, max_results or self.max_results)
        except Exception as e:
            logger.exception(f"Error searching Walmart for: {query}")
            return f"Error searching Walmart: {e}"

    def reddit_search(
        self,
        query: str,
        sort: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> str:
        """Search Reddit posts via Scavio.

        Args:
            query (str): The search query.
            sort (Optional[str]): Sort order - 'relevance', 'hot', 'top', 'new', or 'comments'.
            max_results (Optional[int]): Maximum number of results to return.

        Returns:
            str: Search results formatted as JSON.
        """
        try:
            response = self.client.reddit.search(query, sort=sort)
            return self._format_results(response, max_results or self.max_results)
        except Exception as e:
            logger.exception(f"Error searching Reddit for: {query}")
            return f"Error searching Reddit: {e}"

    def tiktok_search(
        self,
        query: str,
        sort_type: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> str:
        """Search TikTok videos via Scavio.

        Args:
            query (str): The search query.
            sort_type (Optional[str]): Sort type for results.
            max_results (Optional[int]): Maximum number of results to return.

        Returns:
            str: Search results formatted as JSON.
        """
        try:
            response = self.client.tiktok.search_videos(query, sort_type=sort_type)
            return self._format_results(response, max_results or self.max_results)
        except Exception as e:
            logger.exception(f"Error searching TikTok for: {query}")
            return f"Error searching TikTok: {e}"

    def instagram_search(
        self,
        query: str,
        max_results: Optional[int] = None,
    ) -> str:
        """Search Instagram users via Scavio.

        Args:
            query (str): The search query (username or keyword).
            max_results (Optional[int]): Maximum number of results to return.

        Returns:
            str: Search results formatted as JSON.
        """
        try:
            response = self.client.instagram.search_users(query)
            return self._format_results(response, max_results or self.max_results)
        except Exception as e:
            logger.exception(f"Error searching Instagram for: {query}")
            return f"Error searching Instagram: {e}"

    @staticmethod
    def _format_google_results(response: Dict[str, Any], max_results: int) -> str:
        """Format Google search results."""
        results = response.get("organic_results", response.get("results", []))
        limited = results[:max_results]

        output: Dict[str, Any] = {}
        if response.get("answer_box"):
            output["answer_box"] = response["answer_box"]

        formatted = []
        for r in limited:
            formatted.append(
                {
                    "title": r.get("title"),
                    "url": r.get("link") or r.get("url"),
                    "snippet": r.get("snippet") or r.get("description"),
                }
            )
        output["results"] = formatted
        return json.dumps(output, indent=2)

    @staticmethod
    def _format_youtube_results(response: Dict[str, Any], max_results: int) -> str:
        """Format YouTube search results."""
        results = response.get("video_results", response.get("results", []))
        limited = results[:max_results]

        formatted = []
        for r in limited:
            formatted.append(
                {
                    "title": r.get("title"),
                    "url": r.get("link") or r.get("url"),
                    "channel": r.get("channel", {}).get("name")
                    if isinstance(r.get("channel"), dict)
                    else r.get("channel"),
                    "views": r.get("views"),
                    "published": r.get("published_date") or r.get("published"),
                }
            )
        return json.dumps({"results": formatted}, indent=2)

    @staticmethod
    def _format_results(response: Dict[str, Any], max_results: int) -> str:
        """Generic result formatter for any Scavio endpoint."""
        if isinstance(response, list):
            limited = response[:max_results]
            return json.dumps({"results": limited}, indent=2)

        for key in ("results", "items", "data", "posts", "products", "videos", "users"):
            if key in response and isinstance(response[key], list):
                limited = response[key][:max_results]
                return json.dumps({"results": limited}, indent=2)

        return json.dumps(response, indent=2)
