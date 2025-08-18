import logging
from typing import Optional

from fastapi.routing import APIRouter

from agno.agent.agent import Agent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.slack.router import attach_routes
from agno.team.team import Team

logger = logging.getLogger(__name__)


class Slack(BaseInterface):
    type = "slack"

    router: APIRouter

    def __init__(self, agent: Optional[Agent] = None, team: Optional[Team] = None):
        self.agent = agent
        self.team = team

        if not self.agent and not self.team:
            raise ValueError("Slack requires an agent and a team")

    def get_router(self, use_async: bool = True, **kwargs) -> APIRouter:
        # Cannot be overridden
        self.router_prefix = "/slack"
        self.router = APIRouter(prefix=self.router_prefix, tags=["Slack"])

        self.router = attach_routes(router=self.router, agent=self.agent, team=self.team)

        return self.router
