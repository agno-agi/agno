import logging
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import Depends, HTTPException, Query
from fastapi.routing import APIRouter

from agno.db.base import BaseDb
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


def get_metrics_router(dbs: dict[str, BaseDb], settings: AgnoAPISettings = AgnoAPISettings(), **kwargs) -> APIRouter:
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


def attach_routes(router: APIRouter, dbs: dict[str, BaseDb]) -> APIRouter:
    @router.get(
        "/metrics",
        response_model=MetricsResponse,
        status_code=200,
        operation_id="get_metrics",
        summary="Get System Metrics",
        description=(
            "Retrieve system metrics and analytics data for a specified date range. "
            "Provides insights into system usage, performance, and user activity patterns. "
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
                                    "date": "2024-01-15",
                                    "total_requests": 1250,
                                    "unique_users": 45,
                                    "avg_response_time": 0.85,
                                    "error_rate": 0.02,
                                    "agent_runs": 120,
                                    "team_runs": 35,
                                    "eval_runs": 15,
                                    "memory_operations": 75,
                                    "knowledge_uploads": 8,
                                },
                                {
                                    "date": "2024-01-14",
                                    "total_requests": 980,
                                    "unique_users": 38,
                                    "avg_response_time": 0.92,
                                    "error_rate": 0.015,
                                    "agent_runs": 95,
                                    "team_runs": 28,
                                    "eval_runs": 12,
                                    "memory_operations": 62,
                                    "knowledge_uploads": 5,
                                },
                            ],
                            "updated_at": "2024-01-15T23:59:59Z",
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
                                "date": "2024-01-15",
                                "total_requests": 1250,
                                "unique_users": 45,
                                "avg_response_time": 0.85,
                                "error_rate": 0.02,
                                "agent_runs": 120,
                                "team_runs": 35,
                                "eval_runs": 15,
                                "memory_operations": 75,
                                "knowledge_uploads": 8,
                                "peak_concurrent_users": 12,
                                "total_tokens_consumed": 45200,
                                "avg_session_duration": 18.5,
                            },
                            {
                                "date": "2024-01-14",
                                "total_requests": 980,
                                "unique_users": 38,
                                "avg_response_time": 0.92,
                                "error_rate": 0.015,
                                "agent_runs": 95,
                                "team_runs": 28,
                                "eval_runs": 12,
                                "memory_operations": 62,
                                "knowledge_uploads": 5,
                                "peak_concurrent_users": 9,
                                "total_tokens_consumed": 38750,
                                "avg_session_duration": 16.2,
                            },
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
            result = db.calculate_metrics()
            if result is None:
                return []

            return [DayAggregatedMetrics.from_dict(metric) for metric in result]

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error refreshing metrics: {str(e)}")

    return router
