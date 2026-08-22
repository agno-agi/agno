"""Main class for the Agent Protocol interface, used to expose Agno Agents, Teams, or Workflows
in an Agent Protocol-compatible format (LangChain/LangGraph standard)."""

from typing import Optional, Union

from fastapi.routing import APIRouter
from typing_extensions import List

from agno.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.os.interfaces.agent_protocol.router import attach_routes
from agno.os.interfaces.base import BaseInterface
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


class AgentProtocol(BaseInterface):
    type = "agent_protocol"

    router: APIRouter

    def __init__(
        self,
        agents: Optional[List[Union[Agent, RemoteAgent]]] = None,
        teams: Optional[List[Union[Team, RemoteTeam]]] = None,
        workflows: Optional[List[Union[Workflow, RemoteWorkflow]]] = None,
        prefix: str = "/ap",
        tags: Optional[List[str]] = None,
    ):
        self.agents = agents
        self.teams = teams
        self.workflows = workflows
        self.prefix = prefix
        self.tags = tags or ["Agent Protocol"]

        if not (self.agents or self.teams or self.workflows):
            raise ValueError("Agents, Teams, or Workflows are required to setup the Agent Protocol interface.")

    def get_router(self, **kwargs) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore

        self.router = attach_routes(router=self.router, agents=self.agents, teams=self.teams, workflows=self.workflows)

        return self.router
