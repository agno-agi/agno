import logging
from datetime import date, datetime, timezone
from typing import Optional, Union, cast

from fastapi import Depends, HTTPException, Query, Request, Header
from fastapi.routing import APIRouter

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.auth import get_auth_token_from_request, get_authentication_dependency
from agno.os.router.metrics.schema import DayAggregatedMetricsResponse, MetricsResponse
from agno.os.router.schema import (
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
        response_model_exclude_unset=True,
        status_code=200,
        operation_id="get_metrics",
        summary="Get AgentOS Metrics",
        description=(
            "Retrieve AgentOS metrics and analytics data for a specified date range. "
            "If no date range is specified, returns all available metrics. "
            "Use the refresh parameter to trigger recalculation of metrics from raw data."
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
        refresh: bool = Query(default=False, description="Trigger recalculation of metrics from raw data before returning"),
        starting_date: Optional[date] = Query(
            default=None, description="Starting date for metrics range (YYYY-MM-DD format)"
        ),
        ending_date: Optional[date] = Query(
            default=None, description="Ending date for metrics range (YYYY-MM-DD format)"
        ),
        db_id: Optional[str] = Header(default=None, alias="X-DB-ID", description="Database ID to query metrics from"),
        table: Optional[str] = Header(default=None, alias="X-TABLE-NAME", description="The database table to use"),
    ) -> MetricsResponse:
        try:
            db = await get_db(dbs, db_id, table)

            if isinstance(db, RemoteDb):
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                return await db.get_metrics(
                    refresh=refresh,
                    starting_date=starting_date,
                    ending_date=ending_date,
                    db_id=db_id,
                    table=table,
                    headers=headers,
                )

            if refresh:
                if isinstance(db, AsyncBaseDb):
                    result = await db.calculate_metrics()
                else:
                    result = db.calculate_metrics()
                    
                metrics = [DayAggregatedMetricsResponse.from_dict(metric) for metric in result or []]
                latest_updated_at = datetime.now(timezone.utc).isoformat()
                return MetricsResponse(
                    metrics=metrics,
                    updated_at=to_utc_datetime(latest_updated_at),
                )
            else:
                if isinstance(db, AsyncBaseDb):
                    db = cast(AsyncBaseDb, db)
                    metrics, latest_updated_at = await db.get_metrics(starting_date=starting_date, ending_date=ending_date)
                else:
                    metrics, latest_updated_at = db.get_metrics(starting_date=starting_date, ending_date=ending_date)

                return MetricsResponse(
                    metrics=[DayAggregatedMetricsResponse.from_dict(metric) for metric in metrics],
                    updated_at=to_utc_datetime(latest_updated_at),
                )

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error getting metrics: {str(e)}")

    return router
