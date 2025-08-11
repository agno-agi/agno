"""Main class for the AG-UI app, used to expose an Agno Agent or Team in an AG-UI compatible format."""

from typing import Optional

from fastapi.routing import APIRouter

from agno.agent import Agent
from agno.os.interfaces.agui.router import attach_routes
from agno.os.interfaces.base import BaseInterface
from agno.team import Team


class AGUI(BaseInterface):
    type = "agui"

    router: APIRouter

    def __init__(self, agent: Optional[Agent] = None, team: Optional[Team] = None):
        self.agent = agent
        self.team = team

        if not self.agent and not self.team:
            raise ValueError("AGUI requires an agent and a team")

    def get_router(self, use_async: bool = True, **kwargs) -> APIRouter:
        # Cannot be overridden
        self.router = APIRouter(tags=["AGUI"])

        self.router = attach_routes(router=self.router, agent=self.agent, team=self.team)

        return self.router
