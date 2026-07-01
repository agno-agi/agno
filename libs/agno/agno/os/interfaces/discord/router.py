from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import httpx
from fastapi import APIRouter, Request, Response
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.discord.pipeline import (
    DISCORD_API,
    MAX_MESSAGE_LENGTH,
    STATUS_THINKING,
    THREAD_CHANNEL_TYPES,
    chunk_text,
    create_thread,
    edit_channel_message,
    format_attribution,
    post_in_channel,
    resolve_media,
    resolve_session_id,
    stream_agent_run,
    thread_name_from_question,
)
from agno.os.interfaces.discord.state import (
    build_session_store_config,
    insert_sentinel_session,
)
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error, log_warning
from agno.workflow import RemoteWorkflow, Workflow

INTERACTION_PING = 1
INTERACTION_APPLICATION_COMMAND = 2

RESPONSE_PONG = 1
RESPONSE_CHANNEL_MESSAGE_WITH_SOURCE = 4
RESPONSE_DEFERRED_CHANNEL_MESSAGE = 5

EPHEMERAL_FLAG = 64


def _extract_message_and_media(data: dict) -> Tuple[str, Dict[str, Any]]:
    options = {opt["name"]: opt["value"] for opt in data.get("data", {}).get("options", [])}
    message = str(options.get("question", ""))
    media: Dict[str, Any] = {}
    attachment_id = options.get("file")
    if attachment_id:
        attachments = data.get("data", {}).get("resolved", {}).get("attachments", {})
        attachment = attachments.get(attachment_id)
        if attachment and attachment.get("url"):
            content_type = attachment.get("content_type", "application/octet-stream")
            media = resolve_media(content_type, attachment["url"])
    return message, media


def _extract_ephemeral(data: dict, default: bool) -> bool:
    options = {opt["name"]: opt["value"] for opt in data.get("data", {}).get("options", [])}
    value = options.get("ephemeral")
    if isinstance(value, bool):
        return value
    return default


def _extract_user_id(data: dict) -> str:
    member = data.get("member")
    if isinstance(member, dict):
        user = member.get("user") or {}
        if user.get("id"):
            return user["id"]
    user = data.get("user") or {}
    return user.get("id", "")


