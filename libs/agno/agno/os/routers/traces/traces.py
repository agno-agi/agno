import logging
from typing import Optional, Union

from fastapi import Depends, HTTPException, Query, Request
from fastapi.routing import APIRouter

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.auth import get_auth_token_from_request, get_authentication_dependency
from agno.os.routers.traces.schemas import (
    TraceDetail,
    TraceNode,
    TraceSessionStats,
    TraceSummary,
)
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginatedResponse,
    PaginationInfo,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import get_db, timestamp_to_datetime
from agno.remote.base import RemoteDb
from agno.utils.log import log_error

logger = logging.getLogger(__name__)


def get_traces_router(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]], settings: AgnoAPISettings = AgnoAPISettings(), **kwargs
) -> APIRouter:
    """Create traces router with comprehensive OpenAPI documentation for trace endpoints."""
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        tags=["Traces"],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )
    return attach_routes(router=router, dbs=dbs)


def attach_routes(router: APIRouter, dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]]) -> APIRouter:
    @router.get(
        "/traces",
        response_model=PaginatedResponse[TraceSummary],
        response_model_exclude_none=True,
        tags=["Traces"],
        operation_id="get_traces",
        summary="List Traces",
        description=(
            "Retrieve a paginated list of execution traces with optional filtering.\n\n"
            "**Traces provide observability into:**\n"
            "- Agent execution flows\n"
            "- Model invocations and token usage\n"
            "- Tool calls and their results\n"
            "- Errors and performance bottlenecks\n\n"
            "**Filtering Options:**\n"
            "- By run, session, user, or agent ID\n"
            "- By status (OK, ERROR)\n"
            "- By time range\n\n"
            "**Pagination:**\n"
            "- Use `page` (1-indexed) and `limit` parameters\n"
            "- Response includes pagination metadata (total_pages, total_count, etc.)\n\n"
            "**Response Format:**\n"
            "Returns summary information for each trace. Use GET `/traces/{trace_id}` for detailed hierarchy."
        ),
        responses={
            200: {
                "description": "List of traces retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "data": [
                                {
                                    "trace_id": "a1b2c3d4",
                                    "name": "Stock_Price_Agent.run",
                                    "status": "OK",
                                    "duration": "1.2s",
                                    "start_time": "2025-11-19T10:30:00.000000+00:00",
                                    "total_spans": 4,
                                    "error_count": 0,
                                    "input": "What is the stock price of NVDA?",
                                    "run_id": "run123",
                                    "session_id": "session456",
                                    "user_id": "user789",
                                    "agent_id": "agent_stock",
                                    "team_id": None,
                                    "workflow_id": None,
                                    "created_at": "2025-11-19T10:30:00+00:00",
                                }
                            ],
                            "meta": {
                                "page": 1,
                                "limit": 20,
                                "total_pages": 5,
                                "total_count": 95,
                            },
                        }
                    }
                },
            }
        },
    )
    async def get_traces(
        request: Request,
        run_id: Optional[str] = Query(default=None, description="Filter by run ID"),
        session_id: Optional[str] = Query(default=None, description="Filter by session ID"),
        user_id: Optional[str] = Query(default=None, description="Filter by user ID"),
        agent_id: Optional[str] = Query(default=None, description="Filter by agent ID"),
        team_id: Optional[str] = Query(default=None, description="Filter by team ID"),
        workflow_id: Optional[str] = Query(default=None, description="Filter by workflow ID"),
        status: Optional[str] = Query(default=None, description="Filter by status (OK, ERROR)"),
        start_time: Optional[str] = Query(
            default=None,
            description="Filter traces starting after this time (ISO 8601 format with timezone, e.g., '2025-11-19T10:00:00Z' or '2025-11-19T15:30:00+05:30'). Times are converted to UTC for comparison.",
        ),
        end_time: Optional[str] = Query(
            default=None,
            description="Filter traces ending before this time (ISO 8601 format with timezone, e.g., '2025-11-19T11:00:00Z' or '2025-11-19T16:30:00+05:30'). Times are converted to UTC for comparison.",
        ),
        page: int = Query(default=1, description="Page number (1-indexed)", ge=0),
        limit: int = Query(default=20, description="Number of traces per page", ge=1),
        db_id: Optional[str] = Query(default=None, description="Database ID to query traces from"),
    ):
        """Get list of traces with optional filters and pagination"""
        import time as time_module

        # Get database using db_id or default to first available
        db = await get_db(dbs, db_id)

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.get_traces(
                run_id=run_id,
                session_id=session_id,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                workflow_id=workflow_id,
                status=status,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
                page=page,
                db_id=db_id,
                headers=headers,
            )

        try:
            start_time_ms = time_module.time() * 1000

            # Convert ISO datetime strings to UTC datetime objects
            start_time_dt = timestamp_to_datetime(start_time, "start_time") if start_time else None
            end_time_dt = timestamp_to_datetime(end_time, "end_time") if end_time else None

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

            end_time_ms = time_module.time() * 1000
            search_time_ms = round(end_time_ms - start_time_ms, 2)

            # Calculate total pages
            total_pages = (total_count + limit - 1) // limit if limit > 0 else 0

            trace_inputs = {}
            for trace in traces:
                if isinstance(db, AsyncBaseDb):
                    spans = await db.get_spans(trace_id=trace.trace_id)
                else:
                    spans = db.get_spans(trace_id=trace.trace_id)

                # Find root span and extract input
                root_span = next((s for s in spans if not s.parent_span_id), None)
                if root_span and hasattr(root_span, "attributes"):
                    trace_inputs[trace.trace_id] = root_span.attributes.get("input.value")

            # Build response
            trace_summaries = [
                TraceSummary.from_trace(trace, input=trace_inputs.get(trace.trace_id)) for trace in traces
            ]

            return PaginatedResponse(
                data=trace_summaries,
                meta=PaginationInfo(
                    page=page,
                    limit=limit,
                    total_pages=total_pages,
                    total_count=total_count,
                    search_time_ms=search_time_ms,
                ),
            )

        except Exception as e:
            log_error(f"Error retrieving traces: {e}")
            raise HTTPException(status_code=500, detail=f"Error retrieving traces: {str(e)}")

    @router.get(
        "/traces/{trace_id}",
        response_model=Union[TraceDetail, TraceNode],
        response_model_exclude_none=True,
        tags=["Traces"],
        operation_id="get_trace",
        summary="Get Trace or Span Detail",
        description=(
            "Retrieve detailed trace information with hierarchical span tree, or a specific span within the trace.\n\n"
            "**Without span_id parameter:**\n"
            "Returns the full trace with hierarchical span tree:\n"
            "- Trace metadata (ID, status, duration, context)\n"
            "- Hierarchical tree of all spans\n"
            "- Each span includes timing, status, and type-specific metadata\n\n"
            "**With span_id parameter:**\n"
            "Returns details for a specific span within the trace:\n"
            "- Span metadata (ID, name, type, timing)\n"
            "- Status and error information\n"
            "- Type-specific attributes (model, tokens, tool params, etc.)\n\n"
            "**Span Hierarchy (full trace):**\n"
            "The `tree` field contains root spans, each with potential `children`.\n"
            "This recursive structure represents the execution flow:\n"
            "```\n"
            "Agent.run (root)\n"
            "  ├─ LLM.invoke\n"
            "  ├─ Tool.execute\n"
            "  │   └─ LLM.invoke (nested)\n"
            "  └─ LLM.invoke\n"
            "```\n\n"
            "**Span Types:**\n"
            "- `AGENT`: Agent execution with input/output\n"
            "- `LLM`: Model invocations with tokens and prompts\n"
            "- `TOOL`: Tool calls with parameters and results"
        ),
        responses={
            200: {
                "description": "Trace or span detail retrieved successfully",
                "content": {
                    "application/json": {
                        "examples": {
                            "full_trace": {
                                "summary": "Full trace with hierarchy (no span_id)",
                                "value": {
                                    "trace_id": "a1b2c3d4",
                                    "name": "Stock_Price_Agent.run",
                                    "status": "OK",
                                    "duration": "1.2s",
                                    "start_time": "2025-11-19T10:30:00.000000+00:00",
                                    "end_time": "2025-11-19T10:30:01.200000+00:00",
                                    "total_spans": 4,
                                    "error_count": 0,
                                    "input": "What is Tesla stock price?",
                                    "output": "The current price of Tesla (TSLA) is $245.67.",
                                    "error": None,
                                    "run_id": "run123",
                                    "session_id": "session456",
                                    "user_id": "user789",
                                    "agent_id": "stock_agent",
                                    "team_id": None,
                                    "workflow_id": None,
                                    "created_at": "2025-11-19T10:30:00+00:00",
                                    "tree": [
                                        {
                                            "id": "span1",
                                            "name": "Stock_Price_Agent.run",
                                            "type": "AGENT",
                                            "duration": "1.2s",
                                            "status": "OK",
                                            "input": None,
                                            "output": None,
                                            "error": None,
                                            "spans": [],
                                        }
                                    ],
                                },
                            },
                            "single_span": {
                                "summary": "Single span detail (with span_id)",
                                "value": {
                                    "id": "span2",
                                    "name": "gpt-4o-mini.invoke",
                                    "type": "LLM",
                                    "duration": "800ms",
                                    "status": "OK",
                                    "metadata": {"model": "gpt-4o-mini", "input_tokens": 120},
                                },
                            },
                        }
                    }
                },
            },
            404: {"description": "Trace or span not found", "model": NotFoundResponse},
        },
    )
    async def get_trace(
        request: Request,
        trace_id: str,
        span_id: Optional[str] = Query(default=None, description="Optional: Span ID to retrieve specific span"),
        run_id: Optional[str] = Query(default=None, description="Optional: Run ID to retrieve trace for"),
        db_id: Optional[str] = Query(default=None, description="Database ID to query trace from"),
    ):
        """Get detailed trace with hierarchical span tree, or a specific span within the trace"""
        # Get database using db_id or default to first available
        db = await get_db(dbs, db_id)

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.get_trace(
                trace_id=trace_id,
                span_id=span_id,
                run_id=run_id,
                db_id=db_id,
                headers=headers,
            )

        try:
            # If span_id is provided, return just that span
            if span_id:
                if isinstance(db, AsyncBaseDb):
                    span = await db.get_span(span_id)
                else:
                    span = db.get_span(span_id)

                if span is None:
                    raise HTTPException(status_code=404, detail="Span not found")

                # Verify the span belongs to the requested trace
                if span.trace_id != trace_id:
                    raise HTTPException(status_code=404, detail=f"Span {span_id} does not belong to trace {trace_id}")

                # Convert to TraceNode (without children since we're fetching a single span)
                return TraceNode.from_span(span, spans=None)

            # Otherwise, return full trace with hierarchy
            # Get trace
            if isinstance(db, AsyncBaseDb):
                trace = await db.get_trace(trace_id=trace_id, run_id=run_id)
            else:
                trace = db.get_trace(trace_id=trace_id, run_id=run_id)

            if trace is None:
                raise HTTPException(status_code=404, detail="Trace not found")

            # Get all spans for this trace
            if isinstance(db, AsyncBaseDb):
                spans = await db.get_spans(trace_id=trace_id)
            else:
                spans = db.get_spans(trace_id=trace_id)

            # Build hierarchical response
            return TraceDetail.from_trace_and_spans(trace, spans)

        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error retrieving trace {trace_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Error retrieving trace: {str(e)}")

    @router.get(
        "/trace_session_stats",
        response_model=PaginatedResponse[TraceSessionStats],
        response_model_exclude_none=True,
        tags=["Traces"],
        operation_id="get_trace_stats",
        summary="Get Trace Statistics by Session",
        description=(
            "Retrieve aggregated trace statistics grouped by session ID with pagination.\n\n"
            "**Provides insights into:**\n"
            "- Total traces per session\n"
            "- First and last trace timestamps per session\n"
            "- Associated user and agent information\n\n"
            "**Filtering Options:**\n"
            "- By user ID\n"
            "- By agent ID\n\n"
            "**Use Cases:**\n"
            "- Monitor session-level activity\n"
            "- Track conversation flows\n"
            "- Identify high-activity sessions\n"
            "- Analyze user engagement patterns"
        ),
        responses={
            200: {
                "description": "Trace statistics retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "data": [
                                {
                                    "session_id": "37029bc6-1794-4ba8-a629-1efedc53dcad",
                                    "user_id": "kaustubh@agno.com",
                                    "agent_id": "hackernews-agent",
                                    "team_id": None,
                                    "total_traces": 5,
                                    "first_trace_at": "2025-11-19T10:15:16+00:00",
                                    "last_trace_at": "2025-11-19T10:21:30+00:00",
                                }
                            ],
                            "meta": {
                                "page": 1,
                                "limit": 20,
                                "total_pages": 3,
                                "total_count": 45,
                            },
                        }
                    }
                },
            },
            500: {"description": "Failed to retrieve statistics", "model": InternalServerErrorResponse},
        },
    )
    async def get_trace_stats(
        request: Request,
        user_id: Optional[str] = Query(default=None, description="Filter by user ID"),
        agent_id: Optional[str] = Query(default=None, description="Filter by agent ID"),
        team_id: Optional[str] = Query(default=None, description="Filter by team ID"),
        workflow_id: Optional[str] = Query(default=None, description="Filter by workflow ID"),
        start_time: Optional[str] = Query(
            default=None,
            description="Filter sessions with traces created after this time (ISO 8601 format with timezone, e.g., '2025-11-19T10:00:00Z' or '2025-11-19T15:30:00+05:30'). Times are converted to UTC for comparison.",
        ),
        end_time: Optional[str] = Query(
            default=None,
            description="Filter sessions with traces created before this time (ISO 8601 format with timezone, e.g., '2025-11-19T11:00:00Z' or '2025-11-19T16:30:00+05:30'). Times are converted to UTC for comparison.",
        ),
        page: int = Query(default=1, description="Page number (1-indexed)", ge=1),
        limit: int = Query(default=20, description="Number of sessions per page", ge=1),
        db_id: Optional[str] = Query(default=None, description="Database ID to query statistics from"),
    ):
        """Get trace statistics grouped by session"""
        import time as time_module

        # Get database using db_id or default to first available
        db = await get_db(dbs, db_id)

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.get_trace_session_stats(
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                workflow_id=workflow_id,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
                page=page,
                db_id=db_id,
                headers=headers,
            )

        try:
            start_time_ms = time_module.time() * 1000

            # Convert ISO datetime strings to UTC datetime objects
            start_time_dt = timestamp_to_datetime(start_time, "start_time") if start_time else None
            end_time_dt = timestamp_to_datetime(end_time, "end_time") if end_time else None

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

            end_time_ms = time_module.time() * 1000
            search_time_ms = round(end_time_ms - start_time_ms, 2)

            # Calculate total pages
            total_pages = (total_count + limit - 1) // limit if limit > 0 else 0

            # Convert stats to response models (Pydantic auto-serializes datetime to ISO 8601)
            stats_response = [
                TraceSessionStats(
                    session_id=stat["session_id"],
                    user_id=stat.get("user_id"),
                    agent_id=stat.get("agent_id"),
                    team_id=stat.get("team_id"),
                    workflow_id=stat.get("workflow_id"),
                    total_traces=stat["total_traces"],
                    first_trace_at=stat["first_trace_at"],
                    last_trace_at=stat["last_trace_at"],
                )
                for stat in stats_list
            ]

            return PaginatedResponse(
                data=stats_response,
                meta=PaginationInfo(
                    page=page,
                    limit=limit,
                    total_pages=total_pages,
                    total_count=total_count,
                    search_time_ms=search_time_ms,
                ),
            )

        except Exception as e:
            log_error(f"Error retrieving trace statistics: {e}")
            raise HTTPException(status_code=500, detail=f"Error retrieving statistics: {str(e)}")

    return router
