from typing import Optional

from fastapi.routing import APIRouter

from agno.agent import Agent
from agno.app.agno_api.base import BaseInterface
from agno.app.agno_api.interfaces.whatsapp.async_router import attach_async_routes
from agno.app.agno_api.interfaces.whatsapp.sync_router import attach_sync_routes
from agno.team import Team


class Whatsapp(BaseInterface):
    type = "whatsapp"

    router: APIRouter

    def __init__(self, agent: Optional[Agent] = None, team: Optional[Team] = None):
        self.agent = agent
        self.team = team

        if not self.agent and not self.team:
            raise ValueError("Whatsapp requires an agent and a team")

    def get_router(self, use_async: bool = True) -> APIRouter:
        # Cannot be overridden
        prefix: str = "/whatsapp"
        version: str = "/v1"
        self.router = APIRouter(prefix=prefix + version, tags=["Whatsapp"])

        if use_async:
            self.router = attach_async_routes(router=self.router, agent=self.agent, team=self.team)
        else:
            self.router = attach_sync_routes(router=self.router, agent=self.agent, team=self.team)

        return self.router
