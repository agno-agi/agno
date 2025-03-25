import json
from typing import Any, Optional

from agno.tools import Toolkit
from agno.utils.functions import cache_result
from agno.utils.log import log_debug

try:
    from duckduckgo_search import DDGS
except ImportError:
    raise ImportError("`duckduckgo-search` not installed. Please install using `pip install duckduckgo-search`")


class DuckDuckGoTools(Toolkit):
    """
    DuckDuckGo is a toolkit for searching DuckDuckGo easily.
    Args:
        search (bool): Enable DuckDuckGo search function.
        news (bool): Enable DuckDuckGo news function.
        modifier (Optional[str]): A modifier to be used in the search request.
        fixed_max_results (Optional[int]): A fixed number of maximum results.
        headers (Optional[Any]): Headers to be used in the search request.
        proxy (Optional[str]): Proxy to be used in the search request.
        proxies (Optional[Any]): A list of proxies to be used in the search request.
        timeout (Optional[int]): The maximum number of seconds to wait for a response.
        cache_results (bool): Enable in-memory caching of search results.
        cache_ttl (int): Time-to-live for cached results in seconds.
        cache_dir (Optional[str]): Directory to store cache files. Defaults to system temp dir.

    """

    def __init__(
        self,
        search: bool = True,
        news: bool = True,
        modifier: Optional[str] = None,
        fixed_max_results: Optional[int] = None,
        headers: Optional[Any] = None,
        proxy: Optional[str] = None,
        proxies: Optional[Any] = None,
        timeout: Optional[int] = 10,
        verify_ssl: bool = True,
        cache_results: bool = False,
        cache_ttl: int = 3600,
        cache_dir: Optional[str] = None,
    ):
        super().__init__(name="duckduckgo")

        self.headers: Optional[Any] = headers
        self.proxy: Optional[str] = proxy
        self.proxies: Optional[Any] = proxies
        self.timeout: Optional[int] = timeout
        self.fixed_max_results: Optional[int] = fixed_max_results
        self.modifier: Optional[str] = modifier
        self.verify_ssl: bool = verify_ssl
        self.cache_results: bool = cache_results
        self.cache_ttl: int = cache_ttl
        self.cache_dir: Optional[str] = cache_dir

        if search:
            self.register(self.duckduckgo_search)
        if news:
            self.register(self.duckduckgo_news)

    @cache_result()
    def duckduckgo_search(self, query: str, max_results: int = 5) -> str:
        """Use this function to search DuckDuckGo for a query.

        Args:
            query(str): The query to search for.
            max_results (optional, default=5): The maximum number of results to return.

        Returns:
            The result from DuckDuckGo.
        """
        actual_max_results = self.fixed_max_results or max_results
        search_query = f"{self.modifier} {query}" if self.modifier else query

        log_debug(f"Searching DDG for: {search_query}")
        ddgs = DDGS(
            headers=self.headers, proxy=self.proxy, proxies=self.proxies, timeout=self.timeout, verify=self.verify_ssl
        )

        return json.dumps(ddgs.text(keywords=search_query, max_results=actual_max_results), indent=2)

    @cache_result()
    def duckduckgo_news(self, query: str, max_results: int = 5) -> str:
        """Use this function to get the latest news from DuckDuckGo.

        Args:
            query(str): The query to search for.
            max_results (optional, default=5): The maximum number of results to return.

        Returns:
            The latest news from DuckDuckGo.
        """
        actual_max_results = self.fixed_max_results or max_results

        log_debug(f"Searching DDG news for: {query}")
        ddgs = DDGS(
            headers=self.headers, proxy=self.proxy, proxies=self.proxies, timeout=self.timeout, verify=self.verify_ssl
        )

        return json.dumps(ddgs.news(keywords=query, max_results=actual_max_results), indent=2)
