from typing import List, Optional

from fastapi import HTTPException, Query
from fastapi.routing import APIRouter

from agno.db.base import BaseDb
from agno.os.connectors.metrics.schemas import AggregatedMetrics


def attach_routes(router: APIRouter, db: BaseDb) -> APIRouter:
    @router.get("/metrics", response_model=List[AggregatedMetrics], status_code=200)
    async def get_metrics(
        starting_date: Optional[str] = Query(default=None, description="Starting date to filter metrics"),
        ending_date: Optional[str] = Query(default=None, description="Ending date to filter metrics"),
    ) -> List[AggregatedMetrics]:
        try:
            metrics = db.get_metrics_raw(starting_date=starting_date, ending_date=ending_date)
            return [AggregatedMetrics.from_dict(metric) for metric in metrics]
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error getting metrics: {str(e)}")

    @router.post("/metrics/refresh", response_model=List[AggregatedMetrics], status_code=200)
    async def refresh_metrics() -> List[AggregatedMetrics]:
        try:
            result = db.refresh_metrics()
            if result is None:
                return []
            return [AggregatedMetrics.from_dict(metric) for metric in result]
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error refreshing metrics: {str(e)}")

    return router
