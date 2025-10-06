"""Main class for the A2A app, used to expose an Agno Agent or Team in an A2A compatible format."""

from typing import Optional

from fastapi.routing import APIRouter
from typing_extensions import List

from agno.agent import Agent
from agno.os.interfaces.a2a.router import attach_routes
from agno.os.interfaces.base import BaseInterface
from agno.team import Team


class A2A(BaseInterface):
    type = "a2a"

    router: APIRouter

    def __init__(self, agents: Optional[List[Agent]] = None, teams: Optional[List[Team]] = None):
        self.agents = agents
        self.teams = teams

        if not (self.agents or self.teams):
            raise ValueError("Agents or Teams are required to setup the A2A interface.")

    def get_router(self, **kwargs) -> APIRouter:
        # Cannot be overridden
        self.router = APIRouter(prefix="/a2a", tags=["A2A"])

        self.router = attach_routes(router=self.router, agents=self.agents, teams=self.teams)

        return self.router
