from typing import Dict, List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.telegram.router import (
    DEFAULT_ERROR_MESSAGE,
    DEFAULT_HELP_MESSAGE,
    DEFAULT_NEW_MESSAGE,
    DEFAULT_START_MESSAGE,
    attach_routes,
)
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow

DEFAULT_BOT_COMMANDS: List[Dict[str, str]] = [
    {"command": "start", "description": "Start the bot"},
    {"command": "help", "description": "Show help"},
    {"command": "new", "description": "Start a new conversation"},
]


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
        token: Optional[str] = None,
        reply_to_mentions_only: bool = True,
        reply_to_bot_messages: bool = True,
        start_message: str = DEFAULT_START_MESSAGE,
        help_message: str = DEFAULT_HELP_MESSAGE,
        error_message: str = DEFAULT_ERROR_MESSAGE,
        streaming: bool = True,
        show_reasoning: bool = False,
        commands: Optional[List[Dict[str, str]]] = None,
        register_commands: bool = True,
        new_message: str = DEFAULT_NEW_MESSAGE,
        quoted_responses: bool = False,
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["Telegram"]
        self.token = token
        self.reply_to_mentions_only = reply_to_mentions_only
        self.reply_to_bot_messages = reply_to_bot_messages
        self.start_message = start_message
        self.help_message = help_message
        self.error_message = error_message
        self.streaming = streaming
        self.show_reasoning = show_reasoning
        self.commands = commands if commands is not None else DEFAULT_BOT_COMMANDS
        self.register_commands = register_commands
        self.new_message = new_message
        self.quoted_responses = quoted_responses

        if not (self.agent or self.team or self.workflow):
            raise ValueError("Telegram requires an agent, team, or workflow")

    def get_router(self) -> APIRouter:
        return attach_routes(
            router=APIRouter(prefix=self.prefix, tags=self.tags),  # type: ignore
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            token=self.token,
            reply_to_mentions_only=self.reply_to_mentions_only,
            reply_to_bot_messages=self.reply_to_bot_messages,
            start_message=self.start_message,
            help_message=self.help_message,
            error_message=self.error_message,
            streaming=self.streaming,
            show_reasoning=self.show_reasoning,
            commands=self.commands,
            register_commands=self.register_commands,
            new_message=self.new_message,
            quoted_responses=self.quoted_responses,
        )
