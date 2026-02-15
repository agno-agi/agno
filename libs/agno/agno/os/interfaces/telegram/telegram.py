from typing import List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.telegram.router import attach_routes
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


class Telegram(BaseInterface):
    type = "telegram"

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
        prefix: str = "/telegram",
        tags: Optional[List[str]] = None,
        reply_to_mentions_only: bool = True,
        reply_to_bot_messages: bool = True,
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["Telegram"]
        self.reply_to_mentions_only = reply_to_mentions_only
        self.reply_to_bot_messages = reply_to_bot_messages

        if not (self.agent or self.team or self.workflow):
            raise ValueError("Telegram requires an agent, team, or workflow")

    def get_router(self) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore

        self.router = attach_routes(
            router=self.router,
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            reply_to_mentions_only=self.reply_to_mentions_only,
            reply_to_bot_messages=self.reply_to_bot_messages,
        )

        return self.router
