from os import getenv
from typing import Any, Dict, List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.discord.helpers import FALLBACK_ERROR_MESSAGE
from agno.os.interfaces.discord.router import attach_routes
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error, log_warning
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
        public_key: Optional[str] = None,
        application_id: Optional[str] = None,
        bot_token: Optional[str] = None,
        streaming: bool = True,
        # Sync path only — streaming always shows reasoning via task card events
        show_reasoning: bool = False,
        error_message: str = FALLBACK_ERROR_MESSAGE,
        command_name: str = "ask",
        command_description: str = "Ask the AI a question",
        auto_register_command: bool = True,
        reply_in_thread: bool = True,
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["Discord"]
        self.public_key = public_key
        self.application_id = application_id or getenv("DISCORD_APPLICATION_ID") or ""
        self.bot_token = bot_token or getenv("DISCORD_BOT_TOKEN") or ""
        self.streaming = streaming
        self.show_reasoning = show_reasoning
        self.error_message = error_message
        self.command_name = command_name
        self.command_description = command_description
        self.auto_register_command = auto_register_command
        self.reply_in_thread = reply_in_thread

        if not (self.agent or self.team or self.workflow):
            raise ValueError("Discord requires an agent, team, or workflow")

    def _register_commands(self) -> None:
        if not self.application_id or not self.bot_token:
            log_warning("Skipping command registration: application_id or bot_token not set")
            return

        try:
            import httpx
        except ImportError:
            log_warning("httpx not installed, skipping command registration")
            return

        commands: List[Dict[str, Any]] = [
            {
                "name": self.command_name,
                "description": self.command_description,
                "type": 1,
                "options": [
                    {
                        "name": "message",
                        "description": "Your message",
                        "type": 3,
                        "required": True,
                    },
                    {
                        "name": "attachment",
                        "description": "Upload an image or file",
                        "type": 11,
                        "required": False,
                    },
                ],
            },
            {
                "name": "new",
                "description": "Start a fresh conversation (resets memory for this channel)",
                "type": 1,
            },
        ]

        url = f"https://discord.com/api/v10/applications/{self.application_id}/commands"
        headers = {"Authorization": f"Bot {self.bot_token}", "Content-Type": "application/json"}

        try:
            resp = httpx.put(url, json=commands, headers=headers, timeout=15)
            if resp.is_success:
                registered = resp.json()
                names = [c.get("name", "?") for c in registered]
                log_warning(f"Registered Discord commands: {names}")
            else:
                log_error(f"Failed to register commands ({resp.status_code}): {resp.text}")
        except Exception as e:
            log_error(f"Command registration error: {e}")

    def get_router(self) -> APIRouter:
        if self.auto_register_command:
            self._register_commands()

        self.router = attach_routes(
            router=APIRouter(prefix=self.prefix, tags=self.tags),  # type: ignore[arg-type]
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            public_key=self.public_key,
            application_id=self.application_id,
            bot_token=self.bot_token,
            reply_in_thread=self.reply_in_thread,
            streaming=self.streaming,
            show_reasoning=self.show_reasoning,
            error_message=self.error_message,
        )

        return self.router
