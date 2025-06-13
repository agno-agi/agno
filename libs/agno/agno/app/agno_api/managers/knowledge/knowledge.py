import logging

from fastapi.routing import APIRouter

from agno.app.agno_api.base import BaseInterface
from agno.app.agno_api.managers.knowledge.async_router import attach_async_routes
from agno.app.agno_api.managers.knowledge.sync_router import attach_sync_routes
from agno.knowledge.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)


class Knowledge(BaseInterface):
    type = "knowledge"

    router: APIRouter

    def __init__(self, knowledge: KnowledgeBase):
        self.knowledge = knowledge

    def get_router(self, use_async: bool = True) -> APIRouter:
        # Cannot be overridden
        prefix: str = "/knowledge"
        version: str = "/v1"
        self.router = APIRouter(prefix=prefix + version, tags=["Knowledge"])

        if use_async:
            self.router = attach_async_routes(router=self.router, knowledge=self.knowledge)
        else:
            self.router = attach_sync_routes(router=self.router, knowledge=self.knowledge)

        return self.router
