import logging
from typing import Optional
from uuid import uuid4

from fastapi.routing import APIRouter

from agno.memory import Memory
from agno.os.apps.base import BaseApp
from agno.os.apps.memory.router import attach_routes

logger = logging.getLogger(__name__)


class MemoryApp(BaseApp):
    type = "memory"

    router: APIRouter

    def __init__(self, memory: Memory, name: Optional[str] = None):
        self.name = name
        self.memory = memory

    def get_router(self, index: int) -> APIRouter:
        if not self.name:
            self.name = f"Memory App {index}"

        self.router_prefix = f"/memory/{index}"

        # Cannot be overridden
        self.router = APIRouter(prefix=self.router_prefix, tags=["Memory"])

        self.router = attach_routes(router=self.router, memory=self.memory)

        return self.router
