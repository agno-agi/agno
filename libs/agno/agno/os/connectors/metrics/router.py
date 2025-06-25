from typing import List

from fastapi.routing import APIRouter

from agno.db.base import BaseDb
from agno.os.connectors.metrics.schemas import AggregatedMetrics
from agno.os.connectors.utils import PaginatedResponse


def attach_routes(router: APIRouter, db: BaseDb) -> APIRouter:
    @router.get("/metrics", response_model=PaginatedResponse[AggregatedMetrics], status_code=200)
    async def get_metrics() -> PaginatedResponse[AggregatedMetrics]:
        return PaginatedResponse()

    @router.post("/metrics", response_model=List[AggregatedMetrics], status_code=200)
    async def upsert_metrics(metrics: AggregatedMetrics) -> AggregatedMetrics:
        return []

    return router
