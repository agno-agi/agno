"""FastAPI routes for the Discord Gateway relay.

The gateway listener (or an external relay) POSTs message payloads to
``/discord/gateway/events``, authenticated by a shared-secret header. Accepted
messages run in the background: open a reply thread when appropriate, show the
native typing indicator, stream the run, deliver the answer over Discord REST.
"""

from __future__ import annotations

import asyncio
import hmac
import re
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Union

import httpx
from fastapi import APIRouter, Request, Response

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.discord.pipeline import (
    STATUS_THINKING,
    chunk_text,
    create_thread,
    edit_channel_message,
    post_in_channel,
    resolve_media,
    resolve_session_id,
    run_in_background,
    stream_agent_run,
    thread_name_from_question,
    trigger_typing,
)
from agno.os.interfaces.discord.state import SessionStoreConfig, build_session_store_config
from agno.team import RemoteTeam, Team
from agno.utils.http import get_default_async_client
from agno.utils.log import log_error
from agno.workflow import RemoteWorkflow, Workflow

GATEWAY_SECRET_HEADER = "X-Discord-Gateway-Secret"


@dataclass(frozen=True)
class GatewayContext:
    """Config the gateway handlers need, built once in attach_gateway_routes."""

    entity: Any  # Agent | Team | Workflow (or Remote variants)
    entity_id: Optional[str]
    session_cfg: SessionStoreConfig
    bot_headers: Dict[str, str]
    reply_in_thread: bool


# ---------------------------------------------------------------------------
# Gating (pure functions — also exercised directly by unit tests)
# ---------------------------------------------------------------------------


def strip_bot_mention(content: str, bot_user_id: str) -> str:
    return re.sub(rf"<@!?{re.escape(bot_user_id)}>", "", content).strip()


def should_respond(payload: dict, respond_to_dms: bool = True) -> bool:
    """Mention-gating: DMs always (unless disabled), threads when mentioned or the
    bot participates, guild channels only when mentioned. Bots (including self) never."""
    author = payload.get("author") or {}
    if author.get("bot") or author.get("id") == payload.get("bot_user_id"):
        return False
    if payload.get("is_dm"):
        return respond_to_dms
    if payload.get("is_thread"):
        return bool(payload.get("mentions_bot") or payload.get("bot_in_thread"))
    return bool(payload.get("mentions_bot"))


# ---------------------------------------------------------------------------
# Message processing
# ---------------------------------------------------------------------------


async def keep_typing(ctx: GatewayContext, client: httpx.AsyncClient, channel_id: str, stop: asyncio.Event) -> None:
    # The indicator lasts up to 10 seconds per trigger — refresh until stopped
    while not stop.is_set():
        await trigger_typing(client, ctx.bot_headers, channel_id)
        try:
            await asyncio.wait_for(stop.wait(), timeout=8.0)
        except asyncio.TimeoutError:
            pass


