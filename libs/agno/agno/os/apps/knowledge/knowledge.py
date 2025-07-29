import logging
from typing import Optional

from fastapi import Depends
from fastapi.routing import APIRouter

from agno.knowledge.knowledge import Knowledge
from agno.os.apps.base import BaseApp
from agno.os.apps.knowledge.router import attach_routes
from agno.os.auth import get_authentication_dependency
from agno.os.settings import AgnoAPISettings

logger = logging.getLogger(__name__)


class KnowledgeApp(BaseApp):
    type = "knowledge"

    router: APIRouter

    def __init__(self, knowledge: Knowledge, name: Optional[str] = None):
        self.name = name
        self.knowledge = knowledge

    def get_router(self, index: int, settings: AgnoAPISettings = AgnoAPISettings()) -> APIRouter:
        if not self.name:
            self.name = f"Knowledge App {index}"

        self.router_prefix = f"/knowledge/{index}"

        # Cannot be overridden
        self.router = APIRouter(
            prefix=self.router_prefix,
            tags=["Knowledge"],
            dependencies=[Depends(get_authentication_dependency(settings))],
        )

        self.router = attach_routes(router=self.router, knowledge=self.knowledge)

        return self.router
