"""AgentOSTools -- give agents a read-only ops view of the AgentOS they run on.

Answers questions about usage, latency, failures, schedules, eval history and
runtime-built components by reading directly from the AgentOS database.

Cost is not reported: agno only records provider-supplied cost, which almost no
provider returns, and it is not aggregated into the daily metrics rollup.

Typical use:
    from agno.tools.agentos import AgentOSTools

    ops_agent = Agent(
        model=OpenAIResponses(id="gpt-5.5"),
        tools=[AgentOSTools(db=db)],
    )

    ops_agent.print_response("Which agent is slowest, and which tools fail the most?")

The toolkit takes the database, never the AgentOS instance: agents are constructed
before the OS and passed into ``AgentOS(agents=[...])``, so an agent holding an OS
reference would be a construction cycle. Every tool reads only from ``db``.

Enable flags:
    * All surfaces are enabled by default: metrics, traces, schedules, evals,
      components and approvals.
    * Pass e.g. ``schedules=False`` to hide a surface from the agent.
    * ``components`` defaults to False for async databases, which do not support
      ``list_components``. Passing ``components=True`` with an async database
      raises at construction time.
    * Surfaces not supported by the configured database (e.g. schedules on most
      backends) return a clear error payload at call time.

Read-only:
    * No tool mutates platform state. Schedule, approval and component management
      are deliberately not exposed. The one write that does happen is the metrics
      rollup refresh inside get_platform_metrics -- derived data, no user content.
    * Span attributes payloads, approval tool arguments and schedule run
      input/output are never returned -- they can hold full conversation content.
    * Schedule run errors are redacted: an error that came with an HTTP status
      code is reduced to ``HTTP <code>`` (upstream response bodies echo run
      input back, e.g. via a 422), and framework-generated messages are capped
      at their first line, 200 characters.
    * The tools read the database directly, so AgentOS endpoint scopes do not
      apply to them: anyone who can talk to the agent sees platform-wide
      aggregates, and pending approvals include identifiers (user_id, tool_name,
      session_id). Expose the agent carrying this toolkit to operators, and use
      the enable flags to trim surfaces for wider audiences.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, Union, cast

from agno.tools.toolkit import Toolkit
from agno.utils.log import log_warning, logger

if TYPE_CHECKING:
    from agno.db.base import AsyncBaseDb, BaseDb


class AgentOSTools(Toolkit):
    """Toolkit that lets an agent answer ops questions about its AgentOS.

    Args:
        db: The AgentOS database (sync ``BaseDb`` or ``AsyncBaseDb``). All tools
            read only from this database.
        metrics: Expose get_platform_metrics. Defaults to True.
        traces: Expose get_run_activity and get_tool_activity. Defaults to True.
        schedules: Expose list_schedules and get_schedule_history. Defaults to True.
        evals: Expose get_eval_history. Defaults to True.
        components: Expose list_platform_components. Defaults to True for sync
            databases and False for async databases, which do not support
            component listing. Explicit True with an async database raises.
        approvals: Expose list_pending_approvals. Defaults to True.
    """

    def __init__(
        self,
        db: Union["BaseDb", "AsyncBaseDb"],
        metrics: Optional[bool] = None,
        traces: Optional[bool] = None,
        schedules: Optional[bool] = None,
        evals: Optional[bool] = None,
        components: Optional[bool] = None,
        approvals: Optional[bool] = None,
        **kwargs: Any,
    ):
        from agno.db.base import AsyncBaseDb

        if db is None:
            raise ValueError("AgentOSTools requires a db")

        self.db: Union["BaseDb", "AsyncBaseDb"] = db
        self._db_is_async: bool = isinstance(db, AsyncBaseDb)

        (
            self.enable_metrics,
            self.enable_traces,
            self.enable_schedules,
            self.enable_evals,
            self.enable_components,
            self.enable_approvals,
        ) = _resolve_flags(
            metrics=metrics,
            traces=traces,
            schedules=schedules,
            evals=evals,
            components=components,
            approvals=approvals,
            db_is_async=self._db_is_async,
        )

        tools: List[Callable] = []
        async_tools: List[tuple[Callable[..., Any], str]] = []

        if self.enable_metrics:
            tools.append(self.get_platform_metrics)
            async_tools.append((self.aget_platform_metrics, "get_platform_metrics"))
        if self.enable_traces:
            tools.extend([self.get_run_activity, self.get_tool_activity])
            async_tools.extend(
                [
                    (self.aget_run_activity, "get_run_activity"),
                    (self.aget_tool_activity, "get_tool_activity"),
                ]
            )
        if self.enable_evals:
            tools.append(self.get_eval_history)
            async_tools.append((self.aget_eval_history, "get_eval_history"))
        if self.enable_schedules:
            tools.extend([self.list_schedules, self.get_schedule_history])
            async_tools.extend(
                [
                    (self.alist_schedules, "list_schedules"),
                    (self.aget_schedule_history, "get_schedule_history"),
                ]
            )
        if self.enable_components:
            tools.append(self.list_platform_components)
            async_tools.append((self.alist_platform_components, "list_platform_components"))
        if self.enable_approvals:
            tools.append(self.list_pending_approvals)
            async_tools.append((self.alist_pending_approvals, "list_pending_approvals"))

        instruction_lines = [
            "Answer operations questions about this AgentOS with the read-only platform tools.",
            "Usage and token totals: get_platform_metrics. Latency and errors per component: get_run_activity. "
            "Slow or failing tools and model calls: get_tool_activity.",
            "No tool reports cost. If asked what something cost, say the platform does not track it "
            "and give token totals instead -- never estimate cost from tokens.",
            "When a payload carries a truncation or sampling note, report it -- never present a sample "
            "as the whole picture.",
            "These tools are read-only. You cannot modify schedules, approvals or components.",
        ]

        # Toolkit instructions are only injected into the system message when
        # add_instructions is set, so default it on.
        kwargs.setdefault("add_instructions", True)
        super().__init__(
            name="agentos",
            tools=tools,
            async_tools=async_tools,
            instructions="\n".join(instruction_lines),
            **kwargs,
        )

    def _sync_db(self) -> "BaseDb":
        return cast("BaseDb", self.db)

    def _async_db(self) -> "AsyncBaseDb":
        return cast("AsyncBaseDb", self.db)

    # ------------------------------------------------------------------
    # Platform metrics
    # ------------------------------------------------------------------

    def get_platform_metrics(self, days: int = 7) -> str:
        """Get daily platform usage metrics: runs, sessions, users, tokens and model mix.

        Args:
            days (int): Number of days to include, counting back from today. Defaults to 7.

        Returns:
            str: JSON with {window_days, start_date, end_date, totals, model_mix, daily}.
        """
        if self._db_is_async:
            return _async_db_error()
        try:
            start_date, end_date = _metrics_window(days)
            try:
                self._sync_db().calculate_metrics()
            except NotImplementedError:
                pass
            except Exception as e:
                log_warning(f"Could not refresh metrics: {e}")
            rows, _ = self._sync_db().get_metrics(starting_date=start_date, ending_date=end_date)
            return _format_platform_metrics(rows, days, start_date, end_date)
        except Exception:
            logger.exception("Failed to get platform metrics")
            return _tool_error("Failed to get platform metrics")

    async def aget_platform_metrics(self, days: int = 7) -> str:
        """Get daily platform usage metrics: runs, sessions, users, tokens and model mix.

        Args:
            days (int): Number of days to include, counting back from today. Defaults to 7.

        Returns:
            str: JSON with {window_days, start_date, end_date, totals, model_mix, daily}.
        """
        if not self._db_is_async:
            return await _run_sync(self.get_platform_metrics, days)
        try:
            start_date, end_date = _metrics_window(days)
            try:
                await self._async_db().calculate_metrics()
            except NotImplementedError:
                pass
            except Exception as e:
                log_warning(f"Could not refresh metrics: {e}")
            rows, _ = await self._async_db().get_metrics(starting_date=start_date, ending_date=end_date)
            return _format_platform_metrics(rows, days, start_date, end_date)
        except Exception:
            logger.exception("Failed to get platform metrics")
            return _tool_error("Failed to get platform metrics")

    # ------------------------------------------------------------------
    # Run activity (traces grouped by component)
    # ------------------------------------------------------------------

    def get_run_activity(self, days: int = 7) -> str:
        """Get per-agent, per-team, per-workflow and endpoint-level run activity: run counts, latency and errors.

        Args:
            days (int): Number of days to include, counting back from now. Defaults to 7.

        Returns:
            str: JSON with {window_days, total_traces, agents, teams, workflows, endpoint_level, notes}.
                Each row carries total_traces, total_sessions, avg/p95/max duration in ms
                and error_traces. endpoint_level rows are traces with no component id
                (HTTP/MCP entrypoint wrappers), grouped by trace name.
        """
        if self._db_is_async:
            return _async_db_error()
        try:
            start_time = _window_start(days)
            groupings: Dict[str, Tuple[List[Dict[str, Any]], int]] = {}
            for group in ("agent", "team", "workflow", "endpoint"):
                groupings[group] = self._sync_db().get_trace_stats(
                    group_by=group, start_time=start_time, limit=_GROUP_LIMIT
                )
            _, window_total = self._sync_db().get_traces(limit=1, filter_expr=_created_after_expr(start_time))
            return _format_run_activity(groupings, window_total, days)
        except NotImplementedError as e:
            return json.dumps({"error": f"Component-grouped trace stats are not supported by this database: {e}"})
        except Exception:
            logger.exception("Failed to get run activity")
            return _tool_error("Failed to get run activity")

    async def aget_run_activity(self, days: int = 7) -> str:
        """Get per-agent, per-team, per-workflow and endpoint-level run activity: run counts, latency and errors.

        Args:
            days (int): Number of days to include, counting back from now. Defaults to 7.

        Returns:
            str: JSON with {window_days, total_traces, agents, teams, workflows, endpoint_level, notes}.
                Each row carries total_traces, total_sessions, avg/p95/max duration in ms
                and error_traces. endpoint_level rows are traces with no component id
                (HTTP/MCP entrypoint wrappers), grouped by trace name.
        """
        if not self._db_is_async:
            return await _run_sync(self.get_run_activity, days)
        try:
            start_time = _window_start(days)
            groupings: Dict[str, Tuple[List[Dict[str, Any]], int]] = {}
            for group in ("agent", "team", "workflow", "endpoint"):
                groupings[group] = await self._async_db().get_trace_stats(
                    group_by=group, start_time=start_time, limit=_GROUP_LIMIT
                )
            _, window_total = await self._async_db().get_traces(limit=1, filter_expr=_created_after_expr(start_time))
            return _format_run_activity(groupings, window_total, days)
        except NotImplementedError as e:
            return json.dumps({"error": f"Component-grouped trace stats are not supported by this database: {e}"})
        except Exception:
            logger.exception("Failed to get run activity")
            return _tool_error("Failed to get run activity")

    # ------------------------------------------------------------------
    # Tool activity (span aggregates)
    # ------------------------------------------------------------------

    def get_tool_activity(self, days: int = 7) -> str:
        """Get tool and model call statistics: most-used and slowest tools, model call latency.

        Aggregates span names, durations and status only -- never conversation content.

        Args:
            days (int): Number of days to include, counting back from now. Defaults to 7.

        Returns:
            str: JSON with {window_days, tools_most_used, tools_slowest, model_calls, notes}.
                Each row carries total_calls, avg/p95/max duration in ms, error_count and
                last_called_at. p95_duration_ms is null on backends without SQL percentiles.
        """
        if self._db_is_async:
            return _async_db_error()
        try:
            start_time = _window_start(days)
            tools_most_used, tools_total = self._sync_db().get_span_stats(
                span_type="TOOL", start_time=start_time, sort_by="total_calls", limit=_SPAN_LIMIT
            )
            tools_slowest, _ = self._sync_db().get_span_stats(
                span_type="TOOL", start_time=start_time, sort_by="avg_duration_ms", limit=_SPAN_LIMIT
            )
            model_calls, models_total = self._sync_db().get_span_stats(
                span_type="LLM", start_time=start_time, sort_by="total_calls", limit=_SPAN_LIMIT
            )
            return _format_tool_activity(tools_most_used, tools_slowest, tools_total, model_calls, models_total, days)
        except NotImplementedError:
            return json.dumps({"error": "Span statistics are not supported by this database"})
        except Exception:
            logger.exception("Failed to get tool activity")
            return _tool_error("Failed to get tool activity")

    async def aget_tool_activity(self, days: int = 7) -> str:
        """Get tool and model call statistics: most-used and slowest tools, model call latency.

        Aggregates span names, durations and status only -- never conversation content.

        Args:
            days (int): Number of days to include, counting back from now. Defaults to 7.

        Returns:
            str: JSON with {window_days, tools_most_used, tools_slowest, model_calls, notes}.
                Each row carries total_calls, avg/p95/max duration in ms, error_count and
                last_called_at. p95_duration_ms is null on backends without SQL percentiles.
        """
        if not self._db_is_async:
            return await _run_sync(self.get_tool_activity, days)
        try:
            start_time = _window_start(days)
            tools_most_used, tools_total = await self._async_db().get_span_stats(
                span_type="TOOL", start_time=start_time, sort_by="total_calls", limit=_SPAN_LIMIT
            )
            tools_slowest, _ = await self._async_db().get_span_stats(
                span_type="TOOL", start_time=start_time, sort_by="avg_duration_ms", limit=_SPAN_LIMIT
            )
            model_calls, models_total = await self._async_db().get_span_stats(
                span_type="LLM", start_time=start_time, sort_by="total_calls", limit=_SPAN_LIMIT
            )
            return _format_tool_activity(tools_most_used, tools_slowest, tools_total, model_calls, models_total, days)
        except NotImplementedError:
            return json.dumps({"error": "Span statistics are not supported by this database"})
        except Exception:
            logger.exception("Failed to get tool activity")
            return _tool_error("Failed to get tool activity")

    # ------------------------------------------------------------------
    # Eval history
    # ------------------------------------------------------------------

    def get_eval_history(self, limit: int = 20) -> str:
        """Get recent eval runs normalized to PASS/FAIL, with the judge's reason on failures.

        Args:
            limit (int): Maximum number of eval runs to return, newest first. Defaults to 20.

        Returns:
            str: JSON with {eval_runs, count, total}. Accuracy evals report scores
                (status SCORED), performance evals report run times (status MEASURED).
        """
        if self._db_is_async:
            return _async_db_error()
        try:
            rows, total = cast(
                Tuple[List[Dict[str, Any]], int],
                self._sync_db().get_eval_runs(limit=_clamp(limit, 1, 100), page=1, deserialize=False),
            )
            return _format_eval_history(rows, total)
        except Exception:
            logger.exception("Failed to get eval history")
            return _tool_error("Failed to get eval history")

    async def aget_eval_history(self, limit: int = 20) -> str:
        """Get recent eval runs normalized to PASS/FAIL, with the judge's reason on failures.

        Args:
            limit (int): Maximum number of eval runs to return, newest first. Defaults to 20.

        Returns:
            str: JSON with {eval_runs, count, total}. Accuracy evals report scores
                (status SCORED), performance evals report run times (status MEASURED).
        """
        if not self._db_is_async:
            return await _run_sync(self.get_eval_history, limit)
        try:
            rows, total = cast(
                Tuple[List[Dict[str, Any]], int],
                await self._async_db().get_eval_runs(limit=_clamp(limit, 1, 100), page=1, deserialize=False),
            )
            return _format_eval_history(rows, total)
        except Exception:
            logger.exception("Failed to get eval history")
            return _tool_error("Failed to get eval history")

    # ------------------------------------------------------------------
    # Schedules
    # ------------------------------------------------------------------

    def list_schedules(self, limit: int = 20) -> str:
        """List schedules with their cron expression, enabled state and last run outcome.

        Args:
            limit (int): Maximum number of schedules to return, newest first. Defaults to 20.

        Returns:
            str: JSON with {schedules, count, total}. Each schedule carries its
                last_run status, timestamp and a redacted error summary if any
                (an HTTP status line or a capped framework message).
        """
        if self._db_is_async:
            return _async_db_error()
        try:
            schedules, total = self._sync_db().get_schedules(limit=_clamp(limit, 1, 50))
            last_runs: Dict[str, Optional[Dict[str, Any]]] = {}
            for schedule in schedules:
                runs, _ = self._sync_db().get_schedule_runs(schedule["id"], limit=1)
                last_runs[schedule["id"]] = runs[0] if runs else None
            return _format_schedules(schedules, total, last_runs)
        except NotImplementedError:
            return json.dumps({"error": "The scheduler is not supported by this database"})
        except Exception:
            logger.exception("Failed to list schedules")
            return _tool_error("Failed to list schedules")

    async def alist_schedules(self, limit: int = 20) -> str:
        """List schedules with their cron expression, enabled state and last run outcome.

        Args:
            limit (int): Maximum number of schedules to return, newest first. Defaults to 20.

        Returns:
            str: JSON with {schedules, count, total}. Each schedule carries its
                last_run status, timestamp and a redacted error summary if any
                (an HTTP status line or a capped framework message).
        """
        if not self._db_is_async:
            return await _run_sync(self.list_schedules, limit)
        try:
            schedules, total = await self._async_db().get_schedules(limit=_clamp(limit, 1, 50))
            last_runs: Dict[str, Optional[Dict[str, Any]]] = {}
            for schedule in schedules:
                runs, _ = await self._async_db().get_schedule_runs(schedule["id"], limit=1)
                last_runs[schedule["id"]] = runs[0] if runs else None
            return _format_schedules(schedules, total, last_runs)
        except NotImplementedError:
            return json.dumps({"error": "The scheduler is not supported by this database"})
        except Exception:
            logger.exception("Failed to list schedules")
            return _tool_error("Failed to list schedules")

    def get_schedule_history(self, schedule_id: str, limit: int = 20) -> str:
        """Get the run history of one schedule: outcome trend, not just the last run.

        Args:
            schedule_id (str): The id of the schedule (see list_schedules).
            limit (int): Maximum number of runs to return, newest first. Defaults to 20.

        Returns:
            str: JSON with {schedule_id, page_summary, runs, count, total}. The
                page_summary counts the returned runs by status and carries their
                most recent failure; it covers only the runs returned, not the
                schedule's full history. Errors are redacted to an HTTP status
                line or a capped framework message.
        """
        if self._db_is_async:
            return _async_db_error()
        try:
            runs, total = self._sync_db().get_schedule_runs(schedule_id, limit=_clamp(limit, 1, 100))
            return _format_schedule_history(schedule_id, runs, total)
        except NotImplementedError:
            return json.dumps({"error": "The scheduler is not supported by this database"})
        except Exception:
            logger.exception("Failed to get schedule history")
            return _tool_error("Failed to get schedule history")

    async def aget_schedule_history(self, schedule_id: str, limit: int = 20) -> str:
        """Get the run history of one schedule: outcome trend, not just the last run.

        Args:
            schedule_id (str): The id of the schedule (see list_schedules).
            limit (int): Maximum number of runs to return, newest first. Defaults to 20.

        Returns:
            str: JSON with {schedule_id, page_summary, runs, count, total}. The
                page_summary counts the returned runs by status and carries their
                most recent failure; it covers only the runs returned, not the
                schedule's full history. Errors are redacted to an HTTP status
                line or a capped framework message.
        """
        if not self._db_is_async:
            return await _run_sync(self.get_schedule_history, schedule_id, limit)
        try:
            runs, total = await self._async_db().get_schedule_runs(schedule_id, limit=_clamp(limit, 1, 100))
            return _format_schedule_history(schedule_id, runs, total)
        except NotImplementedError:
            return json.dumps({"error": "The scheduler is not supported by this database"})
        except Exception:
            logger.exception("Failed to get schedule history")
            return _tool_error("Failed to get schedule history")

    # ------------------------------------------------------------------
    # Components
    # ------------------------------------------------------------------

    def list_platform_components(self, limit: int = 50) -> str:
        """List runtime-built components (agents, teams, workflows) persisted in the database.

        Args:
            limit (int): Maximum number of components to return, newest first. Defaults to 50.

        Returns:
            str: JSON with {components, count, total}. Each component carries its
                type, name, description and current version.
        """
        if self._db_is_async:
            return json.dumps({"error": "Component listing is not supported by async databases"})
        try:
            components, total = self._sync_db().list_components(limit=_clamp(limit, 1, 100))
            return _format_components(components, total)
        except NotImplementedError:
            return json.dumps({"error": "Component listing is not supported by this database"})
        except Exception:
            logger.exception("Failed to list platform components")
            return _tool_error("Failed to list platform components")

    async def alist_platform_components(self, limit: int = 50) -> str:
        """List runtime-built components (agents, teams, workflows) persisted in the database.

        Args:
            limit (int): Maximum number of components to return, newest first. Defaults to 50.

        Returns:
            str: JSON with {components, count, total}. Each component carries its
                type, name, description and current version.
        """
        if self._db_is_async:
            return json.dumps({"error": "Component listing is not supported by async databases"})
        return await _run_sync(self.list_platform_components, limit)

    # ------------------------------------------------------------------
    # Approvals
    # ------------------------------------------------------------------

    def list_pending_approvals(self) -> str:
        """List human-in-the-loop approvals waiting on a human decision.

        Tool arguments and approval context are not included -- they can hold
        user conversation content.

        Returns:
            str: JSON with {approvals, count, total}. Each approval carries its
                source, pause type, tool name, requester and expiry.
        """
        if self._db_is_async:
            return _async_db_error()
        try:
            approvals, total = self._sync_db().get_approvals(status="pending", limit=_APPROVAL_LIMIT)
            return _format_pending_approvals(approvals, total)
        except NotImplementedError:
            return json.dumps({"error": "Approvals are not supported by this database"})
        except Exception:
            logger.exception("Failed to list pending approvals")
            return _tool_error("Failed to list pending approvals")

    async def alist_pending_approvals(self) -> str:
        """List human-in-the-loop approvals waiting on a human decision.

        Tool arguments and approval context are not included -- they can hold
        user conversation content.

        Returns:
            str: JSON with {approvals, count, total}. Each approval carries its
                source, pause type, tool name, requester and expiry.
        """
        if not self._db_is_async:
            return await _run_sync(self.list_pending_approvals)
        try:
            approvals, total = await self._async_db().get_approvals(status="pending", limit=_APPROVAL_LIMIT)
            return _format_pending_approvals(approvals, total)
        except NotImplementedError:
            return json.dumps({"error": "Approvals are not supported by this database"})
        except Exception:
            logger.exception("Failed to list pending approvals")
            return _tool_error("Failed to list pending approvals")


# ----------------------------------------------------------------------
# Module helpers
# ----------------------------------------------------------------------

_GROUP_LIMIT = 100
_SPAN_LIMIT = 15
_APPROVAL_LIMIT = 100
_ERROR_SUMMARY_LIMIT = 200


def _resolve_flags(
    metrics: Optional[bool],
    traces: Optional[bool],
    schedules: Optional[bool],
    evals: Optional[bool],
    components: Optional[bool],
    approvals: Optional[bool],
    db_is_async: bool,
) -> tuple[bool, bool, bool, bool, bool, bool]:
    """Resolve the enable flags for the six ops surfaces.

    * Every surface is enabled by default.
    * ``components`` defaults to False for async databases, which do not support
      ``list_components``; explicit ``components=True`` with an async database
      raises so the misconfiguration surfaces at construction time.
    """
    m = bool(metrics) if metrics is not None else True
    t = bool(traces) if traces is not None else True
    s = bool(schedules) if schedules is not None else True
    e = bool(evals) if evals is not None else True
    a = bool(approvals) if approvals is not None else True

    if components is None:
        c = not db_is_async
    else:
        c = bool(components)
        if c and db_is_async:
            raise ValueError(
                "components=True requires a synchronous database (BaseDb). "
                "Async databases do not support list_components."
            )

    return m, t, s, e, c, a


async def _run_sync(function: Callable[..., str], *args: Any, **kwargs: Any) -> str:
    import asyncio

    return await asyncio.to_thread(function, *args, **kwargs)


def _async_db_error() -> str:
    return json.dumps(
        {
            "error": "This toolkit is configured with an async database. Run the agent through the "
            "async execution path (arun / AgentOS server) so the async tool variants are used."
        }
    )


def _tool_error(context: str) -> str:
    """Generic error payload for the agent.

    The exception detail is logged (logger.exception) but never returned. These
    tools read the database directly with no endpoint scopes, so raw exception
    text -- SQL fragments, table or column names -- must not reach whoever talks
    to the agent.
    """
    return json.dumps({"error": f"{context}. The error has been logged."})


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(int(value), high))


def _window_start(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=_clamp(days, 1, 365))


def _metrics_window(days: int) -> tuple[date, date]:
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=_clamp(days, 1, 365) - 1)
    return start_date, end_date


def _epoch_to_iso(value: Optional[int]) -> Optional[str]:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (ValueError, OSError, TypeError):
        return None


def _format_platform_metrics(rows: List[Any], days: int, start_date: date, end_date: date) -> str:
    daily = []
    totals = {
        "agent_runs": 0,
        "team_runs": 0,
        "workflow_runs": 0,
        "agent_sessions": 0,
        "team_sessions": 0,
        "workflow_sessions": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }
    model_mix: Dict[str, int] = {}

    for row in sorted(rows, key=lambda r: str(r["date"])):
        record = dict(row)
        token_metrics = record.get("token_metrics") or {}
        daily.append(
            {
                "date": str(record.get("date")),
                "agent_runs": record.get("agent_runs_count", 0),
                "team_runs": record.get("team_runs_count", 0),
                "workflow_runs": record.get("workflow_runs_count", 0),
                "agent_sessions": record.get("agent_sessions_count", 0),
                "team_sessions": record.get("team_sessions_count", 0),
                "workflow_sessions": record.get("workflow_sessions_count", 0),
                "distinct_users": record.get("users_count", 0),
                "total_tokens": token_metrics.get("total_tokens", 0),
            }
        )
        totals["agent_runs"] += record.get("agent_runs_count", 0)
        totals["team_runs"] += record.get("team_runs_count", 0)
        totals["workflow_runs"] += record.get("workflow_runs_count", 0)
        totals["agent_sessions"] += record.get("agent_sessions_count", 0)
        totals["team_sessions"] += record.get("team_sessions_count", 0)
        totals["workflow_sessions"] += record.get("workflow_sessions_count", 0)
        totals["input_tokens"] += token_metrics.get("input_tokens", 0)
        totals["output_tokens"] += token_metrics.get("output_tokens", 0)
        totals["total_tokens"] += token_metrics.get("total_tokens", 0)
        for model in record.get("model_metrics") or []:
            key = f"{model.get('model_id')}:{model.get('model_provider')}"
            model_mix[key] = model_mix.get(key, 0) + int(model.get("count", 0))

    payload: Dict[str, Any] = {
        "window_days": days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "totals": totals,
        "model_mix": [{"model": key, "runs": count} for key, count in sorted(model_mix.items(), key=lambda kv: -kv[1])],
        "daily": daily,
        "notes": ["distinct_users is per-day; summing it across days would overcount"],
    }
    if not daily:
        payload["notes"].append("no metrics recorded for this window; the platform may have had no sessions")
    return json.dumps(payload, default=str)


def _created_after_expr(start_time: datetime) -> Dict[str, Any]:
    return {"op": "GTE", "key": "created_at", "value": start_time.isoformat()}


def _format_run_activity(groupings: Dict[str, Tuple[List[Dict[str, Any]], int]], window_total: int, days: int) -> str:
    notes: List[str] = []
    payload: Dict[str, Any] = {"window_days": days, "total_traces": window_total}

    for group, key in (
        ("agent", "agents"),
        ("team", "teams"),
        ("workflow", "workflows"),
        ("endpoint", "endpoint_level"),
    ):
        rows, total_groups = groupings[group]
        payload[key] = rows
        if total_groups > len(rows):
            notes.append(f"only the top {len(rows)} of {total_groups} {key} groups are shown")

    notes.append(
        "endpoint_level rows are traces with no component id (HTTP/MCP entrypoint wrappers around "
        "component runs); component tables exclude them, and a trace attributed to more than one "
        "component appears under each, so the tables may not sum to total_traces"
    )
    payload["notes"] = notes
    return json.dumps(payload, default=str)


def _format_tool_activity(
    tools_most_used: List[Dict[str, Any]],
    tools_slowest: List[Dict[str, Any]],
    tools_total: int,
    model_calls: List[Dict[str, Any]],
    models_total: int,
    days: int,
) -> str:
    notes: List[str] = []
    if tools_total > len(tools_most_used):
        notes.append(f"only the top {len(tools_most_used)} of {tools_total} tools are shown per list")
    if models_total > len(model_calls):
        notes.append(f"only the top {len(model_calls)} of {models_total} model call groups are shown")
    if any(row.get("p95_duration_ms") is None for row in tools_most_used + model_calls):
        notes.append("p95_duration_ms is not available on this database backend")

    payload = {
        "window_days": days,
        "tools_most_used": tools_most_used,
        "tools_slowest": tools_slowest,
        "model_calls": model_calls,
        "notes": notes,
    }
    return json.dumps(payload, default=str)


def _normalize_eval_run(record: Dict[str, Any]) -> Dict[str, Any]:
    eval_type = record.get("eval_type")
    eval_data = record.get("eval_data") or {}
    if isinstance(eval_data, str):
        try:
            eval_data = json.loads(eval_data)
        except (ValueError, TypeError):
            eval_data = {}

    normalized: Dict[str, Any] = {
        "id": record.get("run_id"),
        "name": record.get("name"),
        "eval_type": eval_type,
        "component": record.get("evaluated_component_name")
        or record.get("agent_id")
        or record.get("team_id")
        or record.get("workflow_id"),
        "model_id": record.get("model_id"),
        "created_at": _epoch_to_iso(record.get("created_at")),
    }

    results = eval_data.get("results") or []
    if eval_type == "reliability":
        eval_status = str(eval_data.get("eval_status") or "")
        normalized["status"] = {"PASSED": "PASS", "FAILED": "FAIL"}.get(eval_status, eval_status or None)
        if normalized["status"] == "FAIL":
            normalized["reason"] = {
                "failed_tool_calls": eval_data.get("failed_tool_calls") or [],
                "missing_tool_calls": eval_data.get("missing_tool_calls") or [],
                "failed_argument_checks": eval_data.get("failed_argument_checks") or [],
            }
    elif eval_type == "agent_as_judge":
        passed_flags = [bool(r.get("passed")) for r in results if isinstance(r, dict)]
        normalized["status"] = "PASS" if passed_flags and all(passed_flags) else ("FAIL" if passed_flags else None)
        normalized["pass_rate"] = eval_data.get("pass_rate")
        if eval_data.get("avg_score") is not None:
            normalized["avg_score"] = eval_data.get("avg_score")
        if normalized["status"] == "FAIL":
            reasons = [str(r.get("reason", "")) for r in results if isinstance(r, dict) and not r.get("passed")]
            normalized["reason"] = "; ".join(reason for reason in reasons if reason)[:1000]
    elif eval_type == "accuracy":
        normalized["status"] = "SCORED"
        normalized["avg_score"] = eval_data.get("avg_score")
    elif eval_type == "performance":
        normalized["status"] = "MEASURED"
        run_times = eval_data.get("result")
        if not isinstance(run_times, dict):
            run_times = eval_data  # older rows stored the numbers at the top level
        normalized["avg_run_time"] = run_times.get("avg_run_time")
    else:
        normalized["status"] = "UNKNOWN"

    return {key: value for key, value in normalized.items() if value is not None}


def _format_eval_history(rows: List[Any], total: int) -> str:
    eval_runs = [_normalize_eval_run(dict(row)) for row in rows]
    payload: Dict[str, Any] = {"eval_runs": eval_runs, "count": len(eval_runs), "total": total}
    if total > len(eval_runs):
        payload["notes"] = [f"only the {len(eval_runs)} most recent of {total} eval runs are shown"]
    return json.dumps(payload, default=str)


def _summarize_run_error(run: Dict[str, Any]) -> Optional[str]:
    """Reduce a stored schedule run error to a safe, bounded summary.

    Errors that came with an HTTP status code are raw upstream response bodies,
    which can echo the run input back (e.g. a 422 validation error), so the
    body is dropped and only ``HTTP <code>`` is returned. Errors without a
    status code are framework-generated (timeouts, cancellations, transport
    failures) and are kept, first line only, capped at 200 characters.
    """
    error = run.get("error")
    if error is None:
        return None
    status_code = run.get("status_code")
    if status_code is not None:
        return f"HTTP {status_code}"
    lines = str(error).strip().splitlines()
    return lines[0][:_ERROR_SUMMARY_LIMIT] if lines else None


def _format_schedule_run(run: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": run.get("status"),
        "attempt": run.get("attempt"),
        "triggered_at": _epoch_to_iso(run.get("triggered_at")),
        "completed_at": _epoch_to_iso(run.get("completed_at")),
        "status_code": run.get("status_code"),
        "error": _summarize_run_error(run),
    }


def _format_schedules(
    schedules: List[Dict[str, Any]], total: int, last_runs: Dict[str, Optional[Dict[str, Any]]]
) -> str:
    rows = []
    for schedule in schedules:
        last_run = last_runs.get(schedule["id"])
        rows.append(
            {
                "id": schedule.get("id"),
                "name": schedule.get("name"),
                "description": schedule.get("description"),
                "cron_expr": schedule.get("cron_expr"),
                "timezone": schedule.get("timezone"),
                "enabled": schedule.get("enabled"),
                "endpoint": schedule.get("endpoint"),
                "next_run_at": _epoch_to_iso(schedule.get("next_run_at")),
                "last_run": _format_schedule_run(last_run) if last_run else None,
            }
        )
    payload: Dict[str, Any] = {"schedules": rows, "count": len(rows), "total": total}
    if total > len(rows):
        payload["notes"] = [f"only {len(rows)} of {total} schedules are shown"]
    return json.dumps(payload, default=str)


def _format_schedule_history(schedule_id: str, runs: List[Dict[str, Any]], total: int) -> str:
    status_counts: Dict[str, int] = {}
    last_failure: Optional[Dict[str, Any]] = None
    for run in runs:
        status = str(run.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1
        if last_failure is None and status in ("failed", "timeout"):
            last_failure = _format_schedule_run(run)

    payload: Dict[str, Any] = {
        "schedule_id": schedule_id,
        "page_summary": {"status_counts": status_counts, "last_failure": last_failure},
        "runs": [_format_schedule_run(run) for run in runs],
        "count": len(runs),
        "total": total,
    }
    if total > len(runs):
        payload["notes"] = [
            f"only the {len(runs)} most recent of {total} runs are shown",
            f"page_summary covers only these {len(runs)} runs; older runs may hold failures it does not reflect",
        ]
    return json.dumps(payload, default=str)


def _format_components(components: List[Dict[str, Any]], total: int) -> str:
    rows = [
        {
            "component_id": component.get("component_id"),
            "component_type": component.get("component_type"),
            "name": component.get("name"),
            "description": component.get("description"),
            "current_version": component.get("current_version"),
            "created_at": _epoch_to_iso(component.get("created_at")),
            "updated_at": _epoch_to_iso(component.get("updated_at")),
        }
        for component in components
    ]
    payload: Dict[str, Any] = {"components": rows, "count": len(rows), "total": total}
    if total > len(rows):
        payload["notes"] = [f"only {len(rows)} of {total} components are shown"]
    return json.dumps(payload, default=str)


def _format_pending_approvals(approvals: List[Dict[str, Any]], total: int) -> str:
    rows = []
    for approval in approvals:
        row = {
            "id": approval.get("id"),
            "run_id": approval.get("run_id"),
            "session_id": approval.get("session_id"),
            "source_type": approval.get("source_type"),
            "source_name": approval.get("source_name"),
            "approval_type": approval.get("approval_type"),
            "pause_type": approval.get("pause_type"),
            "tool_name": approval.get("tool_name"),
            "agent_id": approval.get("agent_id"),
            "team_id": approval.get("team_id"),
            "workflow_id": approval.get("workflow_id"),
            "user_id": approval.get("user_id"),
            "created_at": _epoch_to_iso(approval.get("created_at")),
            "expires_at": _epoch_to_iso(approval.get("expires_at")),
        }
        rows.append({key: value for key, value in row.items() if value is not None})
    payload: Dict[str, Any] = {"approvals": rows, "count": len(rows), "total": total}
    if total > len(rows):
        payload["notes"] = [f"only {len(rows)} of {total} pending approvals are shown"]
    return json.dumps(payload, default=str)
