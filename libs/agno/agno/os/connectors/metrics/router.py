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
        metrics = db.get_metrics_raw(starting_date=starting_date, ending_date=ending_date)
        return [AggregatedMetrics.from_dict(metric) for metric in metrics]

    @router.post("/metrics", response_model=AggregatedMetrics, status_code=200)
    async def upsert_metrics() -> AggregatedMetrics:
        """Upsert metrics in the database."""
        try:
            result = db.upsert_metrics()
            if result is None:
                raise HTTPException(status_code=500, detail="Failed to upsert metrics")
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error upserting metrics: {str(e)}")

    return router
