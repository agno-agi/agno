from datetime import date
from typing import List, Optional

from fastapi import HTTPException, Query
from fastapi.routing import APIRouter

from agno.db.base import BaseDb
from agno.os.managers.metrics.schemas import DayAggregatedMetrics


def attach_routes(router: APIRouter, db: BaseDb) -> APIRouter:
    @router.get("/metrics", response_model=List[DayAggregatedMetrics], status_code=200)
    async def get_metrics(
        starting_date: Optional[date] = Query(default=None, description="Starting date to filter metrics (YYYY-MM-DD)"),
        ending_date: Optional[date] = Query(default=None, description="Ending date to filter metrics (YYYY-MM-DD)"),
    ) -> List[DayAggregatedMetrics]:
        try:
            metrics = db.get_metrics_raw(starting_date=starting_date, ending_date=ending_date)
            return [DayAggregatedMetrics.from_dict(metric) for metric in metrics]
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error getting metrics: {str(e)}")

    @router.post("/metrics/refresh", response_model=List[DayAggregatedMetrics], status_code=200)
    async def calculate_metrics() -> List[DayAggregatedMetrics]:
        try:
            result = db.calculate_metrics()
            if result is None:
                return []
            return [DayAggregatedMetrics.from_dict(metric) for metric in result]
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error refreshing metrics: {str(e)}")

    return router
