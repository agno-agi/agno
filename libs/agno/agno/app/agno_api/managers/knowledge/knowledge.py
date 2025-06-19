import logging

from fastapi.routing import APIRouter

from agno.app.agno_api.base import BaseInterface
from agno.knowledge.knowledge import Knowledge
from agno.app.agno_api.managers.knowledge.async_router import attach_async_routes
from agno.app.agno_api.managers.knowledge.sync_router import attach_sync_routes
from agno.knowledge.knowledge import Knowledge
from agno.utils.log import log_info

logger = logging.getLogger(__name__)


class KnowledgeInterface(BaseInterface):
    type = "knowledge_interface"

    router: APIRouter

    def __init__(self, knowledge: Knowledge):
        self.knowledge = knowledge

    def get_router(self, use_async: bool = True) -> APIRouter:
        # Cannot be overridden
        prefix: str = "/knowledge"
        version: str = "/v1"
        self.router = APIRouter(prefix=prefix + version, tags=["Knowledge"])

        use_async = False
        if use_async:
            log_info(f"Using async routes")
            self.router = attach_async_routes(router=self.router, knowledge=self.knowledge)
        else:
            log_info(f"Using sync routes")
            self.router = attach_sync_routes(router=self.router, knowledge=self.knowledge)

        return self.router
