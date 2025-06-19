from typing import List

from fastapi.routing import APIRouter

from agno.agent import Agent
from agno.app.agno_api.base import BaseInterface
from agno.app.agno_api.interfaces.playground.async_router import attach_async_routes
from agno.app.agno_api.interfaces.playground.sync_router import attach_sync_routes
from agno.team import Team
from agno.workflow import Workflow


class Playground(BaseInterface):
    type = "playground"

    router: APIRouter

    def get_router(
        self, agents: List[Agent], teams: List[Team], workflows: List[Workflow], use_async: bool = True
    ) -> APIRouter:
        # Cannot be overridden
        prefix: str = "/playground"
        version: str = "/v1"
        self.router = APIRouter(prefix=prefix + version, tags=["Playground"])

        if use_async:
            self.router = attach_async_routes(router=self.router, agents=agents, workflows=workflows, teams=teams)
        else:
            self.router = attach_sync_routes(router=self.router, agents=agents, workflows=workflows, teams=teams)

        return self.router
