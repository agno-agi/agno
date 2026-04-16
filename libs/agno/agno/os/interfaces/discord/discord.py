from os import getenv
from typing import Any, Dict, List, Optional, Union

import httpx
from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.discord.helpers import DISCORD_API_BASE, FALLBACK_ERROR_MESSAGE
from agno.os.interfaces.discord.router import attach_routes
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error, log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow

# Discord slash-command option types: 3 = STRING, 11 = ATTACHMENT
# https://discord.com/developers/docs/interactions/application-commands#application-command-object-application-command-option-type
_DEFAULT_ASK_COMMAND: Dict[str, Any] = {
    "name": "ask",
    "description": "Ask the AI a question",
    "type": 1,
    "options": [
        {"name": "message", "description": "Your message", "type": 3, "required": True},
        {"name": "attachment", "description": "Upload an image or file", "type": 11, "required": False},
    ],
}

_NEW_COMMAND: Dict[str, Any] = {
    "name": "new",
    "description": "Start a fresh conversation (resets memory for this channel)",
    "type": 1,
}


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
        commands: Optional[List[Dict[str, Any]]] = None,
        command_name: str = "ask",
        command_description: str = "Ask the AI a question",
        register_commands: bool = True,
        reply_in_thread: bool = False,
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["Discord"]
        self.public_key = public_key or getenv("DISCORD_PUBLIC_KEY") or ""
        self.application_id = application_id or getenv("DISCORD_APP_ID") or ""
        self.bot_token = bot_token or getenv("DISCORD_BOT_TOKEN") or ""
        self.streaming = streaming
        self.show_reasoning = show_reasoning
        self.error_message = error_message
        self.register_commands = register_commands
        self.reply_in_thread = reply_in_thread

        # commands= takes precedence. command_name / command_description are
        # single-command shortcuts used when commands is None — convenient for
        # bots that only want to rename /ask. Mixing the two is ambiguous.
        _has_single_overrides = command_name != "ask" or command_description != "Ask the AI a question"
        if commands is not None and _has_single_overrides:
            raise ValueError(
                "Pass either commands= OR command_name=/command_description=, not both. "
                "The commands= list can already set any name and description per entry."
            )
        if commands is not None:
            self.commands = commands
        else:
            self.commands = [
                {
                    "name": command_name,
                    "description": command_description,
                    "type": 1,
                    "options": _DEFAULT_ASK_COMMAND["options"],
                }
            ]

        if not (self.agent or self.team or self.workflow):
            raise ValueError("Discord requires an agent, team, or workflow")
        if not self.public_key:
            raise ValueError("DISCORD_PUBLIC_KEY is not set. Set the env var or pass public_key.")
        if not self.application_id:
            raise ValueError("DISCORD_APP_ID is not set. Set the env var or pass application_id.")
        if (self.register_commands or self.reply_in_thread) and not self.bot_token:
            raise ValueError(
                "DISCORD_BOT_TOKEN is required when register_commands=True or reply_in_thread=True. "
                "Set the env var, pass bot_token, or disable both flags."
            )

    def _register_commands(self) -> None:
        # Sync at startup — get_router() runs inside AgentOS's lifecycle where
        # an event loop may already be running, so asyncio.run() can't be used.
        # httpx sync is simple and this is a one-off call, unlike the runtime
        # thread-creation path which uses DiscordBotClient over aiohttp.
        if not self.application_id or not self.bot_token:
            log_warning("Skipping command registration: application_id or bot_token not set")
            return
        # /new is reserved — drop any user entry named "new" so the interface's
        # session-reset definition always wins
        commands = [c for c in self.commands if c.get("name") != "new"] + [_NEW_COMMAND]
        url = f"{DISCORD_API_BASE}/applications/{self.application_id}/commands"
        headers = {"Authorization": f"Bot {self.bot_token}", "Content-Type": "application/json"}
        try:
            resp = httpx.put(url, json=commands, headers=headers, timeout=15)
            if resp.is_success:
                log_info(f"Registered Discord commands: {[c.get('name', '?') for c in resp.json()]}")
            else:
                log_error(f"Failed to register commands ({resp.status_code}): {resp.text}")
        except Exception as e:
            log_error(f"Command registration error: {e}")

    def get_router(self) -> APIRouter:
        if self.register_commands:
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
