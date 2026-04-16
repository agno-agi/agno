from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import httpx
from fastapi import APIRouter, Request, Response
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from agno.agent import Agent, RemoteAgent
from agno.media import Audio, File, Image, Video
from agno.os.interfaces.discord.state import (
    build_session_store_config,
    find_latest_session_id,
    insert_sentinel_session,
)
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error, log_warning
from agno.workflow import RemoteWorkflow, Workflow

DISCORD_API = "https://discord.com/api/v10"
_MAX_MESSAGE_LENGTH = 2000
_MAX_THREAD_NAME_LENGTH = 100

INTERACTION_PING = 1
INTERACTION_APPLICATION_COMMAND = 2

RESPONSE_PONG = 1
RESPONSE_CHANNEL_MESSAGE_WITH_SOURCE = 4
RESPONSE_DEFERRED_CHANNEL_MESSAGE = 5

EPHEMERAL_FLAG = 64

# Discord channel types considered threads
_THREAD_CHANNEL_TYPES = {10, 11, 12}  # ANNOUNCEMENT, PUBLIC, PRIVATE

# Event names emitted by agents (and their Team-prefixed siblings)
_TOOL_STARTED_EVENTS = {"ToolCallStarted", "TeamToolCallStarted"}
_TOOL_ENDED_EVENTS = {"ToolCallCompleted", "TeamToolCallCompleted", "ToolCallError", "TeamToolCallError"}

STATUS_THINKING = "Thinking..."


def _resolve_media(content_type: str, url: str) -> Dict[str, Any]:
    if content_type.startswith("image/"):
        return {"images": [Image(url=url)]}
    if content_type.startswith("audio/"):
        return {"audio": [Audio(url=url)]}
    if content_type.startswith("video/"):
        return {"videos": [Video(url=url)]}
    return {"files": [File(url=url)]}


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
            media = _resolve_media(content_type, attachment["url"])
    return message, media


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


def _format_attribution(user_name: str, message: str, max_len: int = _MAX_MESSAGE_LENGTH) -> str:
    prefix = f"{user_name}: "
    remaining = max_len - len(prefix)
    if remaining <= 0:
        # User name alone blew the cap (pathological) — just truncate the whole line
        return f"{user_name}: {message}"[:max_len]
    if len(message) > remaining:
        # Trim message with an ellipsis so the attribution still reads as a quote
        message = message[: remaining - 1].rstrip() + "…"
    return f"{prefix}{message}"


def _thread_name_from_question(question: str) -> str:
    name = " ".join(question.split()).strip() or "Conversation"
    return name[:_MAX_THREAD_NAME_LENGTH]


