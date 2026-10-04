import json
from typing import Any, Dict, List, Literal, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException
except ImportError:
    raise ImportError("`ddgs` not installed. Please install using `pip install ddgs`")

# Valid timelimit values for search filtering
VALID_TIMELIMITS = frozenset({"d", "w", "m", "y"})


def _error_payload(query: str, exc: Exception) -> str:
    """Format an exception into a consistent JSON error string."""
    return json.dumps(
        {
            "error": type(exc).__name__,
            "message": str(exc),
            "query": query,
            "results": [],
        },
        indent=2,
        ensure_ascii=False,
    )


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
        timelimit (Optional[str]): Time limit for search results. Valid values:
            "d" (day), "w" (week), "m" (month), "y" (year).
        region (Optional[str]): Region for search results (e.g., "us-en", "uk-en", "ru-ru").
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
        timelimit: Optional[Literal["d", "w", "m", "y"]] = None,
        region: Optional[str] = None,
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

        tools: List[Any] = []
        if enable_search:
            tools.append(self.web_search)
        if enable_news:
            tools.append(self.search_news)

        super().__init__(name="websearch", tools=tools, **kwargs)

    def _resolve_max_results(self, requested: Optional[int]) -> Optional[int]:
        """Resolve the effective max_results taking fixed_max_results into account."""
        if self.fixed_max_results is not None:
            return self.fixed_max_results
        return requested

    def _build_query(self, query: str) -> str:
        """Prepend modifier to the search query if set."""
        return f"{self.modifier} {query}" if self.modifier else query

    def _build_search_kwargs(self, search_query: str, max_results: Optional[int]) -> Dict[str, Any]:
        """Build dictionary of kwargs for DDGS."""
        kwargs: Dict[str, Any] = {
            "query": search_query,
            "max_results": max_results,
            "backend": self.backend,
        }
        if self.timelimit is not None:
            kwargs["timelimit"] = self.timelimit
        if self.region is not None:
            kwargs["region"] = self.region
        return kwargs

    def web_search(self, query: str, max_results: Optional[int] = 5) -> str:
        """Use this function to search the web for a query.

        Args:
            query(str): The query to search for.
            max_results (optional, default=5): The maximum number of results to return.

        Returns:
            The search results from the web.
        """
        search_query = self._build_query(query)
        actual_max_results = self._resolve_max_results(max_results)

        if actual_max_results is not None and actual_max_results < 1:
            log_debug(f"Skipping web search: max_results={actual_max_results}")
            return json.dumps([], indent=2, ensure_ascii=False)

        log_debug(f"Searching web for: {search_query} using backend: {self.backend}")
        search_kwargs = self._build_search_kwargs(search_query, actual_max_results)

        try:
            with DDGS(proxy=self.proxy, timeout=self.timeout, verify=self.verify_ssl) as ddgs:
                results = ddgs.text(**search_kwargs)
            return json.dumps(results, indent=2, ensure_ascii=False)
        except (RatelimitException, TimeoutException, DDGSException) as e:
            log_error(f"Error searching web for '{search_query}': {e}")
            return _error_payload(search_query, e)
        except Exception as e:
            log_error(f"Unexpected error searching web for '{search_query}': {e}")
            return _error_payload(search_query, e)

    def search_news(self, query: str, max_results: Optional[int] = 5) -> str:
        """Use this function to get the latest news from the web.

        Args:
            query(str): The query to search for.
            max_results (optional, default=5): The maximum number of results to return.

        Returns:
            The latest news from the web.
        """
        search_query = self._build_query(query)
        actual_max_results = self._resolve_max_results(max_results)

        if actual_max_results is not None and actual_max_results < 1:
            log_debug(f"Skipping news search: max_results={actual_max_results}")
            return json.dumps([], indent=2, ensure_ascii=False)

        log_debug(f"Searching web news for: {search_query} using backend: {self.backend}")
        search_kwargs = self._build_search_kwargs(search_query, actual_max_results)

        try:
            with DDGS(proxy=self.proxy, timeout=self.timeout, verify=self.verify_ssl) as ddgs:
                results = ddgs.news(**search_kwargs)
            return json.dumps(results, indent=2, ensure_ascii=False)
        except (RatelimitException, TimeoutException, DDGSException) as e:
            log_error(f"Error searching web news for '{search_query}': {e}")
            return _error_payload(search_query, e)
        except Exception as e:
            log_error(f"Unexpected error searching web news for '{search_query}': {e}")
            return _error_payload(search_query, e)
