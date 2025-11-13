import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error

try:
    from parallel import Parallel as ParallelClient
except ImportError:
    raise ImportError("`parallel-web` not installed. Please install using `pip install parallel-web`")


class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles non-serializable types by converting them to strings."""

    def default(self, obj):
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


class ParallelTools(Toolkit):
    """
    ParallelTools provides access to Parallel's web search and extraction APIs.

    Parallel offers powerful APIs optimized for AI agents:
    - Search API: AI-optimized web search that returns relevant excerpts tailored for LLMs
    - Extract API: Extract content from specific URLs in clean markdown format, handling JavaScript-heavy pages and PDFs

    Args:
        api_key (Optional[str]): Parallel API key. If not provided, will use PARALLEL_API_KEY environment variable.
        enable_search (bool): Enable Search API functionality. Default is True.
        enable_extract (bool): Enable Extract API functionality. Default is True.
        all (bool): Enable all tools. Overrides individual flags when True. Default is False.
        max_results (int): Default maximum number of results for search operations. Default is 10.
        max_chars_per_result (int): Default maximum characters per result for search operations. Default is 10000.
        beta_version (str): Beta API version header. Default is "search-extract-2025-10-10".
        mode (Optional[str]): Default search mode. Options: "one-shot" or "agentic". Default is None.
        include_domains (Optional[List[str]]): Default domains to restrict results to. Default is None.
        exclude_domains (Optional[List[str]]): Default domains to exclude from results. Default is None.
        max_age_seconds (Optional[int]): Default cache age threshold (minimum 600). Default is None.
        timeout_seconds (Optional[float]): Default timeout for content retrieval. Default is None.
        disable_cache_fallback (Optional[bool]): Default cache fallback behavior. Default is None.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_search: bool = True,
        enable_extract: bool = True,
        all: bool = False,
        max_results: int = 10,
        max_chars_per_result: int = 10000,
        beta_version: str = "search-extract-2025-10-10",
        mode: Optional[str] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        max_age_seconds: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        disable_cache_fallback: Optional[bool] = None,
        **kwargs,
    ):
        self.api_key: Optional[str] = api_key or getenv("PARALLEL_API_KEY")
        if not self.api_key:
            log_error("PARALLEL_API_KEY not set. Please set the PARALLEL_API_KEY environment variable.")

        self.max_results = max_results
        self.max_chars_per_result = max_chars_per_result
        self.beta_version = beta_version
        self.mode = mode
        self.include_domains = include_domains
        self.exclude_domains = exclude_domains
        self.max_age_seconds = max_age_seconds
        self.timeout_seconds = timeout_seconds
        self.disable_cache_fallback = disable_cache_fallback

        self.parallel_client = ParallelClient(
            api_key=self.api_key, default_headers={"parallel-beta": self.beta_version}
        )

        tools: List[Any] = []
        if all or enable_search:
            tools.append(self.parallel_search)
        if all or enable_extract:
            tools.append(self.parallel_extract)

        super().__init__(name="parallel_tools", tools=tools, **kwargs)

    def parallel_search(
        self,
        objective: Optional[str] = None,
        search_queries: Optional[List[str]] = None,
        max_results: Optional[int] = None,
        max_chars_per_result: Optional[int] = None,
    ) -> str:
        """Use this function to search the web using Parallel's Search API with a natural language objective.
        You must provide at least one of objective or search_queries.

        Args:
            objective (Optional[str]): Natural-language description of what the web search is trying to find.
            search_queries (Optional[List[str]]): Traditional keyword queries with optional search operators.
            max_results (Optional[int]): Upper bound on results returned. Overrides constructor default.
            max_chars_per_result (Optional[int]): Upper bound on total characters per url for excerpts.

        Returns:
            str: A JSON formatted string containing the search results with URLs, titles, publish dates, and relevant excerpts.
        """
        try:
            if not objective and not search_queries:
                return json.dumps({"error": "Please provide at least one of: objective or search_queries"}, indent=2)

            # Use instance defaults if not provided
            final_max_results = max_results if max_results is not None else self.max_results

            search_params: Dict[str, Any] = {
                "max_results": final_max_results,
            }

            # Add objective if provided
            if objective:
                search_params["objective"] = objective

            # Add search_queries if provided
            if search_queries:
                search_params["search_queries"] = search_queries

            # Add mode from constructor default
            if self.mode:
                search_params["mode"] = self.mode

            # Add excerpts configuration
            excerpts_config: Dict[str, Any] = {}
            final_max_chars = max_chars_per_result if max_chars_per_result is not None else self.max_chars_per_result
            if final_max_chars is not None:
                excerpts_config["max_chars_per_result"] = final_max_chars

            if excerpts_config:
                search_params["excerpts"] = excerpts_config

            # Add source_policy from constructor defaults
            source_policy: Dict[str, Any] = {}
            if self.include_domains:
                source_policy["include_domains"] = self.include_domains
            if self.exclude_domains:
                source_policy["exclude_domains"] = self.exclude_domains

            if source_policy:
                search_params["source_policy"] = source_policy

            # Add fetch_policy from constructor defaults
            fetch_policy: Dict[str, Any] = {}
            if self.max_age_seconds is not None:
                fetch_policy["max_age_seconds"] = self.max_age_seconds
            if self.timeout_seconds is not None:
                fetch_policy["timeout_seconds"] = self.timeout_seconds
            if self.disable_cache_fallback is not None:
                fetch_policy["disable_cache_fallback"] = self.disable_cache_fallback

            if fetch_policy:
                search_params["fetch_policy"] = fetch_policy

            search_result = self.parallel_client.beta.search(**search_params)

            # Use model_dump() if available, otherwise convert to dict
            try:
                if hasattr(search_result, "model_dump"):
                    return json.dumps(search_result.model_dump(), cls=CustomJSONEncoder)
            except Exception:
                pass

            # Manually format the results
            formatted_results: Dict[str, Any] = {
                "search_id": getattr(search_result, "search_id", ""),
                "results": [],
            }

            if hasattr(search_result, "results") and search_result.results:
                results_list: List[Dict[str, Any]] = []
                for result in search_result.results:
                    formatted_result: Dict[str, Any] = {
                        "title": getattr(result, "title", ""),
                        "url": getattr(result, "url", ""),
                        "publish_date": getattr(result, "publish_date", ""),
                        "excerpt": getattr(result, "excerpt", ""),
                    }
                    results_list.append(formatted_result)
                formatted_results["results"] = results_list

            if hasattr(search_result, "warnings"):
                formatted_results["warnings"] = search_result.warnings

            if hasattr(search_result, "usage"):
                formatted_results["usage"] = search_result.usage

            return json.dumps(formatted_results, cls=CustomJSONEncoder, indent=2)

        except Exception as e:
            log_error(f"Error searching Parallel for objective '{objective}': {e}")
            return json.dumps({"error": f"Search failed: {str(e)}"}, indent=2)

    def parallel_extract(
        self,
        urls: List[str],
        objective: Optional[str] = None,
        search_queries: Optional[List[str]] = None,
        excerpts: bool = True,
        max_chars_per_excerpt: Optional[int] = None,
        full_content: bool = False,
        max_chars_for_full_content: Optional[int] = None,
    ) -> str:
        """Use this function to extract content from specific URLs using Parallel's Extract API.

        Args:
            urls (List[str]): List of public URLs to extract content from.
            objective (Optional[str]): Search focus to guide content extraction.
            search_queries (Optional[List[str]]): Keywords for targeting relevant content.
            excerpts (bool): Include relevant text snippets.
            max_chars_per_excerpt (Optional[int]): Upper bound on total characters per url. Only used when excerpts is True.
            full_content (bool): Include complete page text.
            max_chars_for_full_content (Optional[int]): Limit on characters per url. Only used when full_content is True.

        Returns:
            str: A JSON formatted string containing extracted content with titles, publish dates, excerpts and/or full content.
        """
        try:
            if not urls:
                return json.dumps({"error": "Please provide at least one URL to extract"}, indent=2)

            extract_params: Dict[str, Any] = {
                "urls": urls,
            }

            # Add objective if provided
            if objective:
                extract_params["objective"] = objective

            # Add search_queries if provided
            if search_queries:
                extract_params["search_queries"] = search_queries

            # Add excerpts configuration
            if excerpts and max_chars_per_excerpt is not None:
                extract_params["excerpts"] = {"max_chars_per_result": max_chars_per_excerpt}
            else:
                extract_params["excerpts"] = excerpts

            # Add full_content configuration
            if full_content and max_chars_for_full_content is not None:
                extract_params["full_content"] = {"max_chars_per_result": max_chars_for_full_content}
            else:
                extract_params["full_content"] = full_content

            # Add fetch_policy from constructor defaults
            fetch_policy: Dict[str, Any] = {}
            if self.max_age_seconds is not None:
                fetch_policy["max_age_seconds"] = self.max_age_seconds
            if self.timeout_seconds is not None:
                fetch_policy["timeout_seconds"] = self.timeout_seconds
            if self.disable_cache_fallback is not None:
                fetch_policy["disable_cache_fallback"] = self.disable_cache_fallback

            if fetch_policy:
                extract_params["fetch_policy"] = fetch_policy

            extract_result = self.parallel_client.beta.extract(**extract_params)

            # Use model_dump() if available, otherwise convert to dict
            try:
                if hasattr(extract_result, "model_dump"):
                    return json.dumps(extract_result.model_dump(), cls=CustomJSONEncoder)
            except Exception:
                pass

            # Manually format the results
            formatted_results: Dict[str, Any] = {
                "extract_id": getattr(extract_result, "extract_id", ""),
                "results": [],
                "errors": [],
            }

            if hasattr(extract_result, "results") and extract_result.results:
                results_list: List[Dict[str, Any]] = []
                for result in extract_result.results:
                    formatted_result: Dict[str, Any] = {
                        "url": getattr(result, "url", ""),
                        "title": getattr(result, "title", ""),
                        "publish_date": getattr(result, "publish_date", ""),
                    }

                    if excerpts and hasattr(result, "excerpts"):
                        formatted_result["excerpts"] = result.excerpts

                    if full_content and hasattr(result, "full_content"):
                        formatted_result["full_content"] = result.full_content

                    results_list.append(formatted_result)
                formatted_results["results"] = results_list

            if hasattr(extract_result, "errors") and extract_result.errors:
                formatted_results["errors"] = extract_result.errors

            if hasattr(extract_result, "warnings"):
                formatted_results["warnings"] = extract_result.warnings

            if hasattr(extract_result, "usage"):
                formatted_results["usage"] = extract_result.usage

            return json.dumps(formatted_results, cls=CustomJSONEncoder, indent=2)

        except Exception as e:
            log_error(f"Error extracting from Parallel: {e}")
            return json.dumps({"error": f"Extract failed: {str(e)}"}, indent=2)
