import json
from typing import Any, List, Literal, Optional

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
            automatically selects available backends. If set to a specific backend,
            it will override any backend parameter passed to search functions.
            Options: "auto", "duckduckgo", "google", "bing", "brave", "yandex", "yahoo", etc.
        modifier (Optional[str]): A modifier to be prepended to search queries.
        fixed_max_results (Optional[int]): A fixed number of maximum results. If set,
            overrides the max_results parameter in search functions.
        fixed_timelimit (Optional[str]): A fixed timelimit for results. Options: "d" (day),
            "w" (week), "m" (month), "y" (year). If set, overrides the timelimit parameter
            in search functions.
        fixed_region (Optional[str]): A fixed region for results. If set, overrides the
            region parameter in search functions.
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
        fixed_timelimit: Optional[Literal["d", "w", "m", "y"]] = None,
        fixed_region: Optional[str] = None,
        proxy: Optional[str] = None,
        timeout: Optional[int] = 10,
        verify_ssl: bool = True,
        **kwargs,
    ):
        self.proxy: Optional[str] = proxy
        self.timeout: Optional[int] = timeout
        self.fixed_max_results: Optional[int] = fixed_max_results
        self.fixed_timelimit: Optional[str] = fixed_timelimit
        self.fixed_region: Optional[str] = fixed_region
        self.backend: str = backend
        self.modifier: Optional[str] = modifier
        self.verify_ssl: bool = verify_ssl

        tools: List[Any] = []
        if enable_search:
            tools.append(self.web_search)
        if enable_news:
            tools.append(self.search_news)

        super().__init__(name="websearch", tools=tools, **kwargs)

    def web_search(
        self,
        query: str,
        max_results: int = 5,
        timelimit: Optional[Literal["d", "w", "m", "y"]] = None,
        region: str = "wt-wt",
        backend: str = "auto",
    ) -> str:
        """Use this function to search the web for a query.

        Args:
            query (str): The query to search for.
            max_results (int, optional): The maximum number of results to return. Defaults to 5.
            timelimit (str, optional): Time limit for results. Options:
                - "d": past day
                - "w": past week
                - "m": past month
                - "y": past year
                - None: no time limit (default)
            region (str, optional): Region for search results. Defaults to "wt-wt" (worldwide).
                Examples: "us-en" (US), "uk-en" (UK), "ko-kr" (Korea), "ja-jp" (Japan).
            backend (str, optional): Search backend to use. Defaults to "auto".
                Options: "auto", "duckduckgo", "google", "bing", "brave", "yandex", "yahoo".

        Returns:
            The search results from the web.
        """
        actual_max_results = self.fixed_max_results or max_results
        actual_timelimit = self.fixed_timelimit or timelimit
        actual_region = self.fixed_region or region
        actual_backend = self.backend if self.backend != "auto" else backend
        search_query = f"{self.modifier} {query}" if self.modifier else query

        log_debug(f"Searching web for: {search_query} using backend: {actual_backend}")
        with DDGS(proxy=self.proxy, timeout=self.timeout, verify=self.verify_ssl) as ddgs:
            results = ddgs.text(
                query=search_query,
                max_results=actual_max_results,
                timelimit=actual_timelimit,
                region=actual_region,
                backend=actual_backend,
            )

        return json.dumps(results, indent=2)

    def search_news(
        self,
        query: str,
        max_results: int = 5,
        timelimit: Optional[Literal["d", "w", "m", "y"]] = None,
        region: str = "wt-wt",
        backend: str = "auto",
    ) -> str:
        """Use this function to get the latest news from the web.

        Args:
            query (str): The query to search for.
            max_results (int, optional): The maximum number of results to return. Defaults to 5.
            timelimit (str, optional): Time limit for results. Options:
                - "d": past day
                - "w": past week
                - "m": past month
                - "y": past year
                - None: no time limit (default)
            region (str, optional): Region for search results. Defaults to "wt-wt" (worldwide).
                Examples: "us-en" (US), "uk-en" (UK), "ko-kr" (Korea), "ja-jp" (Japan).
            backend (str, optional): Search backend to use. Defaults to "auto".
                Options: "auto", "duckduckgo", "google", "bing", "brave", "yandex", "yahoo".

        Returns:
            The latest news from the web.
        """
        actual_max_results = self.fixed_max_results or max_results
        actual_timelimit = self.fixed_timelimit or timelimit
        actual_region = self.fixed_region or region
        actual_backend = self.backend if self.backend != "auto" else backend

        log_debug(f"Searching web news for: {query} using backend: {actual_backend}")
        with DDGS(proxy=self.proxy, timeout=self.timeout, verify=self.verify_ssl) as ddgs:
            results = ddgs.news(
                query=query,
                max_results=actual_max_results,
                timelimit=actual_timelimit,
                region=actual_region,
                backend=actual_backend,
            )

        return json.dumps(results, indent=2)
