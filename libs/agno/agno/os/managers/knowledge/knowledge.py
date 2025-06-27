import logging
from typing import Optional

from fastapi.routing import APIRouter

from agno.knowledge.knowledge import Knowledge
from agno.os.managers.base import BaseManager
from agno.os.managers.knowledge.router import attach_routes

logger = logging.getLogger(__name__)


class KnowledgeManager(BaseManager):
    type = "knowledge"

    router: APIRouter

    def __init__(self, knowledge: Knowledge, name: Optional[str] = None):
        self.name = name
        self.knowledge = knowledge

    def get_router(self, index: int) -> APIRouter:
        if not self.name:
            self.name = f"Knowledge Manager {index}"

        self.router_prefix = f"/knowledge/{index}"

        # Cannot be overridden
        self.router = APIRouter(prefix=self.router_prefix, tags=["Knowledge"])

        self.router = attach_routes(router=self.router, knowledge=self.knowledge)

        return self.router
