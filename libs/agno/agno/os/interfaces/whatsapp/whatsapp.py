from typing import List, Optional

from fastapi.routing import APIRouter

from agno.agent import Agent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.whatsapp.router import attach_routes
from agno.team import Team
from agno.workflow.workflow import Workflow


class Whatsapp(BaseInterface):
    type = "whatsapp"

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
        workflow: Optional[Workflow] = None,
        prefix: str = "/whatsapp",
        tags: Optional[List[str]] = None,
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["Whatsapp"]

        if not (self.agent or self.team or self.workflow):
            raise ValueError("Whatsapp requires an agent, team or workflow")

    def get_router(self) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore

        self.router = attach_routes(router=self.router, agent=self.agent, team=self.team, workflow=self.workflow)

        return self.router
