"""Traces MCP tools for observability."""

from typing import TYPE_CHECKING, Optional, Union, cast

from fastmcp import FastMCP

from agno.db.base import AsyncBaseDb
from agno.os.routers.traces.schemas import TraceDetail, TraceNode, TraceSessionStats, TraceSummary
from agno.os.utils import get_db, parse_datetime_to_utc

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
        start_time_dt = parse_datetime_to_utc(start_time, "start_time") if start_time else None
        end_time_dt = parse_datetime_to_utc(end_time, "end_time") if end_time else None

        if isinstance(db, AsyncBaseDb):
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

        # Get inputs for each trace
        trace_inputs = {}
        for trace in traces:
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
                for trace in traces
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

            return TraceNode.from_span(span, spans=None).model_dump()

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

        return TraceDetail.from_trace_and_spans(trace, spans).model_dump()

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
        start_time_dt = parse_datetime_to_utc(start_time, "start_time") if start_time else None
        end_time_dt = parse_datetime_to_utc(end_time, "end_time") if end_time else None

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

