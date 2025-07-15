import logging
from typing import Optional

from fastapi.routing import APIRouter

from agno.knowledge.knowledge import Knowledge
from agno.os.apps.base import BaseApp
from agno.os.apps.knowledge.router import attach_routes

logger = logging.getLogger(__name__)


class KnowledgeApp(BaseApp):
    type = "knowledge"

    router: APIRouter

    def __init__(self, knowledge: Knowledge, name: Optional[str] = None):
        self.name = name
        self.knowledge = knowledge

    def get_router(self, index: int) -> APIRouter:
        if not self.name:
            self.name = f"Knowledge App {index}"

        self.router_prefix = f"/knowledge/{index}"

        # Cannot be overridden
        self.router = APIRouter(prefix=self.router_prefix, tags=["Knowledge"])

        self.router = attach_routes(router=self.router, knowledge=self.knowledge)

        return self.router
