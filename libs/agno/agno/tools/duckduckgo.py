from typing import Literal, Optional

from agno.tools.websearch import WebSearchTools


class DuckDuckGoTools(WebSearchTools):
    """DuckDuckGoTools is a convenience wrapper around WebSearchTools with backend="duckduckgo".

    Args:
        search_web: Enable web search function. Defaults to True.
        search_news: Enable news search function. Defaults to True.
        modifier: A modifier to be prepended to search queries.
        fixed_max_results: A fixed number of maximum results.
        proxy: Proxy to be used for requests.
        timeout: The maximum number of seconds to wait for a response.
        verify_ssl: Whether to verify SSL certificates.
        timelimit: Time limit for search results ("d", "w", "m", "y").
        region: Region for search results (e.g., "us-en", "uk-en", "ru-ru").
        backend: Backend to use for searching. Defaults to "duckduckgo".
    """

    def __init__(
        self,
        search_web: bool = True,
        search_news: bool = True,
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
            search_web=search_web,
            search_news=search_news,
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
