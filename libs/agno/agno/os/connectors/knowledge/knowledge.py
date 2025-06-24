import logging
from typing import Optional
from uuid import uuid4

from fastapi.routing import APIRouter

from agno.os.connectors.base import BaseConnector
from agno.os.connectors.knowledge.router import attach_routes
from agno.knowledge.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)


class KnowledgeConnector(BaseConnector):
    type = "knowledge"

    router: APIRouter

    def __init__(self, knowledge: KnowledgeBase, connector_id: Optional[str] = None):
        self.connector_id = connector_id or str(uuid4())
        self.knowledge = knowledge
        self.router_prefix = f"/knowledge-connectors/{self.connector_id}"

    def get_router(self) -> APIRouter:
        # Cannot be overridden
        self.router = APIRouter(prefix=self.router_prefix, tags=["Knowledge"])

        self.router = attach_routes(router=self.router, knowledge=self.knowledge)

        return self.router

