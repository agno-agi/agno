import json
from typing import Any, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    from duckduckgo_search import DDGS
except ImportError:
    raise ImportError("Please install `duckduckgo-search` using `pip install duckduckgo-search`")


class DuckDuckGoTools(Toolkit):
    """
    DuckDuckGoTools provides easy access to DuckDuckGo search and news.

    Args:
        allow_search (bool): Enables the general search functionality.
        enable_news (bool): Enables the news search functionality.
        request_modifier (Optional[str]): Text to prepend or append to each query.
        max_output (Optional[int]): Fixed number of maximum results to return.
        request_headers (Optional[Any]): Custom headers for HTTP requests.
        single_proxy (Optional[str]): Single proxy string.
        multiple_proxies (Optional[Any]): List of proxy configurations.
        request_timeout (Optional[int]): Timeout duration in seconds.
        ssl_check (bool): Whether to verify SSL certificates in the requests.
    """

    def __init__(
        self,
        allow_search: bool = True,
        enable_news: bool = True,
        request_modifier: Optional[str] = None,
        max_output: Optional[int] = None,
        request_headers: Optional[Any] = None,
        request_timeout: Optional[int] = 10,
        single_proxy: Optional[str] = None,
        multiple_proxies: Optional[Any] = None,
        ssl_check: bool = True,
        **kwargs,
    ):
        self.request_headers = request_headers
        self.single_proxy = single_proxy
        self.multiple_proxies = multiple_proxies
        self.request_timeout = request_timeout
        self.max_output = max_output
        self.request_modifier = request_modifier
        self.ssl_check = ssl_check

        toolset = []
        if allow_search:
            toolset.append(self.search_duckduckgo)
        if enable_news:
            toolset.append(self.fetch_duckduckgo_news)

        super().__init__(name="duckduckgo", tools=toolset, **kwargs)

    def search_duckduckgo(self, keyword: str, limit: int = 5) -> str:
        """
        Performs a web search using DuckDuckGo.

        Args:
            keyword (str): The search keyword or phrase.
            limit (int): Maximum number of results to return. Defaults to 5.

        Returns:
            str: A JSON-formatted string of the search results.
        """
        total = self.max_output or limit
        full_query = f"{self.request_modifier} {keyword}" if self.request_modifier else keyword

        log_debug(f"Initiating DuckDuckGo search: {full_query}")
        client = DDGS(
            headers=self.request_headers,
            proxy=self.single_proxy,
            proxies=self.multiple_proxies,
            timeout=self.request_timeout,
            verify=self.ssl_check
        )

        return json.dumps(client.text(keywords=full_query, max_results=total), indent=2)

    def fetch_duckduckgo_news(self, topic: str, limit: int = 5) -> str:
        """
        Fetches recent news from DuckDuckGo related to a topic.

        Args:
            topic (str): The topic to search news for.
            limit (int): Maximum number of news results to return. Defaults to 5.

        Returns:
            str: A JSON-formatted string of news results.
        """
        total = self.max_output or limit

        log_debug(f"Fetching DuckDuckGo news: {topic}")
        client = DDGS(
            headers=self.request_headers,
            proxy=self.single_proxy,
            proxies=self.multiple_proxies,
            timeout=self.request_timeout,
            verify=self.ssl_check
        )

        return json.dumps(client.news(keywords=topic, max_results=total), indent=2)
