import logging
from typing import List, Optional

from fastapi.routing import APIRouter

from agno.agent.agent import Agent
from agno.db.base import BaseDb
from agno.os.managers.base import BaseManager
from agno.os.managers.eval.router import attach_routes
from agno.team.team import Team

logger = logging.getLogger(__name__)


class EvalManager(BaseManager):
    type = "eval"

    router: APIRouter

    def __init__(self, db: BaseDb, name: Optional[str] = None):
        self.name = name
        self.db = db

    def get_router(self, index: int, agents: List[Agent], teams: List[Team]) -> APIRouter:
        if not self.name:
            self.name = f"Eval Manager {index}"

        self.router_prefix = f"/eval/{index}"

        # Cannot be overridden
        self.router = APIRouter(prefix=self.router_prefix, tags=["Eval"])

        self.router = attach_routes(router=self.router, db=self.db, agents=agents, teams=teams)

        return self.router
