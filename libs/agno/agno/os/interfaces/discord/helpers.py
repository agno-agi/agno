from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp

from agno.media import Audio, File, Image, Video
from agno.utils.log import log_error, log_info, log_warning

DISCORD_API_BASE = "https://discord.com/api/v10"
FALLBACK_ERROR_MESSAGE = "Sorry, there was an error processing your message."

_MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
_MAX_EMBED_DESCRIPTION = 4096
_FOLLOWUP_CHUNK_SIZE = 1900  # 100 under Discord's 2000-char cap for "(1/N)" markers
_DOWNLOAD_TIMEOUT = 30
_DOWNLOAD_CHUNK_SIZE = 64 * 1024

# Discord's "parse nothing" allowed_mentions — renders @everyone / @role / @user
# as plain text without notifying anyone. Applied to every outbound message as
# defense against model-generated or prompt-injected mentions reaching users.
_SAFE_MENTIONS: Dict[str, Any] = {"parse": []}

# (response_attr, log_label, default_filename) for each media type
_MEDIA_SPECS = (
    ("images", "image", "image.png"),
    ("files", "file", "file.bin"),
    ("videos", "video", "video.mp4"),
    ("audio", "audio", "audio.mp3"),
)


def _message_payload(**fields: Any) -> Dict[str, Any]:
    # Every outbound payload passes here so allowed_mentions is never forgotten
    return {"allowed_mentions": _SAFE_MENTIONS, **{k: v for k, v in fields.items() if v is not None}}


async def _raise_for_status(resp: aiohttp.ClientResponse, operation: str) -> None:
    # aiohttp's raise_for_status drops the response body; re-raise with it included
    if resp.ok:
        return
    body = await resp.text()
    log_error(f"Failed to {operation} ({resp.status}): {body}")
    raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=resp.status, message=body)


def build_status_embed(
    title: str,
    description: str,
    fields: List[Dict[str, Any]],
) -> Dict[str, Any]:
    embed: Dict[str, Any] = {"title": title}
    if description:
        embed["description"] = description
    if fields:
        embed["fields"] = fields
    return embed


def format_attribution(user_name: str, message: str, max_len: int = 2000) -> str:
    prefix = f"{user_name}: "
    budget = max_len - len(prefix)
    if budget <= 0:
        return f"{prefix}{message}"[:max_len]
    if len(message) > budget:
        message = message[: budget - 1].rstrip() + "…"
    return f"{prefix}{message}"


def format_thread_name(text: str, max_len: int = 100) -> str:
    name = " ".join(text.split()).strip() or "Conversation"
    return name[:max_len]


def extract_interaction_options(data: Dict[str, Any]) -> str:
    for opt in data.get("data", {}).get("options", []):
        if opt.get("name") == "message":
            return opt.get("value", "")
    return ""


def extract_user(data: Dict[str, Any]) -> tuple[str, str]:
    # Guild interactions nest the user under member.user; DMs use top-level user.
    # Prefer display name (global_name) over username for the returned name.
    member = data.get("member") or {}
    for user in (member.get("user"), data.get("user")):
        if not user:
            continue
        user_id = user.get("id", "")
        name = user.get("global_name") or user.get("username") or user_id or "user"
        return user_id, name
    return "", "user"


