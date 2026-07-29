import json
from typing import Callable, List, Literal, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    from ddgs import DDGS
except ImportError:
    raise ImportError("`ddgs` not installed. Please install using `pip install ddgs`")

# Valid timelimit values for search filtering
VALID_TIMELIMITS = frozenset({"d", "w", "m", "y"})


class WebSearchTools(Toolkit):
    """Toolkit for searching the web using the DDGS meta-search library.

    Multiple backends available: duckduckgo, google, bing, brave, yandex, yahoo, etc.

    Args:
        search_web: Enable search_web tool. Defaults to True.
        search_news: Enable search_news tool. Defaults to True.
        backend: Backend for searching. Defaults to "auto" (selects available).
        modifier: Modifier to prepend to search queries.
        fixed_max_results: Fixed number of maximum results.
        proxy: Proxy for requests.
        timeout: Maximum seconds to wait for a response.
        verify_ssl: Whether to verify SSL certificates.
        timelimit: Time limit for results ("d", "w", "m", "y").
        region: Region for results (e.g., "us-en", "uk-en").
        all: Enable all tools.
    """

    def __init__(
        self,
        search_web: bool = True,
        search_news: bool = True,
        backend: str = "auto",
        modifier: Optional[str] = None,
        fixed_max_results: Optional[int] = None,
        proxy: Optional[str] = None,
        timeout: Optional[int] = 10,
        verify_ssl: bool = True,
        timelimit: Optional[Literal["d", "w", "m", "y"]] = None,
        region: Optional[str] = None,
        all: bool = False,
        **kwargs,
    ):
        # Validate timelimit parameter
        if timelimit is not None and timelimit not in VALID_TIMELIMITS:
            raise ValueError(
                f"Invalid timelimit '{timelimit}'. Must be one of: 'd' (day), 'w' (week), 'm' (month), 'y' (year)."
            )

        self.proxy: Optional[str] = proxy
        self.timeout: Optional[int] = timeout
        self.fixed_max_results: Optional[int] = fixed_max_results
        self.modifier: Optional[str] = modifier
        self.verify_ssl: bool = verify_ssl
        self.backend: str = backend
        self.timelimit: Optional[Literal["d", "w", "m", "y"]] = timelimit
        self.region: Optional[str] = region

        tools: List[Callable] = []
        if all or search_web:
            tools.append(self.search_web)
        if all or search_news:
            tools.append(self.search_news)

        super().__init__(name="websearch", tools=tools, **kwargs)

    def search_web(self, query: str, max_results: int = 5) -> str:
        """Search the web for a query.

        Args:
            query: The query to search for.
            max_results: Maximum number of results to return.

        Returns:
            JSON array of search results.
        """
        actual_max_results = self.fixed_max_results or max_results
        search_query = f"{self.modifier} {query}" if self.modifier else query

        log_debug(f"Searching web for: {search_query} using backend: {self.backend}")
        search_kwargs: dict = {
            "query": search_query,
            "max_results": actual_max_results,
            "backend": self.backend,
        }
        if self.timelimit is not None:
            search_kwargs["timelimit"] = self.timelimit
        if self.region is not None:
            search_kwargs["region"] = self.region
        with DDGS(proxy=self.proxy, timeout=self.timeout, verify=self.verify_ssl) as ddgs:
            results = ddgs.text(**search_kwargs)

        return json.dumps(results, indent=2, ensure_ascii=False)

    def search_news(self, query: str, max_results: int = 5) -> str:
        """Search for the latest news on a topic.

        Args:
            query: The query to search for.
            max_results: Maximum number of results to return.

        Returns:
            JSON array of news results.
        """
        actual_max_results = self.fixed_max_results or max_results

        log_debug(f"Searching web news for: {query} using backend: {self.backend}")
        search_kwargs: dict = {
            "query": query,
            "max_results": actual_max_results,
            "backend": self.backend,
        }
        if self.timelimit is not None:
            search_kwargs["timelimit"] = self.timelimit
        if self.region is not None:
            search_kwargs["region"] = self.region
        with DDGS(proxy=self.proxy, timeout=self.timeout, verify=self.verify_ssl) as ddgs:
            results = ddgs.news(**search_kwargs)

        return json.dumps(results, indent=2, ensure_ascii=False)
