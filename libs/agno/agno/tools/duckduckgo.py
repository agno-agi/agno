import json
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    from ddgs import DDGS
except ImportError:
    raise ImportError("`ddgs` not installed. Please install using `pip install ddgs`")


class DuckDuckGoTools(Toolkit):

    """
    DuckDuckGo is a toolkit for searching using DuckDuckGo easily.
    It uses the meta-search library DDGS, so it also has access to other backends.
    Args:
        enable_search (bool): Enable DDGS search function.
        enable_news (bool): Enable DDGS news function.
        modifier (Optional[str]): A modifier to be used in the search request.
        fixed_max_results (Optional[int]): A fixed number of maximum results.
        proxy (Optional[str]): Proxy to be used in the search request.
        timeout (Optional[int]): The maximum number of seconds to wait for a response.
        backend (Optional[str]): The backend to be used in the search request.
    """

    """
        fix for the errors, the ddgs package changed the names of backend engines from lowercase to upper case
            "text": {
            "bing": Bing,
            "brave": Brave,
            "duckduckgo": Duckduckgo,  # bing
            "google": Google,
            "mojeek": Mojeek,
            "mullvad_brave": MullvadLetaBrave,  # brave
            "mullvad_google": MullvadLetaGoogle,  # google
            "yahoo": Yahoo,  # bing
            "yandex": Yandex,
            "wikipedia": Wikipedia,
        },
        "images": {
            "duckduckgo": DuckduckgoImages,
        },
        "news": {
            "duckduckgo": DuckduckgoNews,
        },
        "videos": {
            "duckduckgo": DuckduckgoVideos,
        },
    """

    def __init__(
        self,
        enable_search: bool = True,
        enable_news: bool = True,
        all: bool = False,
        backend: str = "Duckduckgo",
        modifier: Optional[str] = None,
        fixed_max_results: Optional[int] = None,
        time_limit: str = "y",
        region: str = "us-en",
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
        self.time_limit: Optional[str] = time_limit
        self.region: Optional[str] =  region

        tools: List[Any] = []
        if all or enable_search:
            tools.append(self.duckduckgo_search)
        if all or enable_news:
            tools.append(self.duckduckgo_news)

        super().__init__(name="Duckduckgo", tools=tools, **kwargs)

    def duckduckgo_search(self, query: str, max_results: int = 5, time_limit: str = "y", region: str = "us-en") -> str:
        """Use this function to search DDGS for a query.

        Args:
            query(str): The query to search for.
            max_results (optional, default=5): The maximum number of results to return.

        Returns:
            The result from DDGS.
        """
        actual_max_results = self.fixed_max_results or max_results
        search_query = f"{self.modifier} {query}" if self.modifier else query
        time_limit = self.time_limit or time_limit
        region = self.region or region

        log_debug(f"Searching DDG for: {search_query} using backend: {self.backend}")
        with DDGS(proxy=self.proxy, timeout=self.timeout, verify=self.verify_ssl) as ddgs:
            results = ddgs.text(query=search_query, max_results=actual_max_results, backend=self.backend, timelimit=time_limit, region=region)

        return json.dumps(results, indent=2)

    def duckduckgo_news(self, query: str, max_results: int = 5, time_limit: str = "y", region: str = "us-en") -> str:
        """Use this function to get the latest news from DDGS.

        Args:
            query(str): The query to search for.
            max_results (optional, default=5): The maximum number of results to return.

        Returns:
            The latest news from DDGS.
        """
        actual_max_results = self.fixed_max_results or max_results
        time_limit = self.time_limit or time_limit
        region = self.region or region
        log_debug(f"Searching DDG news for: {query} using backend: {self.backend}")
        with DDGS(proxy=self.proxy, timeout=self.timeout, verify=self.verify_ssl) as ddgs:
            results = ddgs.news(query=query, max_results=actual_max_results, backend=self.backend, timelimit=time_limit, region=region)

        return json.dumps(results, indent=2)
