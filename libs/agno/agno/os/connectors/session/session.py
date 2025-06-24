import logging
from typing import Optional
from uuid import uuid4

from fastapi.routing import APIRouter

from agno.os.connectors.base import BaseConnector
from agno.os.connectors.session.router import attach_routes
from agno.db.base import BaseDb

logger = logging.getLogger(__name__)


class SessionConnector(BaseConnector):
    type = "session"

    router: APIRouter

    def __init__(self, db: BaseDb, connector_id: Optional[str] = None):
        self.connector_id = connector_id or str(uuid4())
        self.db = db
        self.router_prefix = f"/session-connectors/{self.connector_id}"

    def get_router(self) -> APIRouter:
        # Cannot be overridden
        self.router = APIRouter(prefix=self.router_prefix, tags=["Session"])

        self.router = attach_routes(router=self.router, db=self.db)

        return self.router
