import logging
from typing import Optional
from uuid import uuid4

from fastapi.routing import APIRouter

from agno.os.connectors.base import BaseConnector
from agno.os.connectors.memory.router import attach_routes
from agno.memory import Memory

logger = logging.getLogger(__name__)


class MemoryConnector(BaseConnector):
    type = "memory"
    
    router: APIRouter

    def __init__(self, memory: Memory, connector_id: Optional[str] = None):
        self.connector_id = connector_id or str(uuid4())
        self.memory = memory
        self.router_prefix = f"/memory-connectors/{self.connector_id}"

    def get_router(self) -> APIRouter:
        # Cannot be overridden
        self.router = APIRouter(prefix=self.router_prefix, tags=["Memory"])

        self.router = attach_routes(router=self.router, memory=self.memory)

        return self.router
