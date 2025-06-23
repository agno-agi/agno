import logging

from fastapi.routing import APIRouter

from agno.app.agno_api.managers.base import BaseManager
from agno.app.agno_api.managers.session.async_router import attach_async_routes
from agno.app.agno_api.managers.session.sync_router import attach_sync_routes
from agno.db.base import BaseDb

logger = logging.getLogger(__name__)


class SessionManager(BaseManager):
    type = "session"

    router: APIRouter

    def __init__(self, db: BaseDb):
        self.db = db

    def get_router(self, use_async: bool = True) -> APIRouter:
        # Cannot be overridden
        prefix: str = "/session"
        version: str = "/v1"
        self.router = APIRouter(prefix=prefix + version, tags=["Session"])

        if use_async:
            self.router = attach_async_routes(router=self.router, db=self.db)
        else:
            self.router = attach_sync_routes(router=self.router, db=self.db)

        return self.router
