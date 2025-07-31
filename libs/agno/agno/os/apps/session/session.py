import logging
from typing import Optional

from fastapi import Depends
from fastapi.routing import APIRouter

from agno.db.base import BaseDb
from agno.os.apps.base import BaseApp
from agno.os.apps.session.router import attach_routes
from agno.os.auth import get_authentication_dependency
from agno.os.settings import AgnoAPISettings

logger = logging.getLogger(__name__)


class SessionApp(BaseApp):
    type = "session"

    router: APIRouter

    def __init__(self, db: BaseDb, name: Optional[str] = None):
        self.name = name or "Session App"
        self.db = db

    def get_router(self, index: int, settings: AgnoAPISettings = AgnoAPISettings(), **kwargs) -> APIRouter:
        if not self.name:
            self.name = f"Session App {index}"

        self.router_prefix = f"/session/{index}"

        # Cannot be overridden
        self.router = APIRouter(
            prefix=self.router_prefix, tags=["Session"], dependencies=[Depends(get_authentication_dependency(settings))]
        )

        self.router = attach_routes(router=self.router, db=self.db)

        return self.router
