import logging
from datetime import date, datetime, timezone
from typing import List, Optional, Union, cast

from fastapi import Depends, HTTPException, Query
from fastapi.routing import APIRouter

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.auth import get_authentication_dependency
from agno.os.routers.metrics.schemas import DayAggregatedMetrics, MetricsResponse
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import get_db

logger = logging.getLogger(__name__)


def get_metrics_router(
    dbs: dict[str, Union[BaseDb, AsyncBaseDb]], settings: AgnoAPISettings = AgnoAPISettings(), **kwargs
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


def attach_routes(router: APIRouter, dbs: dict[str, Union[BaseDb, AsyncBaseDb]]) -> APIRouter:
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
                                    "date": "2025-07-31T00:00:00",
                                    "created_at": 1753993132,
                                    "updated_at": 1753993741,
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
        starting_date: Optional[date] = Query(
            default=None, description="Starting date for metrics range (YYYY-MM-DD format)"
        ),
        ending_date: Optional[date] = Query(
            default=None, description="Ending date for metrics range (YYYY-MM-DD format)"
        ),
        db_id: Optional[str] = Query(default=None, description="Database ID to query metrics from"),
    ) -> MetricsResponse:
        try:
            db = get_db(dbs, db_id)
            if isinstance(db, AsyncBaseDb):
                db = cast(AsyncBaseDb, db)
                metrics, latest_updated_at = await db.get_metrics(starting_date=starting_date, ending_date=ending_date)
            else:
                metrics, latest_updated_at = db.get_metrics(starting_date=starting_date, ending_date=ending_date)

            return MetricsResponse(
                metrics=[DayAggregatedMetrics.from_dict(metric) for metric in metrics],
                updated_at=datetime.fromtimestamp(latest_updated_at, tz=timezone.utc)
                if latest_updated_at is not None
                else None,
            )

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error getting metrics: {str(e)}")

    @router.post(
        "/metrics/refresh",
        response_model=List[DayAggregatedMetrics],
        status_code=200,
        operation_id="refresh_metrics",
        summary="Refresh Metrics",
        description=(
            "Manually trigger recalculation of system metrics from raw data. "
            "This operation analyzes system activity logs and regenerates aggregated metrics. "
            "Useful for ensuring metrics are up-to-date or after system maintenance."
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
                                    "audio_total_tokens": 0,
                                    "audio_input_tokens": 0,
                                    "audio_output_tokens": 0,
                                    "cache_read_tokens": 0,
                                    "cache_write_tokens": 0,
                                    "reasoning_tokens": 0,
                                },
                                "model_metrics": [{"model_id": "gpt-4o", "model_provider": "OpenAI", "count": 2}],
                                "date": "2025-08-12T00:00:00",
                                "created_at": 1755016907,
                                "updated_at": 1755016907,
                            }
                        ]
                    }
                },
            },
            500: {"description": "Failed to refresh metrics", "model": InternalServerErrorResponse},
        },
    )
    async def calculate_metrics(
        db_id: Optional[str] = Query(default=None, description="Database ID to use for metrics calculation"),
    ) -> List[DayAggregatedMetrics]:
        try:
            db = get_db(dbs, db_id)
            if isinstance(db, AsyncBaseDb):
                db = cast(AsyncBaseDb, db)
                result = await db.calculate_metrics()
            else:
                result = db.calculate_metrics()
            if result is None:
                return []

            return [DayAggregatedMetrics.from_dict(metric) for metric in result]

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error refreshing metrics: {str(e)}")

    return router
