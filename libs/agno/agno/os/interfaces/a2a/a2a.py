"""Main class for the A2A app, used to expose an Agno Agent, Team, or Workflow in an A2A compatible format."""

from typing import Any, Dict, Optional, Union

from fastapi.routing import APIRouter
from typing_extensions import List

try:
    from a2a.types import AgentProvider, SecurityScheme
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a-sdk`") from e


from agno.agent import Agent
from agno.agent.protocol import AgentProtocol
from agno.agent.remote import RemoteAgent
from agno.os.interfaces.a2a.router import attach_routes
from agno.os.interfaces.base import BaseInterface
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


class A2A(BaseInterface):
    type = "a2a"

    router: APIRouter

    def __init__(
        self,
        agents: Optional[List[Union[Agent, RemoteAgent, AgentProtocol]]] = None,
        teams: Optional[List[Union[Team, RemoteTeam]]] = None,
        workflows: Optional[List[Union[Workflow, RemoteWorkflow]]] = None,
        prefix: str = "/a2a",
        tags: Optional[List[str]] = None,
        base_url: Optional[str] = None,
        security_schemes: Optional[Dict[str, SecurityScheme]] = None,
        enable_v0_3_compat: bool = True,
        provider: Optional[AgentProvider] = None,
        documentation_url: Optional[str] = None,
        icon_url: Optional[str] = None,
    ):
        self.agents = agents
        self.teams = teams
        self.workflows = workflows
        self.prefix = prefix
        self.tags = tags or ["A2A"]
        self.base_url = base_url
        self.security_schemes = security_schemes
        self.enable_v0_3_compat = enable_v0_3_compat
        self.provider = provider
        self.documentation_url = documentation_url
        self.icon_url = icon_url
        self._request_handlers: Dict[str, Any] = {}

        if not (self.agents or self.teams or self.workflows):
            raise ValueError("Agents, Teams, or Workflows are required to setup the A2A interface.")

    def get_router(self, **kwargs) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore

        self.router = attach_routes(
            router=self.router,
            agents=self.agents,
            teams=self.teams,
            workflows=self.workflows,
            base_url=self.base_url,
            security_schemes=self.security_schemes,
            enable_v0_3_compat=self.enable_v0_3_compat,
            request_handlers=self._request_handlers,
            provider=self.provider,
            documentation_url=self.documentation_url,
            icon_url=self.icon_url,
        )

        return self.router

    async def aclose(self) -> None:
        for request_handler in self._request_handlers.values():
            await request_handler.aclose()

    def get_scope_mappings(self) -> dict:
        # A2A routes are authorized in the route, per entity and per A2A method
        return {}
