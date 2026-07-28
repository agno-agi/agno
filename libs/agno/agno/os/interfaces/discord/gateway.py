"""Discord Gateway interface for AgentOS.

``get_router()`` mounts the relay endpoint; ``get_lifespan()`` runs the
gateway listener (``listener.py``) in a background thread that relays Discord
messages to that endpoint over HTTP. Requires the privileged Message Content
Intent and ``discord.py``, but no public URL. Set ``run_listener=False`` to
mount only the endpoint and run the listener as a separate process (same
``DISCORD_GATEWAY_SECRET`` on both sides).
"""

from __future__ import annotations

import asyncio
import secrets as secrets_module
import threading
import time
from contextlib import asynccontextmanager
from os import getenv
from typing import Any, AsyncIterator, Callable, List, Optional, Union

from fastapi import FastAPI
from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.discord.gateway_router import attach_gateway_routes
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error, log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow

# How long startup waits for the listener to connect before warning
LISTENER_READY_TIMEOUT = 15.0
# How long shutdown waits for the client to close / the thread to join
LISTENER_STOP_TIMEOUT = 10.0


class DiscordGateway(BaseInterface):
    type = "discord_gateway"

    # Requests are verified with the shared gateway secret, not AgentOS bearer auth
    authenticates_own_requests = True

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
        self._ready = threading.Event()

        if not (self.agent or self.team or self.workflow):
            raise ValueError("DiscordGateway requires an agent, team, or workflow")
        if not self.bot_token:
            raise ValueError("DISCORD_BOT_TOKEN is not set. Set the env var or pass bot_token.")
        if self.run_listener:
            # Fail fast at construction if the listener dependency is missing.
            # discord.py stays a lazy import so endpoint-only mode
            # (run_listener=False) and Interactions users never need it.
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
        """App lifespan hook (collected by AgentOS): start the listener thread on
        startup, close the discord client and join the thread on shutdown."""

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            if self.run_listener:
                await self._start_listener()
            yield
            if self.run_listener:
                await self._stop_listener()

        return lifespan

    def is_ready(self) -> bool:
        """True when the listener has an active gateway connection."""
        return self._ready.is_set() and self._thread is not None and self._thread.is_alive()

    async def _start_listener(self) -> None:
        """Spawn the listener thread and wait (bounded) for the gateway connection."""
        self._thread = threading.Thread(target=self._run_listener, name="discord-gateway", daemon=True)
        self._thread.start()
        # Readiness gate: surface a dead bot (bad token, missing intent) at
        # startup instead of a silently-healthy-looking app. Runs in a worker
        # thread so the event loop is never blocked.
        connected = await asyncio.to_thread(self._wait_until_ready, LISTENER_READY_TIMEOUT)
        if connected:
            log_info(f"Discord gateway listener started, relaying to {self._events_url()}")
        else:
            log_error(
                f"Discord gateway listener not connected after {LISTENER_READY_TIMEOUT:.0f}s — the bot is "
                "offline. Check DISCORD_BOT_TOKEN and that the Message Content Intent is enabled."
            )

    def _wait_until_ready(self, timeout: float) -> bool:
        """Wait for on_ready, bailing early if the listener thread dies."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._ready.wait(timeout=0.25):
                return True
            if self._thread is not None and not self._thread.is_alive():
                return False
        return False

    async def _stop_listener(self) -> None:
        """Close the discord client on its own loop, then join the thread.

        The client lives on the listener thread's event loop, so close() must be
        scheduled there with run_coroutine_threadsafe; wrap_future lets this
        coroutine await the result without blocking the app's event loop.
        """
        if self._client is not None and self._listener_loop is not None and self._listener_loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(self._client.close(), self._listener_loop)
                await asyncio.wait_for(asyncio.wrap_future(future), timeout=LISTENER_STOP_TIMEOUT)
            except Exception as e:
                log_warning(f"Discord gateway client close failed: {e}")
        if self._thread is not None and self._thread.is_alive():
            await asyncio.to_thread(self._thread.join, LISTENER_STOP_TIMEOUT)
            if self._thread.is_alive():
                log_warning(f"Discord gateway thread did not stop within {LISTENER_STOP_TIMEOUT:.0f}s")

    def _events_url(self) -> str:
        return f"{self.app_url}{self.prefix}/gateway/events"

    def _run_listener(self) -> None:
        """Thread target: run the listener on its own event loop until closed."""
        from agno.os.interfaces.discord.listener import DiscordGatewayListener

        assert self.bot_token is not None  # validated in __init__

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._listener_loop = loop
        try:
            self._client = DiscordGatewayListener(
                events_url=self._events_url(),
                gateway_secret=self.gateway_secret,
                respond_to_dms=self.respond_to_dms,
                ready_event=self._ready,
            )
            loop.run_until_complete(self._client.start(self.bot_token))
        except Exception as e:
            log_error(f"Discord gateway listener stopped: {e}")
        finally:
            self._ready.clear()
            # client.start() returns as soon as the connection drops, but the
            # close() task scheduled from the lifespan (and aiohttp's internal
            # teardown) may still be running on this loop — drain before
            # closing or they get destroyed mid-flight
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
