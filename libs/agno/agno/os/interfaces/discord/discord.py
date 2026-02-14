import asyncio
from contextlib import asynccontextmanager, suppress
from os import getenv
from typing import Any, List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.discord.router import attach_routes
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


class Discord(BaseInterface):
    """Discord interface supporting two concurrent transports:

    1. **HTTP** (``router.py``) — Slash commands via webhook.  Always available.
       Requires ``DISCORD_PUBLIC_KEY`` for Ed25519 signature verification.

    2. **Gateway** (``gateway.py``) — @mentions and DMs via persistent WebSocket.
       Auto-activates when ``discord.py`` (the library) is installed and a bot token
       is available.  Falls back to HTTP-only otherwise.

    Both transports share a single processing core (``processing.py``) via the
    ``Replier`` protocol, so agent/team/workflow logic is written once.
    """

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
        # Discord's hard limit is 2000 chars; 1900 leaves room for the [1/N] prefix
        # added by split_message() when a response spans multiple messages.
        max_message_chars: int = 1900,
        allowed_guild_ids: Optional[List[str]] = None,
        allowed_channel_ids: Optional[List[str]] = None,
        # Gateway options
        discord_bot_token: Optional[str] = None,
        reply_in_thread: bool = True,
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
        self.reply_in_thread = reply_in_thread

        if not (self.agent or self.team or self.workflow):
            raise ValueError("Discord requires an agent, team or workflow")

        # Gateway auto-activates when discord.py is installed and a bot token is available.
        # No token or no package → HTTP interactions still work, gateway is simply not started.
        self._gateway_client: Any = None
        self._gateway_token: Optional[str] = None

        try:
            import discord as _dc  # noqa: F401
        except ImportError:
            return

        token = discord_bot_token or getenv("DISCORD_BOT_TOKEN")
        if not token:
            return

        from agno.os.interfaces.discord.gateway import create_gateway_client

        self._gateway_client = create_gateway_client(
            agent=agent,
            team=team,
            workflow=workflow,
            reply_in_thread=reply_in_thread,
            show_reasoning=show_reasoning,
            max_message_chars=max_message_chars,
            allowed_guild_ids=allowed_guild_ids,
            allowed_channel_ids=allowed_channel_ids,
        )
        self._gateway_token = token

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

    def get_lifespan(self) -> Optional[Any]:
        """Return a FastAPI lifespan that starts/stops the Discord Gateway WebSocket.

        Returns ``None`` when gateway is disabled — the HTTP interactions endpoint
        still works independently.
        """
        if self._gateway_client is None:
            return None

        client = self._gateway_client
        token = self._gateway_token

        @asynccontextmanager
        async def gateway_lifespan(app: Any):  # noqa: ARG001
            # Start the WebSocket client as a background task.  On shutdown, close the
            # connection first (sends a clean disconnect), then cancel the task to avoid
            # "task was destroyed but it is pending" warnings.
            task = asyncio.create_task(client.start(token), name="discord-gateway")
            try:
                yield
            finally:
                await client.close()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

        return gateway_lifespan
