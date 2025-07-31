import logging
from typing import List, Optional

from fastapi import Depends
from fastapi.routing import APIRouter

from agno.agent.agent import Agent
from agno.db.base import BaseDb
from agno.os.apps.base import BaseApp
from agno.os.apps.eval.router import attach_routes
from agno.os.auth import get_authentication_dependency
from agno.os.settings import AgnoAPISettings
from agno.team.team import Team

logger = logging.getLogger(__name__)


class EvalApp(BaseApp):
    type = "eval"

    router: APIRouter

    def __init__(self, db: BaseDb, name: Optional[str] = None):
        self.name = name or "Eval App"
        self.db = db

    def get_router(  # type: ignore[override]
        self,
        index: int,
        agents: List[Agent],
        teams: List[Team],
        settings: AgnoAPISettings = AgnoAPISettings(),
        **kwargs,
    ) -> APIRouter:
        if not self.name:
            self.name = f"Eval App {index}"

        self.router_prefix = f"/eval/{index}"

        # Cannot be overridden
        self.router = APIRouter(
            prefix=self.router_prefix, tags=["Eval"], dependencies=[Depends(get_authentication_dependency(settings))]
        )

        self.router = attach_routes(router=self.router, db=self.db, agents=agents, teams=teams)

        return self.router