def _chunk_text(text: str, max_len: int = _MAX_MESSAGE_LENGTH) -> List[str]:
    if not text:
        return ["(empty)"]
    if len(text) <= max_len:
        return [text]
    chunks: List[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n\n", 0, max_len)
        if cut <= 0:
            cut = remaining.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = remaining.rfind(" ", 0, max_len)
        if cut <= 0:
            cut = max_len
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    return chunks


def _format_tool_status(active: "OrderedDict[str, str]") -> str:
    names = list(active.values())
    if not names:
        return STATUS_THINKING
    if len(names) == 1:
        return f"Running tool: {names[0]}..."
    return f"Running: {', '.join(names)}..."


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
        body = content[:_MAX_MESSAGE_LENGTH] or "(empty)"
        await client.patch(url, json={"content": body})

    async def _send_followup(client: httpx.AsyncClient, token: str, content: str) -> None:
        url = f"{DISCORD_API}/webhooks/{application_id}/{token}"
        body = content[:_MAX_MESSAGE_LENGTH] or "(empty)"
        await client.post(url, json={"content": body})

    async def _get_original_message_id(client: httpx.AsyncClient, token: str) -> Optional[str]:
        url = f"{DISCORD_API}/webhooks/{application_id}/{token}/messages/@original"
        resp = await client.get(url)
        if resp.status_code == 200:
            return resp.json().get("id")
        log_warning(f"Fetching original interaction message failed: {resp.status_code} {resp.text}")
        return None

    async def _create_thread(client: httpx.AsyncClient, channel_id: str, message_id: str, name: str) -> Optional[str]:
        url = f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}/threads"
        payload = {"name": name, "auto_archive_duration": 60}
        resp = await client.post(url, headers=bot_headers, json=payload)
        if resp.status_code in (200, 201):
            return resp.json().get("id")
        log_warning(f"Thread creation failed: {resp.status_code} {resp.text}")
        return None

    async def _post_in_channel(client: httpx.AsyncClient, channel_id: str, content: str) -> Optional[str]:
        url = f"{DISCORD_API}/channels/{channel_id}/messages"
        body = content[:_MAX_MESSAGE_LENGTH] or "(empty)"
        resp = await client.post(url, headers=bot_headers, json={"content": body})
        if resp.status_code in (200, 201):
            return resp.json().get("id")
        log_warning(f"Posting message failed: {resp.status_code} {resp.text}")
        return None

    async def _edit_channel_message(client: httpx.AsyncClient, channel_id: str, message_id: str, content: str) -> None:
        url = f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}"
        body = content[:_MAX_MESSAGE_LENGTH] or "(empty)"
        await client.patch(url, headers=bot_headers, json={"content": body})

    async def _resolve_session_id(user_id: str, scope_id: str) -> str:
        prefix = f"discord-{user_id}-{scope_id}-"
        if session_cfg.has_db:
            try:
                found = await find_latest_session_id(session_cfg, user_id, entity_id, session_scope=prefix)
                if found:
                    return found
            except Exception as e:
                log_warning(f"Discord session lookup failed, minting fresh: {e}")
        return f"{prefix}{int(time.time())}"

    async def _handle_new_command(data: dict) -> dict:
        user_id = _extract_user_id(data)
        channel_obj = data.get("channel") or {}
        channel_type = channel_obj.get("type")
        channel_id = data.get("channel_id", "")

        if channel_type in _THREAD_CHANNEL_TYPES:
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

    async def _stream_agent_run(
        client: httpx.AsyncClient,
        message: str,
        user_id: str,
        session_id: str,
        media: Dict[str, Any],
        dependencies: Dict[str, Any],
        status_edit,
    ) -> str:
        """Run the agent with streaming, editing the status surface as tools start/finish.

        `status_edit` is an async callable taking a single `content: str` arg that
        writes to whichever message is acting as the status surface (deferred response
        or thread status message).
        """
        active: "OrderedDict[str, str]" = OrderedDict()
        last_status = STATUS_THINKING
        final_content = ""

        await status_edit(STATUS_THINKING)

        # Remote entities proxy to a server and don't accept dependency kwargs;
        # only pass them to local agents/teams/workflows
        is_remote = isinstance(entity, (RemoteAgent, RemoteTeam, RemoteWorkflow))
        run_kwargs: Dict[str, Any] = {
            "user_id": user_id,
            "session_id": session_id,
            "stream": True,
            "stream_events": True,
            "yield_run_output": True,
            **media,
        }
        if not is_remote:
            run_kwargs["dependencies"] = dependencies
            run_kwargs["add_dependencies_to_context"] = True

        async for event in entity.arun(message, **run_kwargs):  # type: ignore[union-attr, call-overload]
            if isinstance(event, (RunOutput, TeamRunOutput)):
                if event.content:
                    final_content = event.content if isinstance(event.content, str) else str(event.content)
                continue

            event_name = getattr(event, "event", "")
            tool = getattr(event, "tool", None)
            tool_name = getattr(tool, "tool_name", None) if tool else None
            call_id = getattr(tool, "tool_call_id", None) if tool else None

            if event_name in _TOOL_STARTED_EVENTS and tool_name:
                key = call_id or f"{tool_name}-{len(active)}"
                active[key] = tool_name
            elif event_name in _TOOL_ENDED_EVENTS:
                if call_id and call_id in active:
                    active.pop(call_id, None)
                elif tool_name:
                    # Fallback: pop the first entry matching this name
                    for k, v in list(active.items()):
                        if v == tool_name:
                            active.pop(k, None)
                            break
            else:
                continue

            status = _format_tool_status(active)
            if status != last_status:
                try:
                    await status_edit(status)
                except Exception as e:
                    log_warning(f"Discord tool-status edit failed: {e}")
                last_status = status

        return final_content or "(empty response)"

    async def _process_ask(data: dict) -> None:
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
                already_in_thread = channel_type in _THREAD_CHANNEL_TYPES

                attribution = _format_attribution(user_name, message)

                # status_channel + status_msg_id identify the message we edit with
                # tool-call status and then the final answer. If both are None, the
                # deferred response itself is the status surface.
                new_thread_id: Optional[str] = None
                status_channel: Optional[str] = None
                status_msg_id: Optional[str] = None

                if reply_in_thread and bot_token and guild_id and not already_in_thread:
                    # New thread: the edited deferred message becomes the thread parent
                    # and shows "{user}: {message}" as attribution
                    thread_name = _thread_name_from_question(message)
                    await _edit_original(client, token, attribution)
                    msg_id = await _get_original_message_id(client, token)
                    if msg_id:
                        new_thread_id = await _create_thread(client, channel_id, msg_id, thread_name)
                    if new_thread_id:
                        status_channel = new_thread_id
                        status_msg_id = await _post_in_channel(client, new_thread_id, STATUS_THINKING)
                elif already_in_thread and bot_token:
                    # Inside an existing thread: show the attribution on the deferred
                    # response, then post a separate status message below it
                    await _edit_original(client, token, attribution)
                    status_channel = channel_id
                    status_msg_id = await _post_in_channel(client, channel_id, STATUS_THINKING)

                # Resolve scope + session
                scope_id = new_thread_id or channel_id
                session_id = await _resolve_session_id(user_id, scope_id)

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
                        await _edit_channel_message(client, _channel, _msg_id, content)
                else:

                    async def status_edit(content: str) -> None:
                        await _edit_original(client, token, content)

                final_content = await _stream_agent_run(
                    client, message, user_id, session_id, media, dependencies, status_edit
                )

                chunks = _chunk_text(final_content)

                if status_channel and status_msg_id:
                    # First chunk replaces the status message; overflow as new messages
                    await _edit_channel_message(client, status_channel, status_msg_id, chunks[0])
                    for chunk in chunks[1:]:
                        await _post_in_channel(client, status_channel, chunk)
                else:
                    # Status surface IS the deferred response; first chunk replaces status,
                    # overflow rides as webhook followups
                    await _edit_original(client, token, chunks[0])
                    for chunk in chunks[1:]:
                        await _send_followup(client, token, chunk)
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
                asyncio.create_task(_process_ask(data))
                return {"type": RESPONSE_DEFERRED_CHANNEL_MESSAGE}
            log_warning(f"Unhandled Discord slash command: {name}")
            return {
                "type": RESPONSE_CHANNEL_MESSAGE_WITH_SOURCE,
                "data": {"content": f"Unknown command: /{name}", "flags": EPHEMERAL_FLAG},
            }

        log_warning(f"Unhandled Discord interaction type: {interaction_type}")
        return Response(status_code=204)

    return router
