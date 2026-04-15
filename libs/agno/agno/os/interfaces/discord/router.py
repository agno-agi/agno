from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
from fastapi import APIRouter, Request, Response
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from agno.agent import Agent, RemoteAgent
from agno.media import Audio, File, Image, Video
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error, log_warning
from agno.workflow import RemoteWorkflow, Workflow

DISCORD_API = "https://discord.com/api/v10"
_MAX_MESSAGE_LENGTH = 2000
_MAX_THREAD_NAME_LENGTH = 100

INTERACTION_PING = 1
INTERACTION_APPLICATION_COMMAND = 2

RESPONSE_PONG = 1
RESPONSE_DEFERRED_CHANNEL_MESSAGE = 5

# Discord channel types considered threads
_THREAD_CHANNEL_TYPES = {10, 11, 12}  # ANNOUNCEMENT, PUBLIC, PRIVATE


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


def _thread_name_from_question(question: str) -> str:
    # Discord caps thread names at 100 chars; also strip newlines so it reads cleanly
    name = " ".join(question.split()).strip() or "Conversation"
    return name[:_MAX_THREAD_NAME_LENGTH]


def _chunk_text(text: str, max_len: int = _MAX_MESSAGE_LENGTH) -> List[str]:
    # Split at natural boundaries so code blocks / paragraphs don't get cleaved
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


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    public_key: Optional[str] = None,
    application_id: Optional[str] = None,
    bot_token: Optional[str] = None,
    reply_in_thread: bool = False,
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

    async def _post_in_thread(client: httpx.AsyncClient, thread_id: str, content: str) -> None:
        url = f"{DISCORD_API}/channels/{thread_id}/messages"
        body = content[:_MAX_MESSAGE_LENGTH] or "(empty)"
        await client.post(url, headers=bot_headers, json={"content": body})

    async def _keep_typing(client: httpx.AsyncClient, channel_id: str) -> None:
        # Discord's typing indicator lasts ~10s; refresh every 8s while the agent runs
        url = f"{DISCORD_API}/channels/{channel_id}/typing"
        try:
            while True:
                try:
                    await client.post(url, headers=bot_headers)
                except Exception as e:
                    log_warning(f"Discord typing indicator failed: {e}")
                await asyncio.sleep(8)
        except asyncio.CancelledError:
            raise

    async def _process(data: dict) -> None:
        token = data["token"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                message, media = _extract_message_and_media(data)
                user_id = _extract_user_id(data)
                guild_id = data.get("guild_id")
                channel_id = data.get("channel_id", "")
                channel = data.get("channel") or {}
                channel_type = channel.get("type")
                already_in_thread = channel_type in _THREAD_CHANNEL_TYPES

                # If we should spawn a new thread, do it *before* running the agent
                # so the thread id can be used as the session id.
                new_thread_id: Optional[str] = None
                if reply_in_thread and bot_token and guild_id and not already_in_thread:
                    thread_name = _thread_name_from_question(message)
                    # Show the question as the thread-parent message so the header reads well
                    await _edit_original(client, token, f"**{thread_name}**")
                    msg_id = await _get_original_message_id(client, token)
                    if msg_id:
                        new_thread_id = await _create_thread(client, channel_id, msg_id, thread_name)

                # One session per thread so history is scoped to the conversation
                if new_thread_id:
                    session_id = f"discord-thread-{new_thread_id}"
                elif already_in_thread:
                    session_id = f"discord-thread-{channel_id}"
                elif guild_id:
                    session_id = f"discord-{channel_id}"
                else:
                    session_id = f"discord-dm-{user_id}"

                # Show "Bot is typing..." inside the thread while the agent runs so
                # the UI doesn't appear frozen after thread creation
                typing_channel = new_thread_id or (channel_id if already_in_thread else None)
                typing_task: Optional[asyncio.Task] = None
                if typing_channel and bot_token:
                    typing_task = asyncio.create_task(_keep_typing(client, typing_channel))

                try:
                    result = await entity.arun(  # type: ignore[union-attr]
                        message,
                        user_id=user_id,
                        session_id=session_id,
                        **media,
                    )
                finally:
                    if typing_task:
                        typing_task.cancel()
                        try:
                            await typing_task
                        except (asyncio.CancelledError, Exception):
                            pass

                content = result.content if result and result.content else "(empty response)"
                chunks = _chunk_text(content)

                if new_thread_id:
                    # New thread: every chunk goes in as a fresh bot message
                    for chunk in chunks:
                        await _post_in_thread(client, new_thread_id, chunk)
                else:
                    # First chunk replaces the "thinking..." deferred response;
                    # any overflow rides along as separate followup messages
                    # (in-thread deferred responses followup into the same thread)
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
            asyncio.create_task(_process(data))
            return {"type": RESPONSE_DEFERRED_CHANNEL_MESSAGE}

        log_warning(f"Unhandled Discord interaction type: {interaction_type}")
        return Response(status_code=204)

    return router
