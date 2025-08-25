from typing import Optional

from fastapi.routing import APIRouter

from agno.agent import Agent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.whatsapp.router import attach_routes
from agno.team import Team


class Whatsapp(BaseInterface):
    type = "whatsapp"

    router: APIRouter

    def __init__(self, agent: Optional[Agent] = None, team: Optional[Team] = None):
        self.agent = agent
        self.team = team

        if not self.agent and not self.team:
            raise ValueError("Whatsapp requires an agent and a team")

    def get_router(self, use_async: bool = True, **kwargs) -> APIRouter:
        # Cannot be overridden
        self.router_prefix = "/whatsapp"
        self.router = APIRouter(prefix=self.router_prefix, tags=["Whatsapp"])

        self.router = attach_routes(router=self.router, agent=self.agent, team=self.team)

        return self.router
