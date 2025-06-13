import logging

from fastapi.routing import APIRouter

from agno.app.agno_api.base import BaseInterface
from agno.app.agno_api.managers.storage.async_router import attach_async_routes
from agno.app.agno_api.managers.storage.sync_router import attach_sync_routes
from agno.db.base import Storage as StorageBase

logger = logging.getLogger(__name__)


class Storage(BaseInterface):
    type = "storage"

    router: APIRouter

    def __init__(self, storage: StorageBase):
        self.storage = storage

    def get_router(self, use_async: bool = True) -> APIRouter:
        # Cannot be overridden
        prefix: str = "/storage"
        version: str = "/v1"
        self.router = APIRouter(prefix=prefix + version, tags=["Storage"])

        if use_async:
            self.router = attach_async_routes(router=self.router, storage=self.storage)
        else:
            self.router = attach_sync_routes(router=self.router, storage=self.storage)

        return self.router