def _extract_user_name(data: dict) -> str:
    # Prefer global_name (new Discord display name), fall back to username, then id
    member = data.get("member")
    sources: List[dict] = []
    if isinstance(member, dict) and isinstance(member.get("user"), dict):
        sources.append(member["user"])
    if isinstance(data.get("user"), dict):
        sources.append(data["user"])
    for src in sources:
        name = src.get("global_name") or src.get("username")
        if name:
            return str(name)
    return str((sources[0] if sources else {}).get("id", "")) or "user"


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    public_key: Optional[str] = None,
    application_id: Optional[str] = None,
    bot_token: Optional[str] = None,
    reply_in_thread: bool = True,
    command_name: str = "ask",
    ephemeral: bool = False,
) -> APIRouter:
    entity = agent or team or workflow
    if entity is None:
        raise ValueError("Discord router requires an agent, team, or workflow")
    if not public_key:
        raise ValueError("Discord router requires a public_key")
    if not application_id:
        raise ValueError("Discord router requires an application_id")
    if reply_in_thread and not bot_token:
        raise ValueError("Discord router requires a bot_token when reply_in_thread=True")

    entity_type: Literal["agent", "team", "workflow"] = "agent" if agent else "team" if team else "workflow"
    entity_id: Optional[str] = getattr(entity, "id", None)
    session_cfg = build_session_store_config(entity, entity_type)

    verify_key = VerifyKey(bytes.fromhex(public_key))
    bot_headers = {"Authorization": f"Bot {bot_token}"} if bot_token else {}

    async def _edit_original(client: httpx.AsyncClient, token: str, content: str) -> None:
        url = f"{DISCORD_API}/webhooks/{application_id}/{token}/messages/@original"
        body = content[:MAX_MESSAGE_LENGTH] or "(empty)"
        await client.patch(url, json={"content": body})

    async def _send_followup(client: httpx.AsyncClient, token: str, content: str, ephemeral: bool = False) -> None:
        url = f"{DISCORD_API}/webhooks/{application_id}/{token}"
        body = content[:MAX_MESSAGE_LENGTH] or "(empty)"
        payload: Dict[str, Any] = {"content": body}
        if ephemeral:
            payload["flags"] = EPHEMERAL_FLAG
        await client.post(url, json=payload)

    async def _get_original_message_id(client: httpx.AsyncClient, token: str) -> Optional[str]:
        url = f"{DISCORD_API}/webhooks/{application_id}/{token}/messages/@original"
        resp = await client.get(url)
        if resp.status_code == 200:
            return resp.json().get("id")
        log_warning(f"Fetching original interaction message failed: {resp.status_code} {resp.text}")
        return None

    async def _handle_new_command(data: dict) -> dict:
        user_id = _extract_user_id(data)
        channel_obj = data.get("channel") or {}
        channel_type = channel_obj.get("type")
        channel_id = data.get("channel_id", "")

        if channel_type in THREAD_CHANNEL_TYPES:
            return {
                "type": RESPONSE_CHANNEL_MESSAGE_WITH_SOURCE,
                "data": {
                    "content": "Use `/new` in a main channel — threads already have their own session.",
                    "flags": EPHEMERAL_FLAG,
                },
            }

        if not session_cfg.has_db:
            return {
                "type": RESPONSE_CHANNEL_MESSAGE_WITH_SOURCE,
                "data": {
                    "content": "Session memory isn't configured for this agent. `/new` has no effect.",
                    "flags": EPHEMERAL_FLAG,
                },
            }

        new_session_id = f"discord-{user_id}-{channel_id}-{int(time.time())}"
        try:
            await insert_sentinel_session(session_cfg, new_session_id, user_id, entity_id)
            content = "Fresh conversation started. Your next `/ask` here begins with a clean slate."
        except Exception as e:
            log_error(f"Discord /new sentinel insert failed: {e}")
            content = "Couldn't start a new conversation — check server logs."

        return {
            "type": RESPONSE_CHANNEL_MESSAGE_WITH_SOURCE,
            "data": {"content": content, "flags": EPHEMERAL_FLAG},
        }

    async def _process_ask(data: dict, is_ephemeral: bool = False) -> None:
        token = data["token"]
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                message, media = _extract_message_and_media(data)
                user_id = _extract_user_id(data)
                user_name = _extract_user_name(data)
                guild_id = data.get("guild_id")
                channel_id = data.get("channel_id", "")
                channel_obj = data.get("channel") or {}
                channel_type = channel_obj.get("type")
                already_in_thread = channel_type in THREAD_CHANNEL_TYPES

                attribution = format_attribution(user_name, message)

                # status_channel + status_msg_id identify the message we edit with
                # tool-call status and then the final answer. If both are None, the
                # deferred response itself is the status surface. Ephemeral replies
                # only exist on the interaction webhook — no threads, no channel
                # messages — so the deferred response is always the surface there.
                new_thread_id: Optional[str] = None
                status_channel: Optional[str] = None
                status_msg_id: Optional[str] = None

                if is_ephemeral:
                    pass
                elif reply_in_thread and bot_token and guild_id and not already_in_thread:
                    # New thread: the edited deferred message becomes the thread parent
                    # and shows "{user}: {message}" as attribution
                    thread_name = thread_name_from_question(message)
                    await _edit_original(client, token, attribution)
                    msg_id = await _get_original_message_id(client, token)
                    if msg_id:
                        new_thread_id = await create_thread(client, bot_headers, channel_id, msg_id, thread_name)
                    if new_thread_id:
                        status_channel = new_thread_id
                        status_msg_id = await post_in_channel(client, bot_headers, new_thread_id, STATUS_THINKING)
                elif already_in_thread and bot_token:
                    # Inside an existing thread: show the attribution on the deferred
                    # response, then post a separate status message below it
                    await _edit_original(client, token, attribution)
                    status_channel = channel_id
                    status_msg_id = await post_in_channel(client, bot_headers, channel_id, STATUS_THINKING)

                # Resolve scope + session
                scope_id = new_thread_id or channel_id
                session_id = await resolve_session_id(session_cfg, entity_id, user_id, scope_id)

                # Surface the Discord origin to the agent so tools like DiscordTools
                # can act on "this channel" without the user spelling it out
                dependencies: Dict[str, Any] = {
                    "discord_channel_id": channel_id,
                    "discord_thread_id": new_thread_id or (channel_id if already_in_thread else None),
                    "discord_guild_id": guild_id,
                }

                if status_channel and status_msg_id:
                    _channel = status_channel
                    _msg_id = status_msg_id

                    async def status_edit(content: str) -> None:
                        await edit_channel_message(client, bot_headers, _channel, _msg_id, content)
                else:

                    async def status_edit(content: str) -> None:
                        await _edit_original(client, token, content)

                final_content = await stream_agent_run(
                    entity, message, user_id, session_id, media, dependencies, status_edit
                )

                chunks = chunk_text(final_content)

                if status_channel and status_msg_id:
                    # First chunk replaces the status message; overflow as new messages
                    await edit_channel_message(client, bot_headers, status_channel, status_msg_id, chunks[0])
                    for chunk in chunks[1:]:
                        await post_in_channel(client, bot_headers, status_channel, chunk)
                else:
                    # Status surface IS the deferred response; first chunk replaces status,
                    # overflow rides as webhook followups
                    await _edit_original(client, token, chunks[0])
                    for chunk in chunks[1:]:
                        await _send_followup(client, token, chunk, ephemeral=is_ephemeral)
            except Exception as e:
                log_error(f"Discord interaction failed: {e}")
                try:
                    await _edit_original(client, token, f"Error: {e}")
                except Exception:
                    pass

    @router.post("/interactions")
    async def discord_interactions(request: Request):
        body = await request.body()
        signature = request.headers.get("X-Signature-Ed25519")
        timestamp = request.headers.get("X-Signature-Timestamp")

        if not signature or not timestamp:
            return Response(status_code=401)

        try:
            verify_key.verify(timestamp.encode() + body, bytes.fromhex(signature))
        except (BadSignatureError, ValueError):
            return Response(status_code=401)

        data = json.loads(body)
        interaction_type = data.get("type")

        if interaction_type == INTERACTION_PING:
            return {"type": RESPONSE_PONG}

        if interaction_type == INTERACTION_APPLICATION_COMMAND:
            name = (data.get("data") or {}).get("name", "")
            if name == "new":
                # /new is fast — handle synchronously with an ephemeral reply
                return await _handle_new_command(data)
            if name == command_name:
                is_ephemeral = _extract_ephemeral(data, ephemeral)
                asyncio.create_task(_process_ask(data, is_ephemeral))
                deferred: Dict[str, Any] = {"type": RESPONSE_DEFERRED_CHANNEL_MESSAGE}
                if is_ephemeral:
                    # The flag on the deferred ack makes the whole reply chain ephemeral
                    deferred["data"] = {"flags": EPHEMERAL_FLAG}
                return deferred
            log_warning(f"Unhandled Discord slash command: {name}")
            return {
                "type": RESPONSE_CHANNEL_MESSAGE_WITH_SOURCE,
                "data": {"content": f"Unknown command: /{name}", "flags": EPHEMERAL_FLAG},
            }

        log_warning(f"Unhandled Discord interaction type: {interaction_type}")
        return Response(status_code=204)

    return router
