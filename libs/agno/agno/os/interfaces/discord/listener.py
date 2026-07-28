"""The Discord Gateway listener: a minimal discord.py client that relays messages.

This module is the ONLY place in the package that imports ``discord`` (and it
is itself only imported lazily by ``gateway.DiscordGateway``), so users of the
Interactions transport never need discord.py installed.

The listener deliberately does no agent work. It:
1. holds the Gateway WebSocket (message_content intent required),
2. pre-filters events with the same mention-gating rules the endpoint
   enforces (an optimization — the endpoint is the authority),
3. serializes each accepted message to a compact JSON payload, and
4. POSTs it to the app's ``/discord/gateway/events`` endpoint with the shared
   secret header.

Because the relay speaks plain HTTP, an instance of this listener can also run
in a separate process, pointed at a remote AgentOS via ``events_url``.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, List, Optional

import discord
import httpx

from agno.os.interfaces.discord.gateway_router import GATEWAY_SECRET_HEADER
from agno.utils.log import log_info, log_warning

# Backoff schedule for relay POSTs — covers the window where uvicorn hasn't
# bound the port yet right after startup, plus transient hiccups
RELAY_RETRY_DELAYS = [0.5, 1.0, 2.0, 4.0, 8.0]


def build_listener_intents() -> "discord.Intents":
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.dm_messages = True
    intents.message_content = True  # privileged — must be enabled in the Dev Portal
    return intents


class DiscordGatewayListener(discord.Client):
    def __init__(
        self,
        *,
        events_url: str,
        gateway_secret: str,
        respond_to_dms: bool = True,
        ready_event: Optional[threading.Event] = None,
    ):
        super().__init__(intents=build_listener_intents())
        self.events_url = events_url
        self.secret_headers = {GATEWAY_SECRET_HEADER: gateway_secret}
        self.respond_to_dms = respond_to_dms
        self.ready_event = ready_event
        self.relay_http: httpx.AsyncClient

    async def setup_hook(self) -> None:
        # One long-lived HTTP client bound to the listener's event loop. The
        # process-global client (agno.utils.http) cannot be used here: its
        # connection pool belongs to the main app's event loop, and this
        # listener runs on its own loop in a background thread.
        self.relay_http = httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        try:
            await self.relay_http.aclose()
        except Exception:
            pass
        await super().close()

    async def on_ready(self) -> None:
        log_info(f"Discord gateway connected as {self.user}")
        if self.ready_event is not None:
            self.ready_event.set()

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
            if not self.respond_to_dms:
                return
        elif is_thread:
            if not (mentions_bot or bot_in_thread):
                return
        elif not mentions_bot:
            return

        await self._relay(self._serialize(message, is_dm, is_thread, mentions_bot, bot_in_thread))

    def _serialize(
        self, message: Any, is_dm: bool, is_thread: bool, mentions_bot: bool, bot_in_thread: bool
    ) -> Dict[str, Any]:
        attachments: List[Dict[str, Any]] = [
            {"url": a.url, "content_type": a.content_type, "filename": a.filename} for a in message.attachments
        ]
        return {
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
            "bot_user_id": str(self.user.id) if self.user else "",
            "mentions_bot": mentions_bot,
            "bot_in_thread": bot_in_thread,
            "content": message.content,
            "attachments": attachments,
        }

    async def _relay(self, payload: Dict[str, Any]) -> None:
        for attempt, delay in enumerate([0.0] + RELAY_RETRY_DELAYS):
            if delay:
                await asyncio.sleep(delay)
            try:
                resp = await self.relay_http.post(self.events_url, json=payload, headers=self.secret_headers)
                if resp.status_code == 401:
                    log_warning(
                        "Discord gateway relay got 401 — the endpoint expects a different "
                        "DISCORD_GATEWAY_SECRET than the listener is sending"
                    )
                return
            except httpx.TransportError as e:
                if attempt == len(RELAY_RETRY_DELAYS):
                    log_warning(
                        f"Discord gateway relay to {self.events_url} failed after retries, dropping event: {e}. "
                        "If AgentOS serves on a non-default port, set app_url or DISCORD_GATEWAY_APP_URL."
                    )