async def process_message(ctx: GatewayContext, payload: dict) -> None:
    """Run the entity for one relayed message and deliver the answer.

    Reply surface: a new thread off the user's message in guild channels;
    inline in existing threads and DMs. The typing indicator runs while the
    entity does; a status message only appears when a tool runs, then becomes
    the answer.
    """
    client = get_default_async_client()
    reply_channel: Optional[str] = None
    status_msg_id: Optional[str] = None
    try:
        bot_user_id = payload.get("bot_user_id", "")
        message = strip_bot_mention(payload.get("content", ""), bot_user_id)
        user_id = (payload.get("author") or {}).get("id", "")
        guild_id = payload.get("guild_id")
        channel_id = payload.get("channel_id", "")
        message_id = payload.get("message_id", "")
        is_dm = bool(payload.get("is_dm"))
        is_thread = bool(payload.get("is_thread"))

        media: Dict[str, Any] = {}
        attachments = payload.get("attachments") or []
        if attachments:
            first = attachments[0]
            if first.get("url"):
                content_type = first.get("content_type") or "application/octet-stream"
                media = resolve_media(content_type, first["url"])

        if not message and not media:
            return

        # Reply surface: in a guild channel start a thread off the user's own
        # message; inside threads and DMs reply inline
        new_thread_id: Optional[str] = None
        if ctx.reply_in_thread and guild_id and not is_dm and not is_thread and message_id:
            new_thread_id = await create_thread(
                client, ctx.bot_headers, channel_id, message_id, thread_name_from_question(message)
            )
        reply_channel = new_thread_id or channel_id

        # Session scope: thread id if we opened one, else channel id
        scope_id = new_thread_id or channel_id
        session_id = await resolve_session_id(ctx.session_cfg, ctx.entity_id, user_id, scope_id)

        # Surface the Discord origin to the agent so tools like DiscordTools
        # can act on "this channel" without the user spelling it out
        dependencies: Dict[str, Any] = {
            "discord_channel_id": channel_id,
            "discord_thread_id": new_thread_id or (channel_id if is_thread else None),
            "discord_guild_id": guild_id,
        }

        # The native typing indicator covers "the bot is working"; a status
        # message is only posted when there is real tool activity to show
        _channel = reply_channel

        async def status_edit(content: str) -> None:
            nonlocal status_msg_id
            if status_msg_id is None:
                if content == STATUS_THINKING:
                    return
                status_msg_id = await post_in_channel(client, ctx.bot_headers, _channel, content)
            else:
                await edit_channel_message(client, ctx.bot_headers, _channel, status_msg_id, content)

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(ctx, client, reply_channel, stop_typing))
        try:
            final_content = await stream_agent_run(
                ctx.entity, message, user_id, session_id, media, dependencies, status_edit
            )
        finally:
            stop_typing.set()
            await typing_task

        chunks = chunk_text(final_content)
        if status_msg_id:
            # The tool-status message becomes the answer; overflow as new messages
            await edit_channel_message(client, ctx.bot_headers, reply_channel, status_msg_id, chunks[0])
            chunks = chunks[1:]
        for chunk in chunks:
            await post_in_channel(client, ctx.bot_headers, reply_channel, chunk)
    except Exception as e:
        log_error(f"Discord gateway event processing failed: {e}")
        if reply_channel:
            try:
                if status_msg_id:
                    await edit_channel_message(client, ctx.bot_headers, reply_channel, status_msg_id, f"Error: {e}")
                else:
                    await post_in_channel(client, ctx.bot_headers, reply_channel, f"Error: {e}")
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def attach_gateway_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    bot_token: Optional[str] = None,
    gateway_secret: Optional[str] = None,
    reply_in_thread: bool = True,
    respond_to_dms: bool = True,
) -> APIRouter:
    entity = agent or team or workflow
    if entity is None:
        raise ValueError("Discord gateway router requires an agent, team, or workflow")
    if not bot_token:
        raise ValueError("Discord gateway router requires a bot_token")
    if not gateway_secret:
        raise ValueError("Discord gateway router requires a gateway_secret")

    entity_type: Literal["agent", "team", "workflow"] = "agent" if agent else "team" if team else "workflow"

    ctx = GatewayContext(
        entity=entity,
        entity_id=getattr(entity, "id", None),
        session_cfg=build_session_store_config(entity, entity_type),
        bot_headers={"Authorization": f"Bot {bot_token}"},
        reply_in_thread=reply_in_thread,
    )

    @router.post("/gateway/events")
    async def discord_gateway_events(request: Request):
        secret = request.headers.get(GATEWAY_SECRET_HEADER, "")
        if not secret or not hmac.compare_digest(secret, gateway_secret):
            return Response(status_code=401)

        payload = await request.json()
        if payload.get("type") != "message":
            return {"status": "ignored"}

        # The listener pre-filters as an optimization; the endpoint is the authority
        if not should_respond(payload, respond_to_dms=respond_to_dms):
            return {"status": "ignored"}

        run_in_background(process_message(ctx, payload))
        return {"status": "accepted"}

    return router
