import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional

from agno.tools.toolkit import Toolkit
from agno.utils.log import logger

# Try to get agno version for tracking
try:
    from importlib.metadata import version as get_version

    AGNO_VERSION = get_version("agno")
except Exception:
    AGNO_VERSION = "unknown"

try:
    from nimble_python import AsyncNimble, Nimble
except ImportError:
    raise ImportError("`nimble_python` not installed. Please install using `pip install nimble_python`")


class NimbleTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_search: bool = True,
        all: bool = False,
        locale: str = "en",
        country: str = "US",
        output_format: Literal["markdown", "plain_text", "simplified_html"] = "markdown",
        **kwargs,
    ):
        """Initialize NimbleTools with web search capabilities.

        Provides real-time web search powered by the Nimble Search API with support
        for deep content extraction and LLM-generated answer summaries.

        Args:
            api_key: Nimble API key. If not provided, will use NIMBLE_API_KEY env var.
            enable_search: Enable web search functionality. Defaults to True.
            all: Enable all available tools. Defaults to False.
            locale: Locale for search results (e.g., "en", "es"). Defaults to "en".
            country: Country code for search results (e.g., "US", "GB"). Defaults to "US".
            output_format: Output format - "markdown", "plain_text", or "simplified_html". Defaults to "markdown".
            **kwargs: Additional arguments passed to Toolkit.
        """
        self.api_key = api_key or getenv("NIMBLE_API_KEY")
        if not self.api_key:
            logger.error("NIMBLE_API_KEY not provided")

        # Initialize clients
        self.client: Nimble = Nimble(api_key=self.api_key)
        self.async_client: AsyncNimble = AsyncNimble(api_key=self.api_key)

        # Store configuration (only things that rarely change per call)
        self.locale: str = locale
        self.country: str = country
        self.output_format: Literal["markdown", "plain_text", "simplified_html"] = output_format

        # Register tools
        tools: List[Any] = []
        if enable_search or all:
            tools.append(self.web_search_using_nimble)

        super().__init__(name="nimble_tools", tools=tools, **kwargs)

    def web_search_using_nimble(
        self,
        query: str,
        max_results: int = 3,
        deep_search: bool = False,
        include_answer: bool = False,
        time_range: Optional[Literal["hour", "day", "week", "month", "year"]] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> str:
        """Search the web for real-time information using Nimble's search API.

        Choose the right mode:
        - Fast Mode (deep_search=False, default): Best for URL discovery and quick answers.
          Returns concise, token-efficient results perfect for agentic loops and initial research.
        - Deep Search (deep_search=True): Use when you need comprehensive full-page content
          for in-depth analysis, extracting detailed information, or reading entire articles.

        Args:
            query: Search query string.
            max_results: Number of results to return (1-100). Defaults to 3.
            deep_search: Enable full-page content extraction. Defaults to False (fast mode).
            include_answer: Generate an LLM-powered summary answer. Defaults to False.
            time_range: Filter by recency - "hour", "day", "week", "month", "year".
                       Use for time-sensitive queries like "latest news" or "recent updates".
            include_domains: Restrict search to specific domains (e.g., ["github.com", "docs.python.org"]).
            exclude_domains: Exclude specific domains from results.

        Returns:
            JSON string with search results formatted according to output_format setting.
        """
        try:
            # Build search parameters
            search_params: Dict[str, Any] = {
                "query": query,
                "num_results": max_results,
                "deep_search": deep_search,
                "include_answer": include_answer,
                "locale": self.locale,
                "country": self.country,
                "parsing_type": self.output_format,
            }

            # Add optional parameters if specified
            if time_range:
                search_params["time_range"] = time_range
            if include_domains:
                search_params["include_domains"] = include_domains
            if exclude_domains:
                search_params["exclude_domains"] = exclude_domains

            # Call Nimble Search API with tracking headers
            response = self.client.search(
                **search_params,
                extra_headers={
                    "X-Client-Source": "agno-tools",
                    "X-Client-Tool": "NimbleTools",
                    "X-Client-Version": AGNO_VERSION,
                },
            )

            # Return the response as JSON
            return json.dumps(response.model_dump(), indent=2)

        except Exception as e:
            logger.error(f"Error searching with Nimble: {e}")
            return json.dumps({"error": f"Search failed: {str(e)}"}, indent=2)
