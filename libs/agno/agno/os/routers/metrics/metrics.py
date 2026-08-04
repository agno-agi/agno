import logging
from datetime import date, datetime, timezone
from typing import List, Optional, Union

from fastapi import BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.routing import APIRouter
from starlette.concurrency import run_in_threadpool

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.auth import get_auth_token_from_request, get_authentication_dependency
from agno.os.routers.metrics.schemas import (
    DayAggregatedMetrics,
    MetricsRefreshResponse,
    MetricsRefreshStatusResponse,
    MetricsResponse,
)
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import get_db, to_utc_datetime
from agno.remote.base import RemoteDb

logger = logging.getLogger(__name__)


def get_metrics_router(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]], settings: AgnoAPISettings = AgnoAPISettings(), **kwargs
) -> APIRouter:
    """Create metrics router with comprehensive OpenAPI documentation for system metrics and analytics endpoints."""
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        tags=["Metrics"],
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
        "/metrics",
        response_model=MetricsResponse,
        status_code=200,
        operation_id="get_metrics",
        summary="Get AgentOS Metrics",
        description=(
            "Retrieve AgentOS metrics and analytics data for a specified date range. "
            "If no date range is specified, returns all available metrics."
        ),
        responses={
            200: {
                "description": "Metrics retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "metrics": [
                                {
                                    "id": "7bf39658-a00a-484c-8a28-67fd8a9ddb2a",
                                    "agent_runs_count": 5,
                                    "agent_sessions_count": 5,
                                    "team_runs_count": 0,
                                    "team_sessions_count": 0,
                                    "workflow_runs_count": 0,
                                    "workflow_sessions_count": 0,
                                    "users_count": 1,
                                    "token_metrics": {
                                        "input_tokens": 448,
                                        "output_tokens": 148,
                                        "total_tokens": 596,
                                        "audio_tokens": 0,
                                        "input_audio_tokens": 0,
                                        "output_audio_tokens": 0,
                                        "cached_tokens": 0,
                                        "cache_write_tokens": 0,
                                        "reasoning_tokens": 0,
                                    },
                                    "model_metrics": [{"model_id": "gpt-4o", "model_provider": "OpenAI", "count": 5}],
                                    "date": "2025-07-31T00:00:00Z",
                                    "created_at": "2025-07-31T12:38:52Z",
                                    "updated_at": "2025-07-31T12:49:01Z",
                                }
                            ]
                        }
                    }
                },
            },
            400: {"description": "Invalid date range parameters", "model": BadRequestResponse},
            500: {"description": "Failed to retrieve metrics", "model": InternalServerErrorResponse},
        },
    )
    async def get_metrics(
        request: Request,
        starting_date: Optional[date] = Query(
            default=None, description="Starting date for metrics range (YYYY-MM-DD format)"
        ),
        ending_date: Optional[date] = Query(
            default=None, description="Ending date for metrics range (YYYY-MM-DD format)"
        ),
        db_id: Optional[str] = Query(default=None, description="Database ID to query metrics from"),
        table: Optional[str] = Query(default=None, description="The database table to use"),
    ) -> MetricsResponse:
        try:
            db = await get_db(dbs, db_id, table)

            if isinstance(db, RemoteDb):
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                return await db.get_metrics(
                    starting_date=starting_date, ending_date=ending_date, db_id=db_id, table=table, headers=headers
                )

            if isinstance(db, AsyncBaseDb):
                metrics, latest_updated_at = await db.get_metrics(starting_date=starting_date, ending_date=ending_date)
            else:
                metrics, latest_updated_at = await run_in_threadpool(
                    db.get_metrics, starting_date=starting_date, ending_date=ending_date
                )

            return MetricsResponse(
                metrics=[DayAggregatedMetrics.from_dict(metric) for metric in metrics],
                updated_at=to_utc_datetime(latest_updated_at),
            )

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error getting metrics: {str(e)}")

    # Most recent refresh state per db id, doubling as the in-flight guard ('running').
    # Only mutated on the event loop (the sync calculation itself runs in the threadpool),
    # so no lock is needed. Per-process: each worker tracks the refreshes it started.
    refresh_states: dict[str, MetricsRefreshStatusResponse] = {}

    async def _do_refresh(
        db: Union[BaseDb, AsyncBaseDb, RemoteDb],
        db_id: Optional[str],
        table: Optional[str],
        headers: Optional[dict],
    ) -> None:
        refresh_key = str(db.id)
        current_state = refresh_states.get(refresh_key)
        started_at = current_state.started_at if current_state else None
        final_state = MetricsRefreshStatusResponse(status="completed", started_at=started_at)
        try:
            if isinstance(db, RemoteDb):
                await db.refresh_metrics(db_id=db_id, table=table, headers=headers, background=True)
            elif isinstance(db, AsyncBaseDb):
                await db.calculate_metrics()
            else:
                await run_in_threadpool(db.calculate_metrics)
        except Exception as e:
            logger.error(f"Metrics refresh failed: {e}")
            final_state = MetricsRefreshStatusResponse(status="failed", started_at=started_at, error=str(e))
        finally:
            final_state.finished_at = datetime.now(timezone.utc)
            refresh_states[refresh_key] = final_state

    @router.post(
        "/metrics/refresh",
        response_model=Union[List[DayAggregatedMetrics], MetricsRefreshResponse],
        status_code=200,
        operation_id="refresh_metrics",
        summary="Refresh Metrics",
        description=(
            "Manually trigger recalculation of system metrics from raw data. "
            "This operation analyzes system activity logs and regenerates aggregated metrics. "
            "Useful for ensuring metrics are up-to-date or after system maintenance. "
            "By default the refresh runs synchronously and returns the refreshed metrics. "
            "Pass background=true to run the refresh in the background instead: the endpoint "
            "returns 202 Accepted immediately and GET /metrics can be polled for results. "
            "If a background refresh is already in progress for the target database, "
            "returns status 'already_running' without starting a new one."
        ),
        responses={
            200: {
                "description": "Metrics refreshed successfully",
                "content": {
                    "application/json": {
                        "example": [
                            {
                                "id": "e77c9531-818b-47a5-99cd-59fed61e5403",
                                "agent_runs_count": 2,
                                "agent_sessions_count": 2,
                                "team_runs_count": 0,
                                "team_sessions_count": 0,
                                "workflow_runs_count": 0,
                                "workflow_sessions_count": 0,
                                "users_count": 1,
                                "token_metrics": {
                                    "input_tokens": 256,
                                    "output_tokens": 441,
                                    "total_tokens": 697,
                                },
                                "model_metrics": [{"model_id": "gpt-5.5", "model_provider": "OpenAI", "count": 2}],
                                "date": "2025-08-12T00:00:00Z",
                                "created_at": "2025-08-12T08:01:47Z",
                                "updated_at": "2025-08-12T08:01:47Z",
                            }
                        ]
                    }
                },
            },
            202: {
                "description": "Background refresh started",
                "content": {
                    "application/json": {
                        "example": {"status": "started", "message": "Metrics refresh started in background"}
                    }
                },
            },
            500: {"description": "Failed to refresh metrics", "model": InternalServerErrorResponse},
        },
    )
    async def calculate_metrics(
        request: Request,
        response: Response,
        background_tasks: BackgroundTasks,
        db_id: Optional[str] = Query(default=None, description="Database ID to use for metrics calculation"),
        table: Optional[str] = Query(default=None, description="Table to use for metrics calculation"),
        background: bool = Query(
            default=False, description="Run the refresh in the background and return 202 immediately"
        ),
    ) -> Union[List[DayAggregatedMetrics], MetricsRefreshResponse]:
        try:
            db = await get_db(dbs, db_id, table)

            headers = None
            if isinstance(db, RemoteDb):
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None

            if background:
                response.status_code = 202
                refresh_key = str(db.id)
                current_state = refresh_states.get(refresh_key)
                if current_state is not None and current_state.status == "running":
                    return MetricsRefreshResponse(
                        status="already_running", message="A metrics refresh is already in progress for this database"
                    )

                refresh_states[refresh_key] = MetricsRefreshStatusResponse(
                    status="running", started_at=datetime.now(timezone.utc)
                )
                background_tasks.add_task(_do_refresh, db, db_id, table, headers)

                return MetricsRefreshResponse(status="started", message="Metrics refresh started in background")

            if isinstance(db, RemoteDb):
                return await db.refresh_metrics(db_id=db_id, table=table, headers=headers)

            if isinstance(db, AsyncBaseDb):
                result = await db.calculate_metrics()
            else:
                result = await run_in_threadpool(db.calculate_metrics)
            if result is None:
                return []

            return [DayAggregatedMetrics.from_dict(metric) for metric in result]

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error refreshing metrics: {str(e)}")

    @router.get(
        "/metrics/refresh/status",
        response_model=MetricsRefreshStatusResponse,
        status_code=200,
        operation_id="get_metrics_refresh_status",
        summary="Get Metrics Refresh Status",
        description=(
            "Get the status of the most recent metrics refresh for the target database. "
            "Returns 'running' while a refresh is in progress, then 'completed' or 'failed' with "
            "the finish timestamp — the state updates even when a refresh completes without "
            "writing new data. Returns 'idle' if no refresh has been triggered since this server "
            "process started. For remote databases the status is fetched from the remote AgentOS. "
            "Intended for polling after starting a background refresh via POST /metrics/refresh?background=true."
        ),
        responses={
            200: {
                "description": "Current refresh status",
                "content": {
                    "application/json": {
                        "example": {
                            "status": "completed",
                            "started_at": "2025-08-12T08:01:47Z",
                            "finished_at": "2025-08-12T08:01:49Z",
                            "error": None,
                        }
                    }
                },
            },
            400: {"description": "Invalid request", "model": BadRequestResponse},
            404: {"description": "Database not found", "model": NotFoundResponse},
            500: {"description": "Failed to get refresh status", "model": InternalServerErrorResponse},
        },
    )
    async def get_metrics_refresh_status(
        request: Request,
        db_id: Optional[str] = Query(default=None, description="Database ID to get the refresh status for"),
        table: Optional[str] = Query(default=None, description="Table to get the refresh status for"),
    ) -> MetricsRefreshStatusResponse:
        try:
            db = await get_db(dbs, db_id, table)

            if isinstance(db, RemoteDb):
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                return await db.get_metrics_refresh_status(db_id=db_id, table=table, headers=headers)

            state = refresh_states.get(str(db.id))
            if state is None:
                return MetricsRefreshStatusResponse(status="idle")
            return state

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error getting metrics refresh status: {str(e)}")

    return router
