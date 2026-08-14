import json
from os import getenv
from typing import Any, Callable, Dict, List, Literal, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, log_exception

try:
    from tavily import TavilyClient
except ImportError:
    raise ImportError("`tavily-python` not installed. Please install using `pip install tavily-python`")


class TavilyTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base_url: Optional[str] = None,
        search: bool = True,
        search_context: bool = False,
        extract: bool = False,
        all: bool = False,
        max_tokens: int = 6000,
        include_answer: bool = True,
        search_depth: Literal["basic", "advanced", "fast", "ultra-fast"] = "advanced",
        extract_depth: Literal["basic", "advanced"] = "basic",
        include_images: bool = False,
        include_favicon: bool = False,
        extract_timeout: Optional[int] = None,
        extract_format: Literal["markdown", "text"] = "markdown",
        format: Literal["json", "markdown"] = "markdown",
        topic: Optional[Literal["general", "news", "finance"]] = None,
        time_range: Optional[Literal["day", "week", "month", "year", "d", "w", "m", "y"]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: Optional[int] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        country: Optional[str] = None,
        auto_parameters: bool = False,
        chunks_per_source: Optional[int] = None,
        search_params: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        """Initialize TavilyTools for web search and content extraction.

        Args:
            api_key: Tavily API key. Falls back to TAVILY_API_KEY env var.
            api_base_url: Tavily API base URL. Falls back to TAVILY_API_BASE_URL env var.
            search: Enable web search tool. Defaults to True.
            search_context: Use deprecated search context mode. Defaults to False.
            extract: Enable URL content extraction tool. Defaults to False (token heavy).
            all: Enable all tools. Defaults to False.
            max_tokens: Maximum tokens for search results.
            include_answer: Include AI-generated answer in search results.
            search_depth: Search depth - basic, advanced, fast, or ultra-fast.
            extract_depth: Extract depth - basic or advanced.
            include_images: Include images in extracted content.
            include_favicon: Include favicon in extracted content.
            extract_timeout: Timeout in seconds for extraction requests.
            extract_format: Output format for extracted content - markdown or text.
            format: Output format for search results - json or markdown.
            topic: Search category - general, news, or finance.
            time_range: Time window for results - day, week, month, year.
            start_date: Only include results published after this date (YYYY-MM-DD).
            end_date: Only include results published before this date (YYYY-MM-DD).
            days: Number of days back to include results (news topic only).
            include_domains: Restrict results to these domains.
            exclude_domains: Exclude these domains from results.
            country: Boost results from this country.
            auto_parameters: Let Tavily auto-tune search parameters.
            chunks_per_source: Number of content chunks per source (1-3).
            search_params: Additional parameters merged into every search request.
        """
        # Backwards compat: enable_X -> X
        if "enable_search" in kwargs:
            search = kwargs.pop("enable_search")
        if "enable_search_context" in kwargs:
            search_context = kwargs.pop("enable_search_context")
        if "enable_extract" in kwargs:
            extract = kwargs.pop("enable_extract")

        self.api_key = api_key or getenv("TAVILY_API_KEY")
        if not self.api_key:
            log_error("TAVILY_API_KEY not provided")
        self.api_base_url = api_base_url or getenv("TAVILY_API_BASE_URL")

        self.client: TavilyClient = TavilyClient(api_key=self.api_key, api_base_url=self.api_base_url)
        self.search_depth: Literal["basic", "advanced", "fast", "ultra-fast"] = search_depth
        self.extract_depth: Literal["basic", "advanced"] = extract_depth
        self.max_tokens: int = max_tokens
        self.include_answer: bool = include_answer
        self.include_images: bool = include_images
        self.include_favicon: bool = include_favicon
        self.extract_timeout: Optional[int] = extract_timeout
        self.extract_format: Literal["markdown", "text"] = extract_format
        self.format: Literal["json", "markdown"] = format
        self.topic: Optional[Literal["general", "news", "finance"]] = topic
        self.time_range: Optional[Literal["day", "week", "month", "year", "d", "w", "m", "y"]] = time_range
        self.start_date: Optional[str] = start_date
        self.end_date: Optional[str] = end_date
        self.days: Optional[int] = days
        self.include_domains: Optional[List[str]] = include_domains
        self.exclude_domains: Optional[List[str]] = exclude_domains
        self.country: Optional[str] = country
        self.auto_parameters: bool = auto_parameters
        self.chunks_per_source: Optional[int] = chunks_per_source
        self.search_params: Optional[Dict[str, Any]] = search_params

        tools: List[Callable] = []

        if all or search:
            if search_context:
                tools.append(self.web_search_with_tavily)
            else:
                tools.append(self.web_search_using_tavily)

        if all or extract:
            tools.append(self.extract_url_content)

        super().__init__(name="tavily_tools", tools=tools, **kwargs)

    def web_search_using_tavily(self, query: str, max_results: int = 5) -> str:
        """Search the web for a given query using Tavily API.

        Args:
            query: The search query.
            max_results: Maximum number of results to return. Defaults to 5.

        Returns:
            Search results in the configured format (json or markdown).
        """

        params: Dict[str, Any] = {
            "query": query,
            "search_depth": self.search_depth,
            "include_answer": self.include_answer,
            "max_results": max_results,
            "topic": self.topic,
            "time_range": self.time_range,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "days": self.days,
            "include_domains": self.include_domains,
            "exclude_domains": self.exclude_domains,
            "country": self.country,
            "chunks_per_source": self.chunks_per_source,
        }
        if self.auto_parameters:
            params["auto_parameters"] = True
        if self.search_params:
            params.update(self.search_params)
        # Only send parameters that are set
        params = {k: v for k, v in params.items() if v is not None}

        response = self.client.search(**params)

        clean_response: Dict[str, Any] = {"query": query}
        if "answer" in response:
            clean_response["answer"] = response["answer"]

        clean_results = []
        current_token_count = len(json.dumps(clean_response))
        for result in response.get("results", []):
            _result = {
                "title": result["title"],
                "url": result["url"],
                "content": result["content"],
                "score": result["score"],
            }
            current_token_count += len(json.dumps(_result))
            if current_token_count > self.max_tokens:
                break
            clean_results.append(_result)
        clean_response["results"] = clean_results

        if self.format == "json":
            return json.dumps(clean_response) if clean_response else "No results found."
        elif self.format == "markdown":
            _markdown = ""
            _markdown += f"# {query}\n\n"
            if "answer" in clean_response:
                _markdown += "### Summary\n"
                _markdown += f"{clean_response.get('answer')}\n\n"
            for result in clean_response["results"]:
                _markdown += f"### [{result['title']}]({result['url']})\n"
                _markdown += f"{result['content']}\n\n"
            return _markdown

    def web_search_with_tavily(self, query: str) -> str:
        """Search the web using Tavily's search context API (deprecated).

        Args:
            query: The search query.

        Returns:
            JSON string of search context results.
        """

        return self.client.get_search_context(query=query, search_depth=self.search_depth, max_tokens=self.max_tokens)

    def extract_url_content(self, urls: str) -> str:
        """Extract content from one or more URLs using Tavily's Extract API.

        Args:
            urls: Single URL or comma-separated URLs to extract content from.

        Returns:
            Extracted content in the configured format (markdown or text).
        """
        # Parse URLs - handle both single and comma-separated multiple URLs
        url_list = [url.strip() for url in urls.split(",") if url.strip()]

        if not url_list:
            return json.dumps({"error": "No valid URLs provided"})

        try:
            # Prepare extract parameters
            extract_params: Dict[str, Any] = {
                "urls": url_list,
                "extract_depth": self.extract_depth,
            }

            # Add optional parameters if specified
            if self.include_images:
                extract_params["include_images"] = True
            if self.include_favicon:
                extract_params["include_favicon"] = True
            if self.extract_timeout is not None:
                extract_params["timeout"] = self.extract_timeout

            # Call Tavily Extract API
            response = self.client.extract(**extract_params)

            # Process response based on format preference
            if not response or "results" not in response:
                return json.dumps({"error": "No content could be extracted from the provided URLs"})

            results = response.get("results", [])
            if not results:
                return json.dumps({"error": "No content could be extracted from the provided URLs"})

            # Format output
            if self.extract_format == "markdown":
                return self._format_extract_markdown(results)
            elif self.extract_format == "text":
                return self._format_extract_text(results)
            else:
                # Fallback to JSON if format is unrecognized
                return json.dumps(results, indent=2)

        except Exception as e:
            log_exception("Error extracting content from URLs")
            return json.dumps({"error": f"Error extracting content: {e}"})

    def _format_extract_markdown(self, results: List[Dict[str, Any]]) -> str:
        """Format extraction results as markdown.

        Args:
            results: List of extraction result dictionaries from Tavily API.

        Returns:
            str: Formatted markdown content.
        """
        output = []

        for result in results:
            url = result.get("url", "Unknown URL")
            raw_content = result.get("raw_content", "")
            failed_reason = result.get("failed_reason")

            if failed_reason:
                output.append(f"## {url}\n\n **Extraction Failed**: {failed_reason}\n\n")
            elif raw_content:
                output.append(f"## {url}\n\n{raw_content}\n\n")
            else:
                output.append(f"## {url}\n\n*No content available*\n\n")

        return "".join(output) if output else "No content extracted."

    def _format_extract_text(self, results: List[Dict[str, Any]]) -> str:
        """Format extraction results as plain text.

        Args:
            results: List of extraction result dictionaries from Tavily API.

        Returns:
            str: Formatted plain text content.
        """
        output = []

        for result in results:
            url = result.get("url", "Unknown URL")
            raw_content = result.get("raw_content", "")
            failed_reason = result.get("failed_reason")

            output.append(f"URL: {url}")
            output.append("-" * 80)

            if failed_reason:
                output.append(f"EXTRACTION FAILED: {failed_reason}")
            elif raw_content:
                output.append(raw_content)
            else:
                output.append("No content available")

            output.append("\n")

        return "\n".join(output) if output else "No content extracted."
