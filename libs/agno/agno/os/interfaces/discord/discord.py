from typing import List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.discord.router import attach_routes
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


class Discord(BaseInterface):
    type = "discord"

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
        prefix: str = "/discord",
        tags: Optional[List[str]] = None,
        # Discord-specific options
        show_reasoning: bool = True,
        max_message_chars: int = 1900,
        allowed_guild_ids: Optional[List[str]] = None,
        allowed_channel_ids: Optional[List[str]] = None,
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["Discord"]
        self.show_reasoning = show_reasoning
        self.max_message_chars = max_message_chars
        self.allowed_guild_ids = allowed_guild_ids
        self.allowed_channel_ids = allowed_channel_ids

        if not (self.agent or self.team or self.workflow):
            raise ValueError("Discord requires an agent, team or workflow")

    def get_router(self) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore

        self.router = attach_routes(
            router=self.router,
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            show_reasoning=self.show_reasoning,
            max_message_chars=self.max_message_chars,
            allowed_guild_ids=self.allowed_guild_ids,
            allowed_channel_ids=self.allowed_channel_ids,
        )

        return self.router
