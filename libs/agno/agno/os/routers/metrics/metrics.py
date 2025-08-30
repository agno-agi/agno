import logging
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import Depends, HTTPException, Query
from fastapi.routing import APIRouter

from agno.db.base import BaseDb
from agno.os.auth import get_authentication_dependency
from agno.os.routers.metrics.schemas import DayAggregatedMetrics, MetricsResponse
from agno.os.settings import AgnoAPISettings
from agno.os.utils import get_db

logger = logging.getLogger(__name__)


def get_metrics_router(dbs: dict[str, BaseDb], settings: AgnoAPISettings = AgnoAPISettings(), **kwargs) -> APIRouter:
    router = APIRouter(dependencies=[Depends(get_authentication_dependency(settings))], tags=["Metrics"])
    return attach_routes(router=router, dbs=dbs)


def attach_routes(router: APIRouter, dbs: dict[str, BaseDb]) -> APIRouter:
    @router.get("/metrics", response_model=MetricsResponse, status_code=200)
    async def get_metrics(
        starting_date: Optional[date] = Query(default=None, description="Starting date to filter metrics (YYYY-MM-DD)"),
        ending_date: Optional[date] = Query(default=None, description="Ending date to filter metrics (YYYY-MM-DD)"),
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
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

    @router.post("/metrics/refresh", response_model=List[DayAggregatedMetrics], status_code=200)
    async def calculate_metrics(
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
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
