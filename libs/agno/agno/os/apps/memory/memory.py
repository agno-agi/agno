import logging
from typing import Optional

from fastapi.routing import APIRouter

from agno.db.base import BaseDb
from agno.os.apps.base import BaseApp
from agno.os.apps.memory.router import attach_routes

logger = logging.getLogger(__name__)


class MemoryApp(BaseApp):
    type = "memory"

    router: APIRouter

    def __init__(self, db: BaseDb, name: Optional[str] = None):
        self.name = name
        self.db = db

    def get_router(self, index: int) -> APIRouter:
        if not self.name:
            self.name = f"Memory App {index}"

        self.router_prefix = f"/memory/{index}"

        # Cannot be overridden
        self.router = APIRouter(prefix=self.router_prefix, tags=["Memory"])

        self.router = attach_routes(router=self.router, db=self.db)

        return self.router
