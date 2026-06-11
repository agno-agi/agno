"""FastAPI routes for the Discord Gateway relay.

The gateway listener (a discord.py client running in a background thread, or an
external relay process) POSTs serialized message events here. Unlike Discord's
own Interactions webhooks, relayed gateway events carry no Ed25519 signature —
a shared secret header is the only gate, so the endpoint rejects anything
without it.
"""

from __future__ import annotations

import asyncio
import hmac
import re
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
    stream_agent_run,
    thread_name_from_question,
)
from agno.os.interfaces.discord.state import build_session_store_config
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error, log_warning
from agno.workflow import RemoteWorkflow, Workflow

GATEWAY_SECRET_HEADER = "X-Discord-Gateway-Secret"


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
    entity_id: Optional[str] = getattr(entity, "id", None)
    session_cfg = build_session_store_config(entity, entity_type)

    bot_headers = {"Authorization": f"Bot {bot_token}"}

    async def _process_message(payload: dict) -> None:
        async with httpx.AsyncClient(timeout=60.0) as client:
            status_channel: Optional[str] = None
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
                # message; inside threads and DMs reply inline with a status message
                new_thread_id: Optional[str] = None
                if reply_in_thread and guild_id and not is_dm and not is_thread and message_id:
                    new_thread_id = await create_thread(
                        client, bot_headers, channel_id, message_id, thread_name_from_question(message)
                    )
                status_channel = new_thread_id or channel_id
                status_msg_id = await post_in_channel(client, bot_headers, status_channel, STATUS_THINKING)
                if not status_msg_id:
                    log_warning("Discord gateway: could not post status message, skipping event")
                    return

                scope_id = new_thread_id or channel_id
                session_id = await resolve_session_id(session_cfg, entity_id, user_id, scope_id)

                dependencies: Dict[str, Any] = {
                    "discord_channel_id": channel_id,
                    "discord_thread_id": new_thread_id or (channel_id if is_thread else None),
                    "discord_guild_id": guild_id,
                }

                _channel = status_channel
                _msg_id = status_msg_id

                async def status_edit(content: str) -> None:
                    await edit_channel_message(client, bot_headers, _channel, _msg_id, content)

                final_content = await stream_agent_run(
                    entity, message, user_id, session_id, media, dependencies, status_edit
                )

                chunks = chunk_text(final_content)
                await edit_channel_message(client, bot_headers, status_channel, status_msg_id, chunks[0])
                for chunk in chunks[1:]:
                    await post_in_channel(client, bot_headers, status_channel, chunk)
            except Exception as e:
                log_error(f"Discord gateway event processing failed: {e}")
                if status_channel and status_msg_id:
                    try:
                        await edit_channel_message(client, bot_headers, status_channel, status_msg_id, f"Error: {e}")
                    except Exception:
                        pass

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

        asyncio.create_task(_process_message(payload))
        return {"status": "accepted"}

    return router
