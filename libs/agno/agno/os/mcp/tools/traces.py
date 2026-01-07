"""Traces MCP tools for observability."""

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

from fastmcp import FastMCP

from agno.db.base import AsyncBaseDb
from agno.os.routers.traces.schemas import TraceDetail, TraceNode, TraceSessionStats, TraceSummary
from agno.os.schema import PaginatedResponse
from agno.os.utils import get_db, timestamp_to_datetime
from agno.remote.base import RemoteDb
from agno.tracing.schemas import Trace

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def register_traces_tools(mcp: FastMCP, os: "AgentOS") -> None:
    """Register traces MCP tools."""

    @mcp.tool(
        name="get_traces",
        description="Get a paginated list of execution traces with optional filtering",
        tags={"traces"},
    )  # type: ignore
    async def get_traces(
        db_id: Optional[str] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict:
        db = await get_db(os.dbs, db_id)

        # Convert datetime strings to UTC
        start_time_dt = timestamp_to_datetime(start_time, "start_time") if start_time else None
        end_time_dt = timestamp_to_datetime(end_time, "end_time") if end_time else None

        traces: List[Union[Trace, TraceSummary]]
        total_count: int

        if isinstance(db, RemoteDb):
            # RemoteDb returns PaginatedResponse[TraceSummary]
            traces_result = cast(
                PaginatedResponse[TraceSummary],
                await db.get_traces(
                    run_id=run_id,
                    session_id=session_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    workflow_id=workflow_id,
                    status=status,
                    start_time=start_time_dt,
                    end_time=end_time_dt,
                    limit=limit,
                    page=page,
                ),
            )
            # For RemoteDb, traces are already TraceSummary objects with input populated
            return {
                "data": [trace.model_dump() for trace in traces_result.data],
                "total_count": traces_result.meta.total_count,
                "page": page,
                "limit": limit,
            }
        elif isinstance(db, AsyncBaseDb):
            traces, total_count = await db.get_traces(
                run_id=run_id,
                session_id=session_id,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                workflow_id=workflow_id,
                status=status,
                start_time=start_time_dt,
                end_time=end_time_dt,
                limit=limit,
                page=page,
            )
        else:
            traces, total_count = db.get_traces(
                run_id=run_id,
                session_id=session_id,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                workflow_id=workflow_id,
                status=status,
                start_time=start_time_dt,
                end_time=end_time_dt,
                limit=limit,
                page=page,
            )

        # For local dbs, get inputs for each trace by fetching spans
        trace_inputs: Dict[str, Any] = {}
        for trace in cast(List[Trace], traces):
            if isinstance(db, AsyncBaseDb):
                spans = await db.get_spans(trace_id=trace.trace_id)
            else:
                spans = db.get_spans(trace_id=trace.trace_id)

            root_span = next((s for s in spans if not s.parent_span_id), None)
            if root_span and hasattr(root_span, "attributes"):
                trace_inputs[trace.trace_id] = root_span.attributes.get("input.value")

        return {
            "data": [
                TraceSummary.from_trace(trace, input=trace_inputs.get(trace.trace_id)).model_dump()
                for trace in cast(List[Trace], traces)
            ],
            "total_count": total_count,
            "page": page,
            "limit": limit,
        }

    @mcp.tool(
        name="get_trace",
        description="Get detailed trace information with hierarchical span tree, or a specific span",
        tags={"traces"},
    )  # type: ignore
    async def get_trace(
        trace_id: str,
        db_id: Optional[str] = None,
        span_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> dict:
        db = await get_db(os.dbs, db_id)

        # For RemoteDb, get_trace already returns TraceDetail with tree built
        if isinstance(db, RemoteDb):
            if span_id:
                trace_node = cast(TraceNode, await db.get_trace(trace_id=trace_id, span_id=span_id, run_id=run_id))
                return cast(Dict[str, Any], trace_node.model_dump())
            else:
                trace_detail = cast(TraceDetail, await db.get_trace(trace_id=trace_id, run_id=run_id))
                return cast(Dict[str, Any], trace_detail.model_dump())

        # If span_id provided, return just that span
        if span_id:
            if isinstance(db, AsyncBaseDb):
                span = await db.get_span(span_id)
            else:
                span = db.get_span(span_id)

            if span is None:
                raise Exception(f"Span {span_id} not found")

            if span.trace_id != trace_id:
                raise Exception(f"Span {span_id} does not belong to trace {trace_id}")

            return cast(Dict[str, Any], TraceNode.from_span(span, spans=None).model_dump())

        # Otherwise return full trace with hierarchy
        if isinstance(db, AsyncBaseDb):
            trace = await db.get_trace(trace_id=trace_id, run_id=run_id)
        else:
            trace = db.get_trace(trace_id=trace_id, run_id=run_id)

        if trace is None:
            raise Exception(f"Trace {trace_id} not found")

        if isinstance(db, AsyncBaseDb):
            spans = await db.get_spans(trace_id=trace_id)
        else:
            spans = db.get_spans(trace_id=trace_id)

        return cast(Dict[str, Any], TraceDetail.from_trace_and_spans(trace, spans).model_dump())

    @mcp.tool(
        name="get_trace_stats",
        description="Get aggregated trace statistics grouped by session",
        tags={"traces"},
    )  # type: ignore
    async def get_trace_stats(
        db_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict:
        db = await get_db(os.dbs, db_id)

        # Convert datetime strings to UTC
        start_time_dt = timestamp_to_datetime(start_time, "start_time") if start_time else None
        end_time_dt = timestamp_to_datetime(end_time, "end_time") if end_time else None

        # RemoteDb returns PaginatedResponse[TraceSessionStats] directly
        if isinstance(db, RemoteDb):
            result = cast(
                PaginatedResponse[TraceSessionStats],
                await db.get_trace_session_stats(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    workflow_id=workflow_id,
                    start_time=start_time_dt,
                    end_time=end_time_dt,
                    limit=limit,
                    page=page,
                ),
            )
            return {
                "data": [stat.model_dump() for stat in result.data],
                "total_count": result.meta.total_count,
                "page": page,
                "limit": limit,
            }

        stats_list: List[Dict[str, Any]]
        total_count: int

        if isinstance(db, AsyncBaseDb):
            stats_list, total_count = await db.get_trace_stats(
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                workflow_id=workflow_id,
                start_time=start_time_dt,
                end_time=end_time_dt,
                limit=limit,
                page=page,
            )
        else:
            stats_list, total_count = db.get_trace_stats(
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                workflow_id=workflow_id,
                start_time=start_time_dt,
                end_time=end_time_dt,
                limit=limit,
                page=page,
            )

        return {
            "data": [
                TraceSessionStats(
                    session_id=stat["session_id"],
                    user_id=stat.get("user_id"),
                    agent_id=stat.get("agent_id"),
                    team_id=stat.get("team_id"),
                    workflow_id=stat.get("workflow_id"),
                    total_traces=stat["total_traces"],
                    first_trace_at=stat["first_trace_at"],
                    last_trace_at=stat["last_trace_at"],
                ).model_dump()
                for stat in stats_list
            ],
            "total_count": total_count,
            "page": page,
            "limit": limit,
        }
