import logging
from typing import Optional, Union

from fastapi import Depends, HTTPException, Query
from fastapi.routing import APIRouter

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.auth import get_authentication_dependency
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
from agno.os.utils import get_db
from agno.utils.log import log_error

logger = logging.getLogger(__name__)


def get_traces_router(
    dbs: dict[str, Union[BaseDb, AsyncBaseDb]], settings: AgnoAPISettings = AgnoAPISettings(), **kwargs
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


def attach_routes(router: APIRouter, dbs: dict[str, Union[BaseDb, AsyncBaseDb]]) -> APIRouter:
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
                                    "start_time": 1234567890000000,
                                    "total_spans": 4,
                                    "error_count": 0,
                                    "input": "What is the stock price of NVDA?",
                                    "run_id": "run123",
                                    "session_id": "session456",
                                    "user_id": "user789",
                                    "agent_id": "agent_stock",
                                    "team_id": None,
                                    "created_at": 1234567890,
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
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        page: int = 1,
        limit: int = 20,
        db_id: Optional[str] = Query(default=None, description="Database ID to query traces from"),
    ):
        """Get list of traces with optional filters and pagination"""
        import inspect
        import time as time_module

        # Get database using db_id or default to first available
        db = get_db(dbs, db_id)

        try:
            start_time_ms = time_module.time() * 1000

            # Get traces and total count in a single call
            traces_result = db.get_traces(
                run_id=run_id,
                session_id=session_id,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                status=status,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
                page=page,
            )

            if inspect.iscoroutine(traces_result):
                result = await traces_result
            else:
                result = traces_result

            traces, total_count = result

            end_time_ms = time_module.time() * 1000
            search_time_ms = round(end_time_ms - start_time_ms, 2)

            # Calculate total pages
            total_pages = (total_count + limit - 1) // limit if limit > 0 else 0

            trace_inputs = {}
            for trace in traces:
                spans_result = db.get_spans(trace_id=trace.trace_id)
                if inspect.iscoroutine(spans_result):
                    spans = await spans_result
                else:
                    spans = spans_result

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
                                    "start_time": 1234567890000000,
                                    "end_time": 1234567891200000,
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
                                    "created_at": 1234567890,
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
        trace_id: str,
        span_id: Optional[str] = Query(default=None, description="Optional: Span ID to retrieve specific span"),
        run_id: Optional[str] = Query(default=None, description="Optional: Run ID to retrieve trace for"),
        db_id: Optional[str] = Query(default=None, description="Database ID to query trace from"),
    ):
        """Get detailed trace with hierarchical span tree, or a specific span within the trace"""
        # Get database using db_id or default to first available
        db = get_db(dbs, db_id)

        # Verify the database has trace support
        if not hasattr(db, "get_trace") or not hasattr(db, "get_spans"):
            raise HTTPException(status_code=500, detail="Selected database does not support traces")

        try:
            import inspect

            # If span_id is provided, return just that span
            if span_id:
                span_result = db.get_span(span_id)
                if inspect.iscoroutine(span_result):
                    span = await span_result
                else:
                    span = span_result

                if span is None:
                    raise HTTPException(status_code=404, detail="Span not found")

                # Verify the span belongs to the requested trace
                if span.trace_id != trace_id:
                    raise HTTPException(status_code=404, detail=f"Span {span_id} does not belong to trace {trace_id}")

                # Convert to TraceNode (without children since we're fetching a single span)
                return TraceNode.from_span(span, spans=None)

            # Otherwise, return full trace with hierarchy
            # Get trace
            trace_result = db.get_trace(trace_id=trace_id, run_id=run_id)
            if inspect.iscoroutine(trace_result):
                trace = await trace_result
            else:
                trace = trace_result

            if trace is None:
                raise HTTPException(status_code=404, detail="Trace not found")

            # Get all spans for this trace
            spans_result = db.get_spans(trace_id=trace_id)
            if inspect.iscoroutine(spans_result):
                spans = await spans_result
            else:
                spans = spans_result

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
                                    "total_traces": 5,
                                    "first_trace_at": 1762156516,
                                    "last_trace_at": 1762156890,
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
        user_id: Optional[str] = Query(default=None, description="Filter by user ID"),
        agent_id: Optional[str] = Query(default=None, description="Filter by agent ID"),
        page: int = Query(default=1, description="Page number (1-indexed)", ge=1),
        limit: int = Query(default=20, description="Number of sessions per page", ge=1, le=100),
        db_id: Optional[str] = Query(default=None, description="Database ID to query statistics from"),
    ):
        """Get trace statistics grouped by session"""
        # Get database using db_id or default to first available
        db = get_db(dbs, db_id)

        # Verify the database has trace support
        if not hasattr(db, "get_trace_stats"):
            raise HTTPException(status_code=500, detail="Selected database does not support trace statistics")

        try:
            import inspect
            import time as time_module

            start_time_ms = time_module.time() * 1000

            # Get trace stats
            stats_result = db.get_trace_stats(
                user_id=user_id,
                agent_id=agent_id,
                limit=limit,
                page=page,
            )

            if inspect.iscoroutine(stats_result):
                result = await stats_result
            else:
                result = stats_result

            stats_list, total_count = result

            end_time_ms = time_module.time() * 1000
            search_time_ms = round(end_time_ms - start_time_ms, 2)

            # Calculate total pages
            total_pages = (total_count + limit - 1) // limit if limit > 0 else 0

            # Convert stats to response models
            stats_response = [
                TraceSessionStats(
                    session_id=stat["session_id"],
                    user_id=stat.get("user_id"),
                    agent_id=stat.get("agent_id"),
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
