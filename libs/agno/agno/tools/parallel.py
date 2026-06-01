import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional

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
    ParallelTools provides access to Parallel's web APIs optimized for AI agents.

    Args:
        api_key (Optional[str]): Parallel API key. If not provided, will use PARALLEL_API_KEY environment variable.
        enable_search (bool): Enable Search API functionality. Default is True.
        enable_extract (bool): Enable Extract API functionality. Default is True.
        enable_task (bool): Enable Task API (deep research). Default is False.
        enable_monitor (bool): Enable Monitor API (web tracking). Default is False.
        all (bool): Enable all tools. Overrides individual flags when True. Default is False.
        default_processor (str): Default processor for tasks. Options: "lite", "base", "core", "pro", "ultra", "ultra8x". Default is "base".
        default_monitor_frequency (str): Default frequency for monitors. Options: "1h", "1d", "1w", "30d". Default is "1d".
        max_results (int): Default maximum number of results for search operations. Default is 10.
        max_chars_per_result (int): Default maximum characters per result for search operations. Default is 10000.
        mode (Optional[str]): Default search mode. Options: "one-shot", "agentic", or "fast". Default is None.
        include_domains (Optional[List[str]]): Default domains to restrict results to. Default is None.
        exclude_domains (Optional[List[str]]): Default domains to exclude from results. Default is None.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_search: bool = True,
        enable_extract: bool = True,
        enable_task: bool = False,
        enable_monitor: bool = False,
        all: bool = False,
        default_processor: str = "base",
        default_monitor_frequency: str = "1d",
        max_results: int = 10,
        max_chars_per_result: int = 10000,
        mode: Optional[str] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        max_age_seconds: Optional[int] = None,
        disable_cache_fallback: Optional[bool] = None,
        **kwargs,
    ):
        self.api_key: Optional[str] = api_key or getenv("PARALLEL_API_KEY")
        if not self.api_key:
            log_error("PARALLEL_API_KEY not set. Please set the PARALLEL_API_KEY environment variable.")

        self.default_processor = default_processor
        self.default_monitor_frequency = default_monitor_frequency
        self.max_results = max_results
        self.max_chars_per_result = max_chars_per_result
        self.mode = mode
        self.include_domains = include_domains
        self.exclude_domains = exclude_domains
        self.max_age_seconds = max_age_seconds
        self.disable_cache_fallback = disable_cache_fallback

        self.parallel_client = ParallelClient(api_key=self.api_key)

        tools: List[Any] = []
        # Search & Extract
        if all or enable_search:
            tools.append(self.parallel_search)
        if all or enable_extract:
            tools.append(self.parallel_extract)
        # Task API
        if all or enable_task:
            tools.extend([self.run_task, self.create_task, self.get_task_result, self.get_task_status])
        # Monitor API
        if all or enable_monitor:
            tools.extend(
                [
                    self.create_monitor,
                    self.create_snapshot_monitor,
                    self.list_monitors,
                    self.get_monitor,
                    self.update_monitor,
                    self.cancel_monitor,
                    self.trigger_monitor,
                    self.get_monitor_events,
                ]
            )

        super().__init__(name="parallel", tools=tools, **kwargs)

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
            log_error(f"Error searching Parallel for objective '{objective}'")
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
            log_error("Error extracting from Parallel")
            return json.dumps({"error": f"Extract failed: {str(e)}"}, indent=2)

    # Task API

    def run_task(
        self,
        input: str,
        processor: Optional[str] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 300,
    ) -> str:
        """Execute a deep research task and wait for results.

        The Task API performs multi-step web research to answer complex queries,
        returning structured results with citations and confidence scores.

        Args:
            input: Natural language research query (e.g., "What is the latest funding round for Stripe?").
            processor: Processing tier - "lite", "base", "core", "pro", "ultra", "ultra8x". Higher tiers are more thorough but cost more.
            output_schema: Optional JSON schema for structured output. If not provided, the API infers an appropriate schema.
            timeout_seconds: Maximum time to wait for results in seconds. Defaults to 300 (5 min).

        Returns:
            JSON string with content (structured output), basis (per-field citations), and run metadata.
        """
        try:
            task_processor = processor or self.default_processor

            task_params: Dict[str, Any] = {
                "input": input,
                "processor": task_processor,
            }

            if output_schema is not None:
                task_params["task_spec"] = {"output_schema": output_schema}

            task_run = self.parallel_client.task_run.create(**task_params)
            task_result = self.parallel_client.task_run.result(task_run.run_id, api_timeout=timeout_seconds)

            output_data: Dict[str, Any] = {
                "run_id": task_run.run_id,
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

            return json.dumps(output_data, cls=CustomJSONEncoder, indent=2)

        except Exception as e:
            log_error(f"Error running task with input '{input[:100]}...'")
            return json.dumps({"error": f"Task failed: {str(e)}"}, indent=2)

    def create_task(
        self,
        input: str,
        processor: Optional[str] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """Create a research task without waiting for results. Returns run_id for later retrieval.

        Use this for long-running tasks. Retrieve results later with get_task_result().

        Args:
            input: Natural language research query or JSON object describing the task.
            processor: Processing tier - "lite", "base", "core", "pro", "ultra", "ultra8x".
            output_schema: Optional JSON schema for structured output.
            metadata: Key-value pairs stored with the task (max 16 char keys, 512 char values).

        Returns:
            JSON string with run_id, status, interaction_id, and processor.
        """
        try:
            task_processor = processor or self.default_processor

            task_params: Dict[str, Any] = {
                "input": input,
                "processor": task_processor,
            }

            if output_schema is not None:
                task_params["task_spec"] = {"output_schema": output_schema}
            if metadata is not None:
                task_params["metadata"] = metadata

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
            log_error(f"Error creating task with input '{input[:100]}...'")
            return json.dumps({"error": f"Create task failed: {str(e)}"}, indent=2)

    def get_task_result(self, run_id: str, timeout_seconds: int = 300) -> str:
        """Get the result of a task by run_id. Blocks until task completes or times out.

        Args:
            run_id: The task run identifier from create_task().
            timeout_seconds: Maximum time to wait for completion in seconds. Defaults to 300.

        Returns:
            JSON string with content (structured output), basis (citations), and run status.
        """
        try:
            task_result = self.parallel_client.task_run.result(run_id, api_timeout=timeout_seconds)

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

            return json.dumps(output_data, cls=CustomJSONEncoder, indent=2)

        except Exception as e:
            log_error(f"Error getting result for task {run_id}")
            return json.dumps({"error": f"Get result failed: {str(e)}"}, indent=2)

    def get_task_status(self, run_id: str) -> str:
        """Check the status of a task without waiting for completion.

        Args:
            run_id: The task run identifier.

        Returns:
            JSON string with run_id, status, processor, is_active, and timestamps.
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
                indent=2,
            )

        except Exception as e:
            log_error(f"Error getting status for task {run_id}")
            return json.dumps({"error": f"Get status failed: {str(e)}"}, indent=2)

    # Monitor API

    def create_monitor(
        self,
        query: str,
        frequency: Optional[str] = None,
        processor: Literal["lite", "base"] = "lite",
        output_schema: Optional[Dict[str, Any]] = None,
        include_backfill: bool = False,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """Create an event_stream monitor to track a search query for material changes.

        The monitor runs on the configured schedule. Use get_monitor_events() to retrieve
        detected changes. Combine with SchedulerTools for automated polling.

        Args:
            query: Search query to monitor for changes (e.g., "AI startup funding rounds").
            frequency: How often to check. Options: "1h", "1d", "1w", "30d". Default is "1d".
            processor: "lite" (fast/cheap) or "base" (more thorough). Defaults to "lite".
            output_schema: Optional JSON schema for structured events.
            include_backfill: If True, first run includes recent historical events.
            metadata: Key-value pairs stored with the monitor (max 16 char keys, 512 char values).

        Returns:
            JSON string with monitor_id, status, frequency, and created_at.
        """
        try:
            monitor_frequency = frequency or self.default_monitor_frequency

            settings: Dict[str, Any] = {"query": query}
            if output_schema is not None:
                settings["output_schema"] = output_schema
            if include_backfill:
                settings["include_backfill"] = True

            monitor_params: Dict[str, Any] = {
                "type": "event_stream",
                "frequency": monitor_frequency,
                "processor": processor,
                "settings": settings,
            }

            if metadata is not None:
                monitor_params["metadata"] = metadata

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
            log_error(f"Error creating monitor for query '{query}'")
            return json.dumps({"error": f"Create monitor failed: {str(e)}"}, indent=2)

    def create_snapshot_monitor(
        self,
        task_run_id: str,
        frequency: Optional[str] = None,
        processor: Literal["lite", "base"] = "lite",
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """Create a snapshot monitor to track changes in a task run's output.

        Use this to monitor when the output of a specific task would change if re-run.
        Use get_monitor_events() to retrieve detected changes.

        Args:
            task_run_id: The task run whose output to monitor for changes.
            frequency: How often to check. Options: "1h", "1d", "1w", "30d". Default is "1d".
            processor: "lite" (fast/cheap) or "base" (more thorough). Defaults to "lite".
            metadata: Key-value pairs stored with the monitor.

        Returns:
            JSON string with monitor_id, status, frequency, and task_run_id.
        """
        try:
            monitor_frequency = frequency or self.default_monitor_frequency

            monitor_params: Dict[str, Any] = {
                "type": "snapshot",
                "frequency": monitor_frequency,
                "processor": processor,
                "settings": {"task_run_id": task_run_id},
            }

            if metadata is not None:
                monitor_params["metadata"] = metadata

            monitor = self.parallel_client.monitor.create(**monitor_params)

            return json.dumps(
                {
                    "monitor_id": monitor.monitor_id,
                    "type": monitor.type,
                    "status": monitor.status,
                    "frequency": monitor.frequency,
                    "processor": monitor.processor,
                    "task_run_id": task_run_id,
                    "created_at": str(monitor.created_at),
                },
                indent=2,
            )

        except Exception as e:
            log_error(f"Error creating snapshot monitor for task {task_run_id}")
            return json.dumps({"error": f"Create snapshot monitor failed: {str(e)}"}, indent=2)

    def list_monitors(
        self,
        status: Optional[Literal["active", "cancelled"]] = None,
        monitor_type: Optional[Literal["event_stream", "snapshot"]] = None,
        limit: int = 100,
    ) -> str:
        """List monitors with optional filters.

        Args:
            status: Filter by "active" or "cancelled". Defaults to active only.
            monitor_type: Filter by "event_stream" or "snapshot".
            limit: Maximum number of monitors to return. Defaults to 100.

        Returns:
            JSON string with list of monitors containing id, type, status, frequency.
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
            log_error("Error listing monitors")
            return json.dumps({"error": f"List monitors failed: {str(e)}"}, indent=2)

    def get_monitor(self, monitor_id: str) -> str:
        """Get details of a specific monitor.

        Args:
            monitor_id: The monitor's unique identifier.

        Returns:
            JSON string with full monitor details including settings.
        """
        try:
            monitor = self.parallel_client.monitor.retrieve(monitor_id)

            monitor_data: Dict[str, Any] = {
                "monitor_id": monitor.monitor_id,
                "type": monitor.type,
                "status": monitor.status,
                "frequency": monitor.frequency,
                "processor": monitor.processor,
                "created_at": str(monitor.created_at),
                "last_run_at": monitor.last_run_at,
                "metadata": monitor.metadata,
            }

            if monitor.type == "event_stream" and hasattr(monitor.settings, "query"):
                monitor_data["query"] = monitor.settings.query
            if monitor.type == "snapshot" and hasattr(monitor.settings, "task_run_id"):
                monitor_data["task_run_id"] = monitor.settings.task_run_id

            return json.dumps(monitor_data, indent=2)

        except Exception as e:
            log_error(f"Error getting monitor {monitor_id}")
            return json.dumps({"error": f"Get monitor failed: {str(e)}"}, indent=2)

    def update_monitor(
        self,
        monitor_id: str,
        frequency: Optional[str] = None,
        query: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """Update a monitor's settings. Only event_stream monitors can update query.

        Args:
            monitor_id: The monitor's unique identifier.
            frequency: New frequency. Options: "1h", "1d", "1w", "30d".
            query: New search query (event_stream monitors only).
            metadata: New metadata (replaces existing).

        Returns:
            JSON string with updated monitor details.
        """
        try:
            update_params: Dict[str, Any] = {}
            if frequency is not None:
                update_params["frequency"] = frequency
            if query is not None:
                update_params["type"] = "event_stream"
                update_params["settings"] = {"query": query}
            if metadata is not None:
                update_params["metadata"] = metadata

            if not update_params:
                return json.dumps({"error": "No update parameters provided"}, indent=2)

            monitor = self.parallel_client.monitor.update(monitor_id, **update_params)

            return json.dumps(
                {
                    "monitor_id": monitor.monitor_id,
                    "type": monitor.type,
                    "status": monitor.status,
                    "frequency": monitor.frequency,
                    "updated": True,
                },
                indent=2,
            )

        except Exception as e:
            log_error(f"Error updating monitor {monitor_id}")
            return json.dumps({"error": f"Update monitor failed: {str(e)}"}, indent=2)

    def cancel_monitor(self, monitor_id: str) -> str:
        """Cancel a monitor permanently. This action cannot be undone.

        Args:
            monitor_id: The monitor's unique identifier.

        Returns:
            JSON string confirming cancellation with monitor_id and status.
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
            log_error(f"Error cancelling monitor {monitor_id}")
            return json.dumps({"error": f"Cancel monitor failed: {str(e)}"}, indent=2)

    def trigger_monitor(self, monitor_id: str) -> str:
        """Trigger an immediate run of a monitor outside its normal schedule.

        The monitor's regular schedule is not affected. An event is only emitted
        if the execution detects a material change.

        Args:
            monitor_id: The monitor's unique identifier.

        Returns:
            JSON string confirming the trigger was sent.
        """
        try:
            self.parallel_client.monitor.trigger(monitor_id)

            return json.dumps(
                {
                    "monitor_id": monitor_id,
                    "triggered": True,
                    "message": "Monitor run triggered. Events will be emitted if changes are detected.",
                },
                indent=2,
            )

        except Exception as e:
            log_error(f"Error triggering monitor {monitor_id}")
            return json.dumps({"error": f"Trigger monitor failed: {str(e)}"}, indent=2)

    def get_monitor_events(
        self,
        monitor_id: str,
        include_completions: bool = False,
        limit: int = 20,
    ) -> str:
        """List events (changes) detected by a monitor.

        Args:
            monitor_id: The monitor's unique identifier.
            include_completions: Include runs with no changes (for audit). Defaults to False.
            limit: Maximum number of events to return. Defaults to 20, max 100.

        Returns:
            JSON string with list of events containing timestamps, changes, and citations.
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
                    "event_type": getattr(event, "type", None),
                    "event_group_id": getattr(event, "event_group_id", None),
                    "created_at": str(getattr(event, "created_at", "")),
                }
                if hasattr(event, "content"):
                    event_data["content"] = event.content
                if hasattr(event, "citations"):
                    event_data["citations"] = [
                        {"url": c.url, "title": getattr(c, "title", None)} for c in event.citations
                    ]
                events.append(event_data)

            return json.dumps({"events": events, "has_more": response.next_cursor is not None}, indent=2)

        except Exception as e:
            log_error(f"Error getting events for monitor {monitor_id}")
            return json.dumps({"error": f"Get events failed: {str(e)}"}, indent=2)
