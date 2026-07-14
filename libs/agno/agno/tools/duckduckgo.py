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
        proxy (Optional[str]): Proxy to be used for requests.
        timeout (Optional[int]): The maximum number of seconds to wait for a response.
        verify_ssl (bool): Whether to verify SSL certificates.
        timelimit (Optional[str]): Time limit for search results. Valid values:
            "d" (day), "w" (week), "m" (month), "y" (year).
        region (Optional[str]): Region for search results (e.g., "us-en", "uk-en", "ru-ru").
        backend (Optional[str]): Backend to use for searching (e.g., "api", "html", "lite").
            Defaults to "duckduckgo".
    """

    def __init__(
        self,
        enable_search: bool = True,
        enable_news: bool = True,
        modifier: Optional[str] = None,
        fixed_max_results: Optional[int] = None,
        proxy: Optional[str] = None,
        timeout: Optional[int] = 10,
        verify_ssl: bool = True,
        timelimit: Optional[Literal["d", "w", "m", "y"]] = None,
        region: Optional[str] = None,
        backend: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(
            enable_search=enable_search,
            enable_news=enable_news,
            backend=backend or "duckduckgo",
            modifier=modifier,
            fixed_max_results=fixed_max_results,
            proxy=proxy,
            timeout=timeout,
            verify_ssl=verify_ssl,
            timelimit=timelimit,
            region=region,
            **kwargs,
        )

        # Backward compatibility aliases for old method names
        self.duckduckgo_search = self.web_search
        self.duckduckgo_news = self.search_news