@dataclass
class DiscordWebhook:
    # Bound to one Discord interaction. Interaction tokens expire 15 minutes
    # after ACK — one instance spans one /ask lifecycle.
    session: aiohttp.ClientSession
    application_id: str
    interaction_token: str

    def _url(self, *, original: bool = False) -> str:
        base = f"{DISCORD_API_BASE}/webhooks/{self.application_id}/{self.interaction_token}"
        return f"{base}/messages/@original" if original else base

    async def edit_original(
        self,
        *,
        content: Optional[str] = None,
        embeds: Optional[List[Dict[str, Any]]] = None,
        components: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        payload = _message_payload(content=content, embeds=embeds, components=components)
        async with self.session.patch(self._url(original=True), json=payload) as resp:
            await _raise_for_status(resp, "edit original response")

    async def send_followup(
        self,
        *,
        content: Optional[str] = None,
        embeds: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[str]:
        payload = _message_payload(content=content, embeds=embeds)
        async with self.session.post(self._url(), json=payload) as resp:
            await _raise_for_status(resp, "send followup")
            return (await resp.json()).get("id")

    async def upload_file(self, content_bytes: bytes, filename: str) -> None:
        form = aiohttp.FormData()
        form.add_field(
            "payload_json",
            json.dumps(_message_payload(content="")),
            content_type="application/json",
        )
        form.add_field("files[0]", content_bytes, filename=filename)
        async with self.session.post(self._url(), data=form) as resp:
            await _raise_for_status(resp, "upload file")

    async def get_original_message_id(self) -> Optional[str]:
        # Non-fatal — caller falls back to not creating a thread if this fails
        async with self.session.get(self._url(original=True)) as resp:
            if not resp.ok:
                log_warning(f"Could not fetch original interaction message ({resp.status})")
                return None
            return (await resp.json()).get("id")

    async def send_response_media(self, response: Any) -> None:
        for attr, label, default_name in _MEDIA_SPECS:
            for item in getattr(response, attr, None) or []:
                content_bytes = await item.aget_content_bytes()
                if not content_bytes:
                    continue
                filename = getattr(item, "filename", None) or default_name
                try:
                    await self.upload_file(content_bytes, filename)
                except Exception as e:
                    log_error(f"Failed to upload {label}: {e}")


@dataclass
class DiscordBotClient:
    # Bot-token authenticated client for operations outside the interaction scope:
    # command registration (app-scoped), thread creation (channel-scoped). Pairs
    # with DiscordWebhook, which handles interaction-scoped webhook token calls.
    session: aiohttp.ClientSession
    bot_token: str

    async def _api_call(self, method: str, endpoint: str, operation: str, **kwargs: Any) -> Optional[Any]:
        url = f"{DISCORD_API_BASE}{endpoint}"
        headers = {"Authorization": f"Bot {self.bot_token}", "Content-Type": "application/json"}
        try:
            async with self.session.request(method, url, headers=headers, **kwargs) as resp:
                if not resp.ok:
                    log_warning(f"Failed to {operation} ({resp.status}): {await resp.text()}")
                    return None
                return await resp.json() if resp.content_length else None
        except Exception as e:
            log_error(f"Failed to {operation}: {e}")
            return None

    async def create_message_thread(self, channel_id: str, message_id: str, name: str) -> Optional[str]:
        # 100-char name and 60-min archive are Discord API limits for thread creation
        payload = {"name": name[:100], "auto_archive_duration": 60}
        data = await self._api_call(
            "POST",
            f"/channels/{channel_id}/messages/{message_id}/threads",
            "create thread",
            json=payload,
        )
        return data.get("id") if data else None

    async def register_commands(self, application_id: str, commands: List[Dict[str, Any]]) -> None:
        data = await self._api_call(
            "PUT",
            f"/applications/{application_id}/commands",
            "register commands",
            json=commands,
        )
        if data:
            log_info(f"Registered Discord commands: {[c.get('name', '?') for c in data]}")


async def download_attachment(
    session: aiohttp.ClientSession,
    url: str,
    max_size: int = _MAX_ATTACHMENT_BYTES,
) -> Optional[bytes]:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=_DOWNLOAD_TIMEOUT)) as resp:
            resp.raise_for_status()
            if (resp.content_length or 0) > max_size:
                log_warning(f"Attachment {resp.content_length}B exceeds {max_size}B cap, skipping")
                return None
            # Stream-bound read so a lying Content-Length can't OOM us
            chunks: List[bytes] = []
            total = 0
            async for chunk in resp.content.iter_chunked(_DOWNLOAD_CHUNK_SIZE):
                total += len(chunk)
                if total > max_size:
                    log_warning(f"Attachment exceeded {max_size}B cap during stream, skipping")
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
    except Exception as e:
        log_error(f"Failed to download attachment: {e}")
        return None


async def download_resolved_attachments(
    session: aiohttp.ClientSession,
    data: Dict[str, Any],
) -> Dict[str, List[Any]]:
    resolved = data.get("data", {}).get("resolved", {}).get("attachments") or {}
    if not resolved:
        return {}

    async def fetch(att: Dict[str, Any]) -> Optional[tuple]:
        url = att.get("url")
        # Manifest size is user-controlled and may lie; download_attachment
        # re-checks Content-Length + streams with a byte cap as defense-in-depth
        if not url or att.get("size", 0) > _MAX_ATTACHMENT_BYTES:
            if url:
                log_warning(f"Attachment exceeds size cap, skipping: {att.get('filename')}")
            return None
        content = await download_attachment(session, url)
        if not content:
            return None
        return content, att.get("content_type", "application/octet-stream"), att.get("filename", "file")

    fetched = await asyncio.gather(*(fetch(att) for att in resolved.values()), return_exceptions=True)

    media: Dict[str, List[Any]] = {}
    for result in fetched:
        if isinstance(result, BaseException):
            log_error(f"Attachment download failed: {result}")
            continue
        if not result:
            continue
        content, mime, filename = result
        if mime.startswith("image/"):
            media.setdefault("images", []).append(Image(content=content))
        elif mime.startswith("audio/"):
            media.setdefault("audio", []).append(Audio(content=content))
        elif mime.startswith("video/"):
            media.setdefault("videos", []).append(Video(content=content))
        else:
            media.setdefault("files", []).append(File(content=content, filename=filename))
    return media
