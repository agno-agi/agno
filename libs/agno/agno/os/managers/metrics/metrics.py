import logging
from typing import Optional

from fastapi.routing import APIRouter

from agno.db.base import BaseDb
from agno.os.managers.base import BaseManager
from agno.os.managers.metrics.router import attach_routes

logger = logging.getLogger(__name__)


class MetricsManager(BaseManager):
    type = "metrics"

    router: APIRouter

    def __init__(self, db: BaseDb, name: Optional[str] = None):
        self.name = name
        self.db = db

    def get_router(self, index: int) -> APIRouter:
        if not self.name:
            self.name = f"Metrics Manager {index}"

        self.router_prefix = f"/metric/{index}"

        # Cannot be overridden
        self.router = APIRouter(prefix=self.router_prefix, tags=["Metrics"])

        self.router = attach_routes(router=self.router, db=self.db)

        return self.router
