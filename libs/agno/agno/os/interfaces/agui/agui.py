"""Main class for the AG-UI app, used to expose an Agno Agent, Team, or Workflow in an AG-UI compatible format."""

from typing import List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.os.interfaces.agui.router import attach_routes
from agno.os.interfaces.base import BaseInterface
from agno.team import Team
from agno.team.remote import RemoteTeam
from agno.workflow import RemoteWorkflow, Workflow


class AGUI(BaseInterface):
    type = "agui"

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
        prefix: str = "",
        tags: Optional[List[str]] = None,
    ):
        """
        Initialize the AGUI interface.

        Args:
            agent: The agent to expose via AG-UI
            team: The team to expose via AG-UI
            workflow: The workflow to expose via AG-UI
            prefix: Custom prefix for the router (e.g., "/agui/v1", "/chat/public")
            tags: Custom tags for the router (e.g., ["AGUI", "Chat"], defaults to ["AGUI"])
        """
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["AGUI"]

        if not (self.agent or self.team or self.workflow):
            raise ValueError("AGUI requires an agent, team, or workflow")

    def get_router(self) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore

        self.router = attach_routes(router=self.router, agent=self.agent, team=self.team, workflow=self.workflow)

        return self.router

    def get_scope_mappings(self) -> dict:
        if self.agent is not None:
            family = "agents"
        elif self.team is not None:
            family = "teams"
        else:
            family = "workflows"
        return {f"POST {self.prefix}/agui": [f"{family}:run"]}
