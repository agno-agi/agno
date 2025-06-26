from typing import List

from fastapi.routing import APIRouter
from fastapi import HTTPException

from agno.db.base import BaseDb
from agno.os.connectors.metrics.schemas import AggregatedMetrics


def attach_routes(router: APIRouter, db: BaseDb) -> APIRouter:
    @router.get("/metrics", response_model=List[AggregatedMetrics], status_code=200)
    async def get_metrics() -> List[AggregatedMetrics]:
        """Get all metrics from the database."""
        try:
            metrics = db.get_metrics()
            return metrics
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error retrieving metrics: {str(e)}")

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
