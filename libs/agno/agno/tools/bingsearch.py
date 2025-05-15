import json
import os
from typing import Any, Dict, Optional

import requests

from agno.tools.toolkit import Toolkit
from agno.utils.log import logger


class BingSearchTools(Toolkit):
    """
    A toolkit for performing various Bing Search API queries.

    Args:
        subscription_key (str): Subscription key for the Bing Search API.
        search (bool): Enable web search functionality.
        news (bool): Enable news search functionality.
        images (bool): Enable image search functionality.
        videos (bool): Enable video search functionality.
        modifier (Optional[str]): A string to prepend to each query (e.g., "site:example.com").
        fixed_max_results (Optional[int]): Fixed number of results to return (overrides max_results if set).
        headers (Optional[Dict[str, Any]]): Additional headers to include in API requests.
        proxy (Optional[str]): A single proxy URL.
        proxies (Optional[Dict[str, str]]): Dictionary of proxies (e.g., {"http": "...", "https": "..."}).
        timeout (Optional[int]): Maximum number of seconds to wait for a response (default: 10).
        verify_ssl (bool): Whether to verify SSL certificates.
        search_kwargs (Optional[dict]): Additional parameters for web search.
        search_endpoint (Optional[str]): Endpoint URL for the web search API.
        news_endpoint (Optional[str]): Endpoint URL for the news search API.
        images_endpoint (Optional[str]): Endpoint URL for the image search API.
        videos_endpoint (Optional[str]): Endpoint URL for the video search API.
    """

    def __init__(
        self,
        subscription_key: str,
        search: bool = True,
        news: bool = True,
        images: bool = True,
        videos: bool = True,
        modifier: Optional[str] = None,
        fixed_max_results: Optional[int] = None,
        headers: Optional[Dict[str, Any]] = None,
        proxy: Optional[str] = None,
        proxies: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = 10,
        verify_ssl: bool = True,
        search_kwargs: Optional[dict] = None,
        search_endpoint: Optional[str] = None,
        news_endpoint: Optional[str] = None,
        images_endpoint: Optional[str] = None,
        videos_endpoint: Optional[str] = None,
    ):
        super().__init__(name="bingsearch")
        subscription_key = subscription_key or os.environ.get("BING_SUBSCRIPTION_KEY")
        if not subscription_key:
            raise ValueError("subscription_key is required")
        self.subscription_key = subscription_key
        self.headers = headers or {}
        self.proxy = proxy
        self.proxies = proxies
        self.timeout = timeout
        self.fixed_max_results = fixed_max_results
        self.modifier = modifier
        self.verify_ssl = verify_ssl
        self.search_kwargs = search_kwargs or {}

        self.search_endpoint = search_endpoint or "https://api.bing.microsoft.com/v7.0/search"
        self.news_endpoint = news_endpoint or "https://api.bing.microsoft.com/v7.0/news/search"
        self.images_endpoint = images_endpoint or "https://api.bing.microsoft.com/v7.0/images/search"
        self.videos_endpoint = videos_endpoint or "https://api.bing.microsoft.com/v7.0/videos/search"

        # Use a requests.Session for connection reuse across multiple requests
        self.session = requests.Session()

        if search:
            self.register(self.bing_search)
        if news:
            self.register(self.bing_news)
        if images:
            self.register(self.bing_images)
        if videos:
            self.register(self.bing_videos)

    def _prepare_proxies(self) -> Optional[Dict[str, str]]:
        """
        Prepare a proxies dictionary for the requests.

        Returns:
            Optional[Dict[str, str]]: A dictionary with 'http' and 'https' keys if a proxy is set, otherwise None.
        """
        if self.proxies:
            return self.proxies
        elif self.proxy:
            return {"http": self.proxy, "https": self.proxy}
        return None

    def _build_headers(self) -> Dict[str, str]:
        """
        Build the headers for the API request.

        Returns:
            Dict[str, str]: A dictionary of headers including the subscription key.
        """
        base_headers = {"Ocp-Apim-Subscription-Key": self.subscription_key}
        base_headers.update(self.headers)
        return base_headers

    def _perform_request(self, endpoint: str, params: dict) -> dict:
        """
        Perform an API GET request with the specified endpoint and parameters.

        Args:
            endpoint (str): The API endpoint URL.
            params (dict): Query parameters for the request.

        Returns:
            dict: The JSON response from the API.

        Raises:
            requests.exceptions.RequestException: If the request fails.
        """
        headers = self._build_headers()
        proxies = self._prepare_proxies()
        try:
            response = self.session.get(
                endpoint,
                headers=headers,
                params=params,
                proxies=proxies,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise

    def _build_query(self, query: str) -> str:
        """
        Build the complete query by prepending the modifier if it is set.

        Args:
            query (str): The original search query.

        Returns:
            str: The modified search query.
        """
        return f"{self.modifier} {query}" if self.modifier else query

    def bing_search(self, query: str, max_results: int = 5) -> str:
        """
        Use this function to search Bing web search for query.
        This function returns JSON string containing simplified search results with metadata.

        Each search item includes:
        - title: The result title.
        - snippet: A short snippet of the result.
        - link: The URL to the result.
        - datePublished: Publication date. (if available).
        - deepLinks: A list of additional related links (if available).

        Args:
            query (str): The search query.
            max_results (int): The maximum number of results to return (overridden by fixed_max_results if set).

        Returns:
            str: A formatted JSON string of the web search results.
        """
        logger.debug(f"Searching Bing Web for: {query}")
        full_query = self._build_query(query)
        count = self.fixed_max_results or max_results
        params = {
            "q": full_query,
            "count": count,
            "textDecorations": True,
            "textFormat": "HTML",
            **self.search_kwargs,
        }
        search_results = self._perform_request(self.search_endpoint, params)
        if "webPages" not in search_results or "value" not in search_results["webPages"]:
            return json.dumps([{"Result": "No good Bing Search Result was found"}], indent=2)

        result_values = search_results["webPages"]["value"]
        results_list = []
        for result in result_values:
            item = {
                "title": result.get("name"),
                "snippet": result.get("snippet"),
                "link": result.get("url"),
            }
            if "datePublished" in result:
                item["datePublished"] = result["datePublished"]
            if "deepLinks" in result:
                item["deepLinks"] = [
                    {
                        "name": dl.get("name"),
                        "url": dl.get("url"),
                        "snippet": dl.get("snippet"),
                    }
                    for dl in result["deepLinks"]
                ]
            results_list.append(item)
        logger.debug(f"Found {len(results_list)} search results")
        return json.dumps(results_list, indent=2)

    def bing_news(
        self,
        query: str,
        max_results: int = 5,
        offset: int = 0,
        mkt: str = "en-US",
        safeSearch: str = "Moderate",
        sort_by: Optional[str] = None,
    ) -> str:
        """
        Use this function to search Bing news search for query.
        This function returns JSON string containing simplified search results with metadata.

        Each news item includes:
          - title: The news article title.
          - snippet: A short description.
          - link: URL to the full article.
          - provider: The name of the first provider if available.
          - datePublished: Publication date.
          - image: URL of the thumbnail image (if available).

        Args:
            query (str): The search query.
            max_results (int): Maximum number of results to return (overridden by fixed_max_results if set).
            offset (int): The offset for pagination.
            mkt (str): Market (e.g., "en-US").
            safeSearch (str): Safe search setting (e.g., "Moderate").
            sort_by (Optional[str]): Sorting order (e.g., "relevance" or "date").

        Returns:
            str: A formatted JSON string of the news search results.
        """
        logger.debug(f"Searching Bing News for: {query}")
        full_query = self._build_query(query)
        count = self.fixed_max_results or max_results
        params = {
            "q": full_query,
            "count": count,
            "offset": offset,
            "mkt": mkt,
            "safeSearch": safeSearch,
        }
        if sort_by:
            params["sortBy"] = sort_by
        news_results = self._perform_request(self.news_endpoint, params)
        if "value" not in news_results:
            return json.dumps([{"Result": "No Bing News result was found"}])
        results: list[dict[str, Any]] = []
        for article in news_results["value"]:
            results.append(
                {
                    "title": article.get("name"),
                    "snippet": article.get("description"),
                    "link": article.get("url"),
                    "provider": article.get("provider", [{}])[0].get("name") if article.get("provider") else None,
                    "datePublished": article.get("datePublished"),
                    "image": article.get("image", {}).get("thumbnail", {}).get("contentUrl")
                    if article.get("image")
                    else None,
                }
            )
        logger.debug(f"Found {len(results)} search results")
        return json.dumps(results, indent=2)

    def bing_images(
        self,
        query: str,
        max_results: int = 5,
        offset: int = 0,
        mkt: str = "en-US",
        safeSearch: str = "Moderate",
    ) -> str:
        """
        Use this function to search Bing image search for query.
        This function returns JSON string containing simplified search results with metadata.

        Each image item includes:
          - title: The image title.
          - link: Direct URL to the image.
          - thumbnail: URL to the thumbnail image.
          - hostPage: URL of the hosting page.
          - datePublished: The publication date (if available).
          - width: Image width.
          - height: Image height.

        Args:
            query (str): The search query.
            max_results (int): Maximum number of results to return (overridden by fixed_max_results if set).
            offset (int): The offset for pagination.
            mkt (str): Market (e.g., "en-US").
            safeSearch (str): Safe search setting (e.g., "Moderate").

        Returns:
            str: A formatted JSON string of the image search results.
        """
        logger.debug(f"Searching Bing Images for: {query}")
        full_query = self._build_query(query)
        count = self.fixed_max_results or max_results
        params = {
            "q": full_query,
            "count": count,
            "offset": offset,
            "mkt": mkt,
            "safeSearch": safeSearch,
        }
        image_results = self._perform_request(self.images_endpoint, params)
        if "value" not in image_results:
            return json.dumps([{"Result": "No Bing Images result was found"}])
        results: list[dict[str, Any]] = []
        for img in image_results["value"]:
            results.append(
                {
                    "title": img.get("name"),
                    "link": img.get("contentUrl"),
                    "thumbnail": img.get("thumbnailUrl"),
                    "hostPage": img.get("hostPageUrl"),
                    "datePublished": img.get("datePublished"),
                    "width": img.get("width"),
                    "height": img.get("height"),
                }
            )
        logger.debug(f"Found {len(results)} search results")
        return json.dumps(results, indent=2)

    def bing_videos(
        self,
        query: str,
        max_results: int = 5,
        offset: int = 0,
        mkt: str = "en-US",
        safeSearch: str = "Moderate",
        sort_by: Optional[str] = None,
    ) -> str:
        """
        Use this function to search Bing video search for query.
        This function returns JSON string containing simplified search results with metadata.

        Each video item includes:
          - title: The video title.
          - snippet: A short description.
          - link: URL to the video content.
          - thumbnail: URL to the video thumbnail.
          - duration: Video duration.
          - datePublished: Publication date.
          - viewCount: Number of views.

        Args:
            query (str): The search query.
            max_results (int): Maximum number of results to return (overridden by fixed_max_results if set).
            offset (int): The offset for pagination.
            mkt (str): Market (e.g., "en-US").
            safeSearch (str): Safe search setting (e.g., "Moderate").
            sort_by (Optional[str]): Sorting order if supported.

        Returns:
            str: A formatted JSON string of the video search results.
        """
        logger.debug(f"Searching Bing Videos for: {query}")
        full_query = self._build_query(query)
        count = self.fixed_max_results or max_results
        params = {
            "q": full_query,
            "count": count,
            "offset": offset,
            "mkt": mkt,
            "safeSearch": safeSearch,
        }
        if sort_by:
            params["sortBy"] = sort_by
        video_results = self._perform_request(self.videos_endpoint, params)
        if "value" not in video_results:
            return json.dumps([{"Result": "No Bing Videos result was found"}])
        results: list[dict[str, Any]] = []
        for vid in video_results["value"]:
            results.append(
                {
                    "title": vid.get("name"),
                    "snippet": vid.get("description"),
                    "link": vid.get("contentUrl"),
                    "thumbnail": vid.get("thumbnailUrl"),
                    "duration": vid.get("duration"),
                    "datePublished": vid.get("datePublished"),
                    "viewCount": vid.get("viewCount"),
                }
            )
        logger.debug(f"Found {len(results)} search results")
        return json.dumps(results, indent=2)
