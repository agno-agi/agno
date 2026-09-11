"""Main class for the AG-UI app, used to expose an Agno Agent or Team in an AG-UI compatible format."""

from typing import List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.os.interfaces.agui.a2ui_stream import A2UIConfig, is_remote_entity, validate_a2ui_config
from agno.os.interfaces.agui.router import attach_routes
from agno.os.interfaces.base import BaseInterface
from agno.team import Team
from agno.team.remote import RemoteTeam


class AGUI(BaseInterface):
    type = "agui"

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        prefix: str = "",
        tags: Optional[List[str]] = None,
        a2ui: Optional[A2UIConfig] = None,
    ):
        """
        Initialize the AGUI interface.

        Args:
            agent: The agent to expose via AG-UI
            team: The team to expose via AG-UI
            prefix: Custom prefix for the router (e.g., "/agui/v1", "/chat/public")
            tags: Custom tags for the router (e.g., ["AGUI", "Chat"], defaults to ["AGUI"])
            a2ui: A2UI generation settings, as `A2UIConfig`. Set `inject_a2ui_tool`
                to let this agent generate its own interface even when the client
                does not ask for it; the rest are behavior knobs (catalog, prompt
                guidelines, retry cap). A client forwarding `injectA2UITool: false`
                still turns generation off for that run.

        Raises:
            ValueError: if `a2ui` holds a setting this interface does not have.
                Every one of them turns something on, so ignoring a misspelled
                key would leave generation off with the configuration
                apparently in place.
            ValueError: if `a2ui` is given for a remote agent or team. Per-run
                tools are not forwarded to a remote deployment, so no setting
                here can reach one; wire `get_a2ui_tools()` into the agent in
                that deployment instead.
        """
        self.agent = agent
        self.team = team
        self.prefix = prefix
        self.tags = tags or ["AGUI"]
        self.a2ui = validate_a2ui_config(a2ui)

        if not (self.agent or self.team):
            raise ValueError("AGUI requires an agent or a team")

        if self.a2ui is not None and is_remote_entity(self.agent or self.team):
            raise ValueError(
                "A2UI settings cannot apply to a remote agent or team: per-run tools are not forwarded to a "
                "remote deployment. Wire get_a2ui_tools() into the agent there instead."
            )

    def get_router(self) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore

        self.router = attach_routes(router=self.router, agent=self.agent, team=self.team, a2ui=self.a2ui)

        return self.router

    def get_scope_mappings(self) -> dict:
        # Agent-wins precedence must match router dispatch (entity = agent or team)
        family = "agents" if self.agent is not None else "teams"
        return {f"POST {self.prefix}/agui": [f"{family}:run"]}
