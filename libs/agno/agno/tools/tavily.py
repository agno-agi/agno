import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from tavily import TavilyClient
except ImportError:
    raise ImportError("`tavily-python` not installed. Please install using `pip install tavily-python`")


class TavilyTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base_url: Optional[str] = None,
        enable_search: bool = True,
        enable_search_context: bool = False,
        enable_extract: bool = False,
        all: bool = False,
        max_tokens: int = 6000,
        include_answer: bool = True,
        search_depth: Literal["basic", "advanced"] = "advanced",
        extract_depth: Literal["basic", "advanced"] = "basic",
        include_images: bool = False,
        include_favicon: bool = False,
        extract_timeout: Optional[int] = None,
        extract_format: Literal["markdown", "text"] = "markdown",
        format: Literal["json", "markdown"] = "markdown",
        **kwargs,
    ):
        """Initialize TavilyTools with search and extract capabilities.

        Args:
            api_key: Tavily API key. If not provided, will use TAVILY_API_KEY env var.
            api_base_url: Tavily API base URL. If not provided, will use TAVILY_API_BASE_URL env var. Defaults to None. If None - will use https://api.tavily.com.
            enable_search: Enable web search functionality. Defaults to True.
            enable_search_context: Use search context mode instead of regular search. Defaults to False.
            enable_extract: Enable URL content extraction functionality. Defaults to False.
            all: Enable all available tools. Defaults to False.
            max_tokens: Maximum tokens for search results. Defaults to 6000.
            include_answer: Include AI-generated answer in search results. Defaults to True.
            search_depth: Search depth level - basic (1 credit) or advanced (2 credits). Defaults to "advanced".
            extract_depth: Extract depth level - basic (1 credit/5 URLs) or advanced (2 credits/5 URLs). Defaults to "basic".
            include_images: Include images in extracted content. Defaults to False.
            include_favicon: Include favicon in extracted content. Defaults to False.
            extract_timeout: Timeout in seconds for extraction requests. Defaults to None.
            extract_format: Output format for extracted content - markdown or text. Defaults to "markdown".
            format: Output format for search results - json or markdown. Defaults to "markdown".
            **kwargs: Additional arguments passed to Toolkit.
        """
        self.api_key = api_key or getenv("TAVILY_API_KEY")
        if not self.api_key:
            logger.error("TAVILY_API_KEY not provided")
        self.api_base_url = api_base_url or getenv("TAVILY_API_BASE_URL")

        self.client: TavilyClient = TavilyClient(api_key=self.api_key, api_base_url=self.api_base_url)
        self.search_depth: Literal["basic", "advanced"] = search_depth
        self.extract_depth: Literal["basic", "advanced"] = extract_depth
        self.max_tokens: int = max_tokens
        self.include_answer: bool = include_answer
        self.include_images: bool = include_images
        self.include_favicon: bool = include_favicon
        self.extract_timeout: Optional[int] = extract_timeout
        self.extract_format: Literal["markdown", "text"] = extract_format
        self.format: Literal["json", "markdown"] = format

        tools: List[Any] = []

        if enable_search or all:
            if enable_search_context:
                tools.append(self.web_search_with_tavily)
            else:
                tools.append(self.web_search_using_tavily)

        if enable_extract or all:
            tools.append(self.extract_url_content)

        super().__init__(name="tavily_tools", tools=tools, **kwargs)

    def web_search_using_tavily(self, query: str, max_results: int = 5) -> str:
        """Use this function to search the web for a given query.
        This function uses the Tavily API to provide realtime online information about the query.

        Args:
            query (str): Query to search for.
            max_results (int): Maximum number of results to return. Defaults to 5.

        Returns:
            str: JSON string of results related to the query.
        """

        response = self.client.search(
            query=query, search_depth=self.search_depth, include_answer=self.include_answer, max_results=max_results
        )

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
        """Use this function to search the web for a given query.
        This function uses the Tavily API to provide realtime online information about the query.

        Args:
            query (str): Query to search for.

        Returns:
            str: JSON string of results related to the query.
        """

        return self.client.get_search_context(query=query, search_depth=self.search_depth, max_tokens=self.max_tokens)

    def extract_url_content(self, urls: str) -> str:
        """Extract content from one or more URLs using Tavily's Extract API.
        This function retrieves the main content from web pages in markdown or text format.

        Args:
            urls (str): Single URL or multiple comma-separated URLs to extract content from.
                       Example: "https://example.com" or "https://example.com,https://another.com"

        Returns:
            str: Extracted content in the specified format (markdown or text).
                 For multiple URLs, returns combined content with URL headers.
                 Failed extractions are noted in the output.
        """
        # Parse URLs - handle both single and comma-separated multiple URLs
        url_list = [url.strip() for url in urls.split(",") if url.strip()]

        if not url_list:
            return "Error: No valid URLs provided."

        try:
            # Prepare extract parameters
            extract_params: Dict[str, Any] = {
                "urls": url_list,
                "depth": self.extract_depth,
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
                return "Error: No content could be extracted from the provided URL(s)."

            results = response.get("results", [])
            if not results:
                return "Error: No content could be extracted from the provided URL(s)."

            # Format output
            if self.extract_format == "markdown":
                return self._format_extract_markdown(results)
            elif self.extract_format == "text":
                return self._format_extract_text(results)
            else:
                # Fallback to JSON if format is unrecognized
                return json.dumps(results, indent=2)

        except Exception as e:
            logger.error(f"Error extracting content from URLs: {e}")
            return f"Error extracting content: {str(e)}"

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
