from os import getenv
from typing import List, Optional, Union

import httpx
from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.discord.router import attach_routes
from agno.team import RemoteTeam, Team
from agno.utils.log import log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow

DISCORD_API = "https://discord.com/api/v10"


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
        public_key: Optional[str] = None,
        application_id: Optional[str] = None,
        bot_token: Optional[str] = None,
        command_name: str = "ask",
        command_description: str = "Ask the AI a question",
        auto_register_command: bool = True,
        reply_in_thread: bool = False,
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["Discord"]
        self.public_key = public_key or getenv("DISCORD_PUBLIC_KEY")
        self.application_id = application_id or getenv("DISCORD_APP_ID")
        self.bot_token = bot_token or getenv("DISCORD_BOT_TOKEN")
        self.command_name = command_name
        self.command_description = command_description
        self.auto_register_command = auto_register_command
        self.reply_in_thread = reply_in_thread

        if not (self.agent or self.team or self.workflow):
            raise ValueError("Discord requires an agent, team, or workflow")
        if not self.public_key:
            raise ValueError("DISCORD_PUBLIC_KEY is not set. Set the env var or pass public_key.")
        if not self.application_id:
            raise ValueError("DISCORD_APP_ID is not set. Set the env var or pass application_id.")
        needs_bot_token = self.auto_register_command or self.reply_in_thread
        if needs_bot_token and not self.bot_token:
            raise ValueError(
                "DISCORD_BOT_TOKEN is required when auto_register_command=True or reply_in_thread=True. "
                "Set the env var, pass bot_token, or disable both flags."
            )

    def _register_command(self) -> None:
        url = f"{DISCORD_API}/applications/{self.application_id}/commands"
        headers = {
            "Authorization": f"Bot {self.bot_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "name": self.command_name,
            "description": self.command_description,
            "options": [
                {
                    "name": "question",
                    "description": "Your question",
                    "type": 3,
                    "required": True,
                },
                {
                    "name": "file",
                    "description": "Attach an image, audio, video, or document",
                    "type": 11,
                    "required": False,
                },
            ],
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, headers=headers, json=payload)
            if 200 <= resp.status_code < 300:
                log_info(f"Registered Discord slash command /{self.command_name}")
            else:
                log_warning(f"Discord command registration returned {resp.status_code}: {resp.text}")
        except Exception as e:
            log_warning(f"Discord command registration failed: {e}")

    def get_router(self) -> APIRouter:
        if self.auto_register_command:
            self._register_command()

        self.router = attach_routes(
            router=APIRouter(prefix=self.prefix, tags=self.tags),  # type: ignore[arg-type]
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            public_key=self.public_key,
            application_id=self.application_id,
            bot_token=self.bot_token,
            reply_in_thread=self.reply_in_thread,
        )
        return self.router
