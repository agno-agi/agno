from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional, Tuple, Union

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

INTERACTION_PING = 1
INTERACTION_APPLICATION_COMMAND = 2

RESPONSE_PONG = 1
RESPONSE_DEFERRED_CHANNEL_MESSAGE = 5


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


def _build_session_id(data: dict, user_id: str) -> str:
    if data.get("guild_id"):
        return f"discord-{data.get('channel_id', '')}"
    return f"discord-dm-{user_id}"


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    public_key: Optional[str] = None,
    application_id: Optional[str] = None,
) -> APIRouter:
    entity = agent or team or workflow
    if entity is None:
        raise ValueError("Discord router requires an agent, team, or workflow")
    if not public_key:
        raise ValueError("Discord router requires a public_key")
    if not application_id:
        raise ValueError("Discord router requires an application_id")

    verify_key = VerifyKey(bytes.fromhex(public_key))

    async def _send_followup(token: str, content: str) -> None:
        url = f"{DISCORD_API}/webhooks/{application_id}/{token}"
        body = content[:_MAX_MESSAGE_LENGTH] or "(empty)"
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(url, json={"content": body})

    async def _process(data: dict) -> None:
        token = data["token"]
        try:
            message, media = _extract_message_and_media(data)
            user_id = _extract_user_id(data)
            session_id = _build_session_id(data, user_id)

            result = await entity.arun(  # type: ignore[union-attr]
                message,
                user_id=user_id,
                session_id=session_id,
                **media,
            )
            content = result.content if result and result.content else "(empty response)"
            await _send_followup(token, content)
        except Exception as e:
            log_error(f"Discord interaction failed: {e}")
            try:
                await _send_followup(token, f"Error: {e}")
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
