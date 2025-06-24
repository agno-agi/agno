from typing import List

from fastapi.routing import APIRouter

from agno.agent import Agent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.playground.router import attach_routes
from agno.team import Team
from agno.workflow import Workflow


class Playground(BaseInterface):
    type = "playground"

    router: APIRouter

    def get_router(self, agents: List[Agent], teams: List[Team], workflows: List[Workflow]) -> APIRouter:
        self.router_prefix = "/playground"
        # Cannot be overridden
        self.router = APIRouter(prefix=self.router_prefix, tags=["Playground"])

        self.router = attach_routes(router=self.router, agents=agents, workflows=workflows, teams=teams)

        return self.router
