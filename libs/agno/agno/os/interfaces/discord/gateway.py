"""Discord Gateway interface for AgentOS.

Runs a discord.py Gateway (WebSocket) listener in a background thread with its
own event loop. The listener does minimal work: it filters message events,
serializes them to JSON, and relays them via HTTP POST to this app's own
/discord/gateway/events endpoint, where the FastAPI route does all processing
and replies over Discord REST. Because the relay speaks plain HTTP, it can
later be moved to a separate process feeding multiple stateless replicas —
set run_listener=False here and run the relay externally with the same
DISCORD_GATEWAY_SECRET.

Unlike DiscordInteractions, this requires the privileged Message Content
Intent (enable it under Bot settings in the Discord developer portal) and the
`discord.py` package, but needs NO public URL, application id, or public key.
"""

from __future__ import annotations

import asyncio
import secrets as secrets_module
import threading
from contextlib import asynccontextmanager
from os import getenv
from typing import Any, AsyncIterator, Callable, List, Optional, Union

from fastapi import FastAPI
from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.discord.gateway_router import GATEWAY_SECRET_HEADER, attach_gateway_routes
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error, log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow

_RELAY_RETRY_DELAYS = [0.5, 1.0, 2.0, 4.0, 8.0]


class DiscordGateway(BaseInterface):
    type = "discord_gateway"

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
        prefix: str = "/discord",
        tags: Optional[List[str]] = None,
        bot_token: Optional[str] = None,
        app_url: Optional[str] = None,
        gateway_secret: Optional[str] = None,
        reply_in_thread: bool = True,
        respond_to_dms: bool = True,
        run_listener: bool = True,
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["Discord Gateway"]
        self.bot_token = bot_token or getenv("DISCORD_BOT_TOKEN")
        self.app_url = (app_url or getenv("DISCORD_GATEWAY_APP_URL") or "http://localhost:7777").rstrip("/")
        self.gateway_secret = gateway_secret or getenv("DISCORD_GATEWAY_SECRET") or secrets_module.token_urlsafe(32)
        self.reply_in_thread = reply_in_thread
        self.respond_to_dms = respond_to_dms
        self.run_listener = run_listener

        self._thread: Optional[threading.Thread] = None
        self._listener_loop: Optional[asyncio.AbstractEventLoop] = None
        self._client: Optional[Any] = None

        if not (self.agent or self.team or self.workflow):
            raise ValueError("DiscordGateway requires an agent, team, or workflow")
        if not self.bot_token:
            raise ValueError("DISCORD_BOT_TOKEN is not set. Set the env var or pass bot_token.")
        if self.run_listener:
            try:
                import discord  # noqa: F401
            except (ImportError, ModuleNotFoundError):
                raise ImportError(
                    "`discord.py` is required for DiscordGateway with run_listener=True. "
                    "Install it with: pip install discord.py (or pip install 'agno[discord]')"
                )

    def get_router(self) -> APIRouter:
        self.router = attach_gateway_routes(
            router=APIRouter(prefix=self.prefix, tags=self.tags),  # type: ignore[arg-type]
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            bot_token=self.bot_token,
            gateway_secret=self.gateway_secret,
            reply_in_thread=self.reply_in_thread,
            respond_to_dms=self.respond_to_dms,
        )
        return self.router

    def get_lifespan(self) -> Callable[[FastAPI], Any]:
        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            if self.run_listener:
                self._thread = threading.Thread(target=self._run_listener, name="discord-gateway", daemon=True)
                self._thread.start()
                log_info(f"Discord gateway listener started, relaying to {self._events_url()}")
            yield
            if self._client is not None and self._listener_loop is not None and self._listener_loop.is_running():
                try:
                    asyncio.run_coroutine_threadsafe(self._client.close(), self._listener_loop).result(timeout=10)
                except Exception as e:
                    log_warning(f"Discord gateway client close failed: {e}")
            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=10)
                if self._thread.is_alive():
                    log_warning("Discord gateway thread did not stop within 10s")

        return lifespan

    def _events_url(self) -> str:
        return f"{self.app_url}{self.prefix}/gateway/events"

    def _run_listener(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._listener_loop = loop
        try:
            self._client = self._build_client()
            loop.run_until_complete(self._client.start(self.bot_token))
        except Exception as e:
            log_error(f"Discord gateway listener stopped: {e}")
        finally:
            # client.start() returns as soon as the connection drops, but the
            # close() task scheduled from the lifespan thread (and aiohttp's
            # internal teardown) may still be running on this loop — drain
            # before closing or they get destroyed mid-flight
            try:
                pending = asyncio.all_tasks(loop)
                if pending:
                    loop.run_until_complete(
                        asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=10)
                    )
                loop.run_until_complete(loop.shutdown_asyncgens())
                # Give aiohttp's SSL transports a beat to run their close callbacks
                loop.run_until_complete(asyncio.sleep(0.25))
            except Exception:
                pass
            loop.close()

    def _build_client(self) -> Any:
        import discord
        import httpx

        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.dm_messages = True
        intents.message_content = True

        events_url = self._events_url()
        secret_headers = {GATEWAY_SECRET_HEADER: self.gateway_secret}
        respond_to_dms = self.respond_to_dms

        class _RelayClient(discord.Client):
            async def setup_hook(self) -> None:
                # One long-lived HTTP client bound to the listener loop
                self.relay_http = httpx.AsyncClient(timeout=10.0)

            async def close(self) -> None:
                try:
                    await self.relay_http.aclose()
                except Exception:
                    pass
                await super().close()

            async def on_ready(self) -> None:
                log_info(f"Discord gateway connected as {self.user}")

            async def on_message(self, message: Any) -> None:
                if self.user is None or message.author.id == self.user.id or message.author.bot:
                    return

                is_dm = message.guild is None
                is_thread = isinstance(message.channel, discord.Thread)
                mentions_bot = self.user in message.mentions
                bot_in_thread = False
                if is_thread:
                    bot_in_thread = message.channel.owner_id == self.user.id or message.channel.me is not None

                # Pre-filter as an optimization; the endpoint re-checks and is the authority
                if is_dm:
                    if not respond_to_dms:
                        return
                elif is_thread:
                    if not (mentions_bot or bot_in_thread):
                        return
                elif not mentions_bot:
                    return

                payload = {
                    "type": "message",
                    "message_id": str(message.id),
                    "channel_id": str(message.channel.id),
                    "guild_id": str(message.guild.id) if message.guild else None,
                    "channel_type": int(message.channel.type.value),
                    "is_dm": is_dm,
                    "is_thread": is_thread,
                    "thread_parent_id": str(message.channel.parent_id) if is_thread else None,
                    "author": {
                        "id": str(message.author.id),
                        "username": message.author.name,
                        "global_name": getattr(message.author, "global_name", None),
                        "bot": message.author.bot,
                    },
                    "bot_user_id": str(self.user.id),
                    "mentions_bot": mentions_bot,
                    "bot_in_thread": bot_in_thread,
                    "content": message.content,
                    "attachments": [
                        {"url": a.url, "content_type": a.content_type, "filename": a.filename}
                        for a in message.attachments
                    ],
                }
                await self._relay(payload)

            async def _relay(self, payload: dict) -> None:
                # uvicorn may not be bound yet right after startup — retry with backoff
                for attempt, delay in enumerate([0.0] + _RELAY_RETRY_DELAYS):
                    if delay:
                        await asyncio.sleep(delay)
                    try:
                        resp = await self.relay_http.post(events_url, json=payload, headers=secret_headers)
                        if resp.status_code == 401:
                            log_warning(
                                "Discord gateway relay got 401 — the endpoint expects a different "
                                "DISCORD_GATEWAY_SECRET than the listener is sending"
                            )
                        return
                    except httpx.TransportError as e:
                        if attempt == len(_RELAY_RETRY_DELAYS):
                            log_warning(
                                f"Discord gateway relay to {events_url} failed after retries, dropping event: {e}. "
                                "If AgentOS serves on a non-default port, set app_url or DISCORD_GATEWAY_APP_URL."
                            )

        return _RelayClient(intents=intents)
