"""Main class for the RemoteAccess interface, used to expose Agno Agents and Teams for remote execution.

The RemoteAccess interface is the opt-in surface consumed by RemoteAgent and RemoteTeam.
Only entities explicitly passed to this interface are remotely callable: an AgentOS that
does not mount the interface (or does not pass an entity to it) does not expose that
entity for remote execution, regardless of its default API routes.

Workflows are not remotely executable: run them on their own AgentOS via the standard
workflow API instead.
"""

from typing import Any, List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent
from agno.agent.protocol import AgentProtocol
from agno.agent.remote import RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.remote_access.router import attach_routes
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error


class RemoteAccess(BaseInterface):
    type = "remote_access"

    router: APIRouter

    def __init__(
        self,
        agents: Optional[List[Union[Agent, RemoteAgent, AgentProtocol]]] = None,
        teams: Optional[List[Union[Team, RemoteTeam]]] = None,
        workflows: Optional[List[Any]] = None,
        prefix: str = "/remote",
        tags: Optional[List[str]] = None,
    ):
        """Initialize the RemoteAccess interface.

        Args:
            agents: Agents to expose for remote execution.
            teams: Teams to expose for remote execution.
            workflows: Not supported. Remote workflows are not a thing; passing
                workflows logs an error and they are ignored.
            prefix: Path prefix the interface is mounted at (default: "/remote").
                RemoteAgent/RemoteTeam must use a matching api_prefix.
            tags: OpenAPI tags for the interface routes.
        """
        if workflows:
            log_error(
                "Remote workflows are not a thing: the RemoteAccess interface does not expose workflows. "
                "The workflows passed to RemoteAccess will be ignored. Run workflows on their own AgentOS "
                "via the standard workflow API instead."
            )

        self.agents = agents
        self.teams = teams
        self.prefix = prefix
        self.tags = tags or ["RemoteAccess"]

        if not (self.agents or self.teams):
            raise ValueError("Agents or Teams are required to setup the RemoteAccess interface.")

    def get_router(self, **kwargs) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore

        self.router = attach_routes(router=self.router, agents=self.agents, teams=self.teams)

        return self.router

    def get_scope_mappings(self) -> dict:
        from agno.os.interfaces.remote_access.scopes import get_remote_access_scope_mappings

        return get_remote_access_scope_mappings(
            self.prefix,
            include_agents=bool(self.agents),
            include_teams=bool(self.teams),
        )
