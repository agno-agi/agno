from typing import Literal, Optional

from agno.tools.websearch import WebSearchTools


class DuckDuckGoTools(WebSearchTools):
    """
    DuckDuckGoTools is a convenience wrapper around WebSearchTools with the backend
    defaulting to "duckduckgo".
    Args:
        enable_search (bool): Enable web search function.
        enable_news (bool): Enable news search function.
        modifier (Optional[str]): A modifier to be prepended to search queries.
        fixed_max_results (Optional[int]): A fixed number of maximum results.
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
        modifier: Optional[str] = None,
        fixed_max_results: Optional[int] = None,
        fixed_timelimit: Optional[Literal["d", "w", "m", "y"]] = None,
        fixed_region: Optional[str] = None,
        proxy: Optional[str] = None,
        timeout: Optional[int] = 10,
        verify_ssl: bool = True,
        **kwargs,
    ):
        super().__init__(
            enable_search=enable_search,
            enable_news=enable_news,
            backend="duckduckgo",
            modifier=modifier,
            fixed_max_results=fixed_max_results,
            fixed_timelimit=fixed_timelimit,
            fixed_region=fixed_region,
            proxy=proxy,
            timeout=timeout,
            verify_ssl=verify_ssl,
            **kwargs,
        )

        # Backward compatibility aliases for old method names
        self.duckduckgo_search = self.web_search
        self.duckduckgo_news = self.search_news
