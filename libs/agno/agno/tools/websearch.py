import json
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    from ddgs import DDGS
except ImportError:
    raise ImportError("`ddgs` not installed. Please install using `pip install ddgs`")


class WebSearchTools(Toolkit):
    """
    Toolkit for searching the web. Uses the meta-search library DDGS.
    Multiple search backends (e.g. google, bing, duckduckgo) are available.

    Args:
        enable_search (bool): Enable web search function.
        enable_news (bool): Enable news search function.
        backend (str): The backend to use for searching. Defaults to "auto" which
            automatically selects available backends. Other options include:
            "duckduckgo", "google", "bing", "brave", "yandex", "yahoo", etc.
        modifier (Optional[str]): A modifier to be prepended to search queries.
        fixed_max_results (Optional[int]): A fixed number of maximum results.
        proxy (Optional[str]): Proxy to be used for requests.
        timeout (Optional[int]): The maximum number of seconds to wait for a response.
        verify_ssl (bool): Whether to verify SSL certificates.
    """

    def __init__(
        self,
        enable_search: bool = True,
        enable_news: bool = True,
        backend: str = "auto",
        modifier: Optional[str] = None,
        fixed_max_results: Optional[int] = None,
        proxy: Optional[str] = None,
        timeout: Optional[int] = 10,
        verify_ssl: bool = True,
        **kwargs,
    ):
        self.proxy: Optional[str] = proxy
        self.timeout: Optional[int] = timeout
        self.fixed_max_results: Optional[int] = fixed_max_results
        self.modifier: Optional[str] = modifier
        self.verify_ssl: bool = verify_ssl
        self.backend: str = backend

        tools: List[Any] = []
        if enable_search:
            tools.append(self.web_search)
        if enable_news:
            tools.append(self.search_news)

        super().__init__(name="websearch", tools=tools, **kwargs)

    def web_search(self, query: str, max_results: int = 5) -> str:
        """Use this function to search the web for a query.

        Args:
            query(str): The query to search for.
            max_results (optional, default=5): The maximum number of results to return.

        Returns:
            The search results from the web.
        """
        actual_max_results = self.fixed_max_results or max_results
        search_query = f"{self.modifier} {query}" if self.modifier else query

        log_debug(f"Searching web for: {search_query} using backend: {self.backend}")
        with DDGS(proxy=self.proxy, timeout=self.timeout, verify=self.verify_ssl) as ddgs:
            results = ddgs.text(query=search_query, max_results=actual_max_results, backend=self.backend)

        return json.dumps(results, indent=2)

    def search_news(self, query: str, max_results: int = 5) -> str:
        """Use this function to get the latest news from the web.

        Args:
            query(str): The query to search for.
            max_results (optional, default=5): The maximum number of results to return.

        Returns:
            The latest news from the web.
        """
        actual_max_results = self.fixed_max_results or max_results

        log_debug(f"Searching web news for: {query} using backend: {self.backend}")
        with DDGS(proxy=self.proxy, timeout=self.timeout, verify=self.verify_ssl) as ddgs:
            results = ddgs.news(query=query, max_results=actual_max_results, backend=self.backend)

        return json.dumps(results, indent=2)
