from ssl import SSLContext
from typing import Dict, List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.slack.router import attach_routes
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


class Slack(BaseInterface):
    type = "slack"

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
        prefix: str = "/slack",
        tags: Optional[List[str]] = None,
        reply_to_mentions_only: bool = True,
        token: Optional[str] = None,
        signing_secret: Optional[str] = None,
        streaming: bool = True,
        loading_messages: Optional[List[str]] = None,
        task_display_mode: str = "plan",
        loading_text: str = "Thinking...",
        suggested_prompts: Optional[List[Dict[str, str]]] = None,
        ssl: Optional[SSLContext] = None,
        buffer_size: int = 100,
        max_file_size: int = 1_073_741_824,  # 1GB
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["Slack"]
        self.reply_to_mentions_only = reply_to_mentions_only
        self.token = token
        self.signing_secret = signing_secret
        self.streaming = streaming
        self.loading_messages = loading_messages
        self.task_display_mode = task_display_mode
        self.loading_text = loading_text
        self.suggested_prompts = suggested_prompts
        self.ssl = ssl
        self.buffer_size = buffer_size
        self.max_file_size = max_file_size

        if not (self.agent or self.team or self.workflow):
            raise ValueError("Slack requires an agent, team, or workflow")

    def get_router(self) -> APIRouter:
        self.router = attach_routes(
            router=APIRouter(prefix=self.prefix, tags=self.tags),  # type: ignore
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            reply_to_mentions_only=self.reply_to_mentions_only,
            token=self.token,
            signing_secret=self.signing_secret,
            streaming=self.streaming,
            loading_messages=self.loading_messages,
            task_display_mode=self.task_display_mode,
            loading_text=self.loading_text,
            suggested_prompts=self.suggested_prompts,
            ssl=self.ssl,
            buffer_size=self.buffer_size,
            max_file_size=self.max_file_size,
        )

        return self.router
