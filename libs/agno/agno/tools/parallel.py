import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional, Union

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
    - Task API: Deep research with structured output and citations (enable_task=True)
    - Monitor API: Track topics over time, get notified of changes, update settings (enable_monitor=True)

    Args:
        api_key (Optional[str]): Parallel API key. If not provided, will use PARALLEL_API_KEY environment variable.
        enable_search (bool): Enable Search API functionality. Default is True.
        enable_extract (bool): Enable Extract API functionality. Default is True.
        enable_task (bool): Enable Task API (deep research). Default is False.
        enable_monitor (bool): Enable Monitor API (web tracking). Default is False.
        all (bool): Enable all tools. Overrides individual flags when True. Default is False.
        max_results (int): Default maximum number of results for search operations. Default is 10.
        max_chars_per_result (int): Default maximum characters per result for search operations. Default is 10000.
        beta_version (str): Beta API version header. Default is "search-extract-2025-10-10".
        mode (Optional[str]): Default search mode. Options: "one-shot" or "agentic". Default is None.
        include_domains (Optional[List[str]]): Default domains to restrict results to. Default is None.
        exclude_domains (Optional[List[str]]): Default domains to exclude from results. Default is None.
        max_age_seconds (Optional[int]): Default cache age threshold (minimum 600). Default is None.
        disable_cache_fallback (Optional[bool]): Default cache fallback behavior. Default is None.
        default_processor (str): Default processor for Task API. Default is "base".
        default_monitor_processor (str): Default processor for Monitor API. Options: "lite", "base". Default is "lite".
        default_monitor_frequency (str): Default frequency for monitors. Options: "1h", "1d", "1w", "30d". Default is "1d".
        default_timeout (int): Default timeout for task results in seconds. Default is 1800 (30 minutes), suitable for "pro" tier research. Increase up to 3600 for "ultra" tier deep research.
        default_output_schema (Optional[Union[Dict[str, Any], str]]): Schema for structured output. Accepts a bare string description, {"type": "auto"}, {"type": "json", "json_schema": {...}}, or {"type": "text"}. Default is None.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_search: bool = True,
        enable_extract: bool = True,
        enable_task: bool = False,
        enable_monitor: bool = False,
        all: bool = False,
        max_results: int = 10,
        max_chars_per_result: int = 10000,
        beta_version: str = "search-extract-2025-10-10",
        mode: Optional[str] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        max_age_seconds: Optional[int] = None,
        disable_cache_fallback: Optional[bool] = None,
        default_processor: str = "base",
        default_monitor_processor: Literal["lite", "base"] = "lite",
        default_monitor_frequency: str = "1d",
        default_timeout: int = 1800,
        default_output_schema: Optional[Union[Dict[str, Any], str]] = None,
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
        self.disable_cache_fallback = disable_cache_fallback
        self.default_processor = default_processor
        self.default_monitor_processor = default_monitor_processor
        self.default_monitor_frequency = default_monitor_frequency
        self.default_timeout = default_timeout
        self.default_output_schema = default_output_schema

        self.parallel_client = ParallelClient(
            api_key=self.api_key, default_headers={"parallel-beta": self.beta_version}
        )

        tools: List[Any] = []
        if all or enable_search:
            tools.append(self.parallel_search)
        if all or enable_extract:
            tools.append(self.parallel_extract)
        if all or enable_task:
            tools.extend([self.create_task, self.get_task_status, self.get_task_result])
        if all or enable_monitor:
            tools.extend(
                [
                    self.create_monitor,
                    self.get_monitor,
                    self.update_monitor,
                    self.list_monitors,
                    self.get_monitor_events,
                    self.cancel_monitor,
                ]
            )

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
                        "excerpts": getattr(result, "excerpts", []),
                    }
                    results_list.append(formatted_result)
                formatted_results["results"] = results_list

            if hasattr(search_result, "warnings"):
                formatted_results["warnings"] = search_result.warnings

            if hasattr(search_result, "usage"):
                formatted_results["usage"] = search_result.usage

            return json.dumps(formatted_results, cls=CustomJSONEncoder, indent=2)

        except Exception as e:
            log_error(f"Error searching Parallel for objective '{objective}': {str(e)}")
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
            log_error(f"Error extracting from Parallel: {str(e)}")
            return json.dumps({"error": f"Extract failed: {str(e)}"}, indent=2)

    # -------------------------------------------------------------------------
    # Task API — Deep research with structured output and citations
    # -------------------------------------------------------------------------

    def _format_task_output(self, run_id: str, task_result: Any) -> Dict[str, Any]:
        """Format task result output with content and basis citations."""
        output_data: Dict[str, Any] = {
            "run_id": run_id,
            "status": task_result.run.status,
            "processor": task_result.run.processor,
        }

        if hasattr(task_result.output, "content"):
            output_data["content"] = task_result.output.content
        if hasattr(task_result.output, "basis"):
            output_data["basis"] = [
                {
                    "field": b.field,
                    "confidence": getattr(b, "confidence", None),
                    "citations": [
                        {"url": c.url, "title": getattr(c, "title", None), "excerpts": getattr(c, "excerpts", None)}
                        for c in getattr(b, "citations", [])
                    ],
                }
                for b in task_result.output.basis
            ]

        return output_data

    def create_task(self, query: str) -> str:
        """
        Create a research task without waiting for results. Use get_task_result() to retrieve later.

        Args:
            query (str): Natural language research query (e.g., "What is Anthropic's latest funding?")

        Returns:
            str: JSON with run_id, status, interaction_id, and processor
        """
        try:
            task_params: Dict[str, Any] = {
                "input": query,
                "processor": self.default_processor,
            }

            if self.default_output_schema is not None:
                task_params["task_spec"] = {"output_schema": self.default_output_schema}

            task_run = self.parallel_client.task_run.create(**task_params)

            return json.dumps(
                {
                    "run_id": task_run.run_id,
                    "status": task_run.status,
                    "interaction_id": task_run.interaction_id,
                    "processor": task_run.processor,
                    "is_active": task_run.is_active,
                },
                indent=2,
            )

        except Exception as e:
            log_error(f"Error creating task with query '{query[:100]}...': {str(e)}")
            return json.dumps({"error": f"Create task failed: {str(e)}"}, indent=2)

    def get_task_result(self, run_id: str) -> str:
        """
        Get the result of a task. Blocks until task completes or default_timeout is reached.

        Args:
            run_id (str): The task run identifier from create_task()

        Returns:
            str: JSON with content (structured output), basis (citations), and run status
        """
        try:
            task_result = self.parallel_client.task_run.result(
                run_id, api_timeout=self.default_timeout, timeout=float(self.default_timeout)
            )

            output_data = self._format_task_output(run_id, task_result)
            return json.dumps(output_data, cls=CustomJSONEncoder, indent=2)

        except Exception as e:
            log_error(f"Error getting result for task {run_id}: {str(e)}")
            return json.dumps({"error": f"Get result failed: {str(e)}"}, indent=2)

    def get_task_status(self, run_id: str) -> str:
        """
        Check the status of a task without waiting for completion.

        Args:
            run_id (str): The task run identifier

        Returns:
            str: JSON with run_id, status, processor, is_active, and timestamps
        """
        try:
            task_run = self.parallel_client.task_run.retrieve(run_id)

            return json.dumps(
                {
                    "run_id": task_run.run_id,
                    "status": task_run.status,
                    "processor": task_run.processor,
                    "is_active": task_run.is_active,
                    "created_at": task_run.created_at,
                    "modified_at": task_run.modified_at,
                },
                cls=CustomJSONEncoder,
                indent=2,
            )

        except Exception as e:
            log_error(f"Error getting status for task {run_id}: {str(e)}")
            return json.dumps({"error": f"Get status failed: {str(e)}"}, indent=2)

    # -------------------------------------------------------------------------
    # Monitor API — Track topics over time and get notified of changes
    # -------------------------------------------------------------------------

    def create_monitor(self, query: str) -> str:
        """
        Create a monitor to track a search query for changes over time.

        Args:
            query (str): Search query to monitor (e.g., "AI startup funding rounds")

        Returns:
            str: JSON with monitor_id, status, frequency, and created_at
        """
        try:
            settings: Dict[str, Any] = {"query": query}
            if self.default_output_schema is not None:
                settings["output_schema"] = self.default_output_schema

            monitor_params: Dict[str, Any] = {
                "type": "event_stream",
                "frequency": self.default_monitor_frequency,
                "processor": self.default_monitor_processor,
                "settings": settings,
            }

            monitor = self.parallel_client.monitor.create(**monitor_params)

            return json.dumps(
                {
                    "monitor_id": monitor.monitor_id,
                    "type": monitor.type,
                    "status": monitor.status,
                    "frequency": monitor.frequency,
                    "processor": monitor.processor,
                    "query": query,
                    "created_at": str(monitor.created_at),
                    "last_run_at": monitor.last_run_at,
                },
                indent=2,
            )

        except Exception as e:
            log_error(f"Error creating monitor for query '{query}': {str(e)}")
            return json.dumps({"error": f"Create monitor failed: {str(e)}"}, indent=2)

    def get_monitor(self, monitor_id: str) -> str:
        """
        Retrieve a specific monitor by ID.

        Args:
            monitor_id (str): The monitor's unique identifier

        Returns:
            str: JSON with monitor configuration including status, frequency, query, and settings
        """
        try:
            monitor = self.parallel_client.monitor.retrieve(monitor_id)

            result: Dict[str, Any] = {
                "monitor_id": monitor.monitor_id,
                "type": monitor.type,
                "status": monitor.status,
                "frequency": monitor.frequency,
                "processor": monitor.processor,
                "created_at": str(monitor.created_at),
                "last_run_at": monitor.last_run_at,
            }
            if monitor.type == "event_stream" and hasattr(monitor.settings, "query"):
                result["query"] = monitor.settings.query

            return json.dumps(result, indent=2)

        except Exception as e:
            log_error(f"Error retrieving monitor {monitor_id}: {str(e)}")
            return json.dumps({"error": f"Get monitor failed: {str(e)}"}, indent=2)

    def update_monitor(
        self,
        monitor_id: str,
        frequency: Optional[str] = None,
        query: Optional[str] = None,
    ) -> str:
        """
        Update a monitor's frequency or query. Cannot update cancelled monitors.

        Args:
            monitor_id (str): The monitor's unique identifier
            frequency (Optional[str]): New frequency (e.g., "1h", "1d", "1w", "30d")
            query (Optional[str]): New search query (only for event_stream monitors)

        Returns:
            str: JSON with updated monitor configuration
        """
        try:
            update_params: Dict[str, Any] = {}
            if frequency is not None:
                update_params["frequency"] = frequency
            if query is not None:
                update_params["type"] = "event_stream"
                update_params["settings"] = {"query": query}

            if not update_params:
                return json.dumps({"error": "At least one of frequency or query must be provided"}, indent=2)

            monitor = self.parallel_client.monitor.update(monitor_id, **update_params)

            result: Dict[str, Any] = {
                "monitor_id": monitor.monitor_id,
                "type": monitor.type,
                "status": monitor.status,
                "frequency": monitor.frequency,
                "processor": monitor.processor,
                "updated": True,
            }
            if monitor.type == "event_stream" and hasattr(monitor.settings, "query"):
                result["query"] = monitor.settings.query

            return json.dumps(result, indent=2)

        except Exception as e:
            log_error(f"Error updating monitor {monitor_id}: {str(e)}")
            return json.dumps({"error": f"Update monitor failed: {str(e)}"}, indent=2)

    def list_monitors(
        self,
        status: Optional[Literal["active", "cancelled"]] = None,
        monitor_type: Optional[Literal["event_stream", "snapshot"]] = None,
        limit: int = 100,
    ) -> str:
        """
        List all monitors with optional filters.

        Args:
            status (Optional[Literal["active", "cancelled"]]): Filter by status
            monitor_type (Optional[Literal["event_stream", "snapshot"]]): Filter by type
            limit (int): Maximum number of monitors to return (default: 100)

        Returns:
            str: JSON with list of monitors containing id, type, status, frequency
        """
        try:
            list_params: Dict[str, Any] = {"limit": limit}
            if status is not None:
                list_params["status"] = [status]
            if monitor_type is not None:
                list_params["type"] = [monitor_type]

            response = self.parallel_client.monitor.list(**list_params)

            monitors = []
            for m in response.monitors:
                monitor_info: Dict[str, Any] = {
                    "monitor_id": m.monitor_id,
                    "type": m.type,
                    "status": m.status,
                    "frequency": m.frequency,
                    "processor": m.processor,
                    "created_at": str(m.created_at),
                    "last_run_at": m.last_run_at,
                }
                if m.type == "event_stream" and hasattr(m.settings, "query"):
                    monitor_info["query"] = m.settings.query
                monitors.append(monitor_info)

            return json.dumps({"monitors": monitors, "has_more": response.next_cursor is not None}, indent=2)

        except Exception as e:
            log_error(f"Error listing monitors: {str(e)}")
            return json.dumps({"error": f"List monitors failed: {str(e)}"}, indent=2)

    def cancel_monitor(self, monitor_id: str) -> str:
        """
        Cancel a monitor permanently. This action cannot be undone.

        Args:
            monitor_id (str): The monitor's unique identifier

        Returns:
            str: JSON confirming cancellation with monitor_id and status
        """
        try:
            monitor = self.parallel_client.monitor.cancel(monitor_id)

            return json.dumps(
                {
                    "monitor_id": monitor.monitor_id,
                    "status": monitor.status,
                    "cancelled": True,
                },
                indent=2,
            )

        except Exception as e:
            log_error(f"Error cancelling monitor {monitor_id}: {str(e)}")
            return json.dumps({"error": f"Cancel monitor failed: {str(e)}"}, indent=2)

    def get_monitor_events(
        self,
        monitor_id: str,
        include_completions: bool = False,
        limit: int = 20,
    ) -> str:
        """
        Get events (changes) detected by a monitor.

        Args:
            monitor_id (str): The monitor's unique identifier
            include_completions (bool): Include runs with no changes (default: False)
            limit (int): Maximum number of events to return (default: 20, max: 100)

        Returns:
            str: JSON with list of events containing timestamps, changes, and citations
        """
        try:
            response = self.parallel_client.monitor.events(
                monitor_id,
                include_completions=include_completions,
                limit=min(limit, 100),
            )

            events = []
            for event in response.events:
                event_data: Dict[str, Any] = {
                    "event_id": getattr(event, "event_id", None),
                    "event_type": getattr(event, "event_type", None),
                    "event_group_id": getattr(event, "event_group_id", None),
                    "event_date": getattr(event, "event_date", None),
                }
                if hasattr(event, "output"):
                    if hasattr(event.output, "content"):
                        event_data["content"] = event.output.content
                    if hasattr(event.output, "basis"):
                        event_data["basis"] = [
                            {
                                "field": b.field,
                                "confidence": getattr(b, "confidence", None),
                                "citations": [
                                    {"url": c.url, "title": getattr(c, "title", None)}
                                    for c in getattr(b, "citations", [])
                                ],
                            }
                            for b in event.output.basis
                        ]
                events.append(event_data)

            return json.dumps({"events": events, "has_more": response.next_cursor is not None}, indent=2)

        except Exception as e:
            log_error(f"Error getting events for monitor {monitor_id}: {str(e)}")
            return json.dumps({"error": f"Get events failed: {str(e)}"}, indent=2)
