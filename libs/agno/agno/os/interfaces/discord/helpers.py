from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from agno.media import Audio, File, Image, Video
from agno.utils.log import log_error, log_warning

DISCORD_API_BASE = "https://discord.com/api/v10"


def bot_api_headers(bot_token: str) -> Dict[str, str]:
    # Bot-token auth is used for channel/thread API calls; webhook calls use
    # the interaction token embedded in the URL instead and need no headers
    return {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}


# Discord message/embed/thread limits — values come from the Discord API reference
_MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MB — Discord rejects uploads over this
_MAX_EMBED_DESCRIPTION = 4096  # chars — longer descriptions get truncated + followups
_FOLLOWUP_CHUNK_SIZE = 1900  # leaves ~100-char headroom under the 2000-char message limit for overflow markers
_THREAD_NAME_MAX = 100  # chars — Discord rejects longer thread names
_THREAD_AUTO_ARCHIVE_MINUTES = 60  # 60 = 1h, shortest auto-archive window Discord allows

EMBED_COLOR_PROCESSING = 0x5865F2  # Discord blurple
EMBED_COLOR_COMPLETE = 0x57F287  # Green
EMBED_COLOR_ERROR = 0xED4245  # Red

FALLBACK_ERROR_MESSAGE = "Sorry, there was an error processing your message."

# Suppress all mention parsing — prevents @everyone/@here/role pings from model output
_SAFE_MENTIONS: Dict[str, Any] = {"parse": []}

# (attribute_name, singular_label, default_filename) for media upload iteration
_MEDIA_UPLOAD_CONFIG = [
    ("images", "image", "image.png"),
    ("files", "file", "file.bin"),
    ("videos", "video", "video.mp4"),
    ("audio", "audio", "audio.mp3"),
]


def build_status_embed(
    title: str,
    description: str,
    fields: List[Dict[str, Any]],
    color: int = EMBED_COLOR_PROCESSING,
) -> Dict[str, Any]:
    embed: Dict[str, Any] = {"title": title, "color": color}
    if description:
        embed["description"] = description
    if fields:
        embed["fields"] = fields
    return embed


async def _raise_for_status(resp: aiohttp.ClientResponse, operation: str) -> None:
    # Converts non-2xx responses into aiohttp.ClientResponseError with the
    # response body in the message — aiohttp's raise_for_status drops the body
    if resp.ok:
        return
    body = await resp.text()
    log_error(f"Failed to {operation} ({resp.status}): {body}")
    raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=resp.status, message=body)


def _webhook_url(application_id: str, interaction_token: str, *, original: bool = False) -> str:
    base = f"{DISCORD_API_BASE}/webhooks/{application_id}/{interaction_token}"
    return f"{base}/messages/@original" if original else base


async def edit_original_response(
    session: aiohttp.ClientSession,
    application_id: str,
    interaction_token: str,
    *,
    content: Optional[str] = None,
    embeds: Optional[List[Dict[str, Any]]] = None,
    components: Optional[List[Dict[str, Any]]] = None,
) -> None:
    payload: Dict[str, Any] = {"allowed_mentions": _SAFE_MENTIONS}
    if content is not None:
        payload["content"] = content
    if embeds is not None:
        payload["embeds"] = embeds
    if components is not None:
        payload["components"] = components
    async with session.patch(_webhook_url(application_id, interaction_token, original=True), json=payload) as resp:
        await _raise_for_status(resp, "edit original response")


async def send_followup_message(
    session: aiohttp.ClientSession,
    application_id: str,
    interaction_token: str,
    *,
    content: Optional[str] = None,
    embeds: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    payload: Dict[str, Any] = {"allowed_mentions": _SAFE_MENTIONS}
    if content is not None:
        payload["content"] = content
    if embeds is not None:
        payload["embeds"] = embeds
    async with session.post(_webhook_url(application_id, interaction_token), json=payload) as resp:
        await _raise_for_status(resp, "send followup")
        data = await resp.json()
        return data.get("id")


async def upload_webhook_file(
    session: aiohttp.ClientSession,
    application_id: str,
    interaction_token: str,
    content_bytes: bytes,
    filename: str,
) -> None:
    form = aiohttp.FormData()
    form.add_field(
        "payload_json",
        json.dumps({"content": "", "allowed_mentions": _SAFE_MENTIONS}),
        content_type="application/json",
    )
    form.add_field("files[0]", content_bytes, filename=filename)
    async with session.post(_webhook_url(application_id, interaction_token), data=form) as resp:
        await _raise_for_status(resp, "upload file")


async def download_attachment(
    session: aiohttp.ClientSession,
    url: str,
    max_size: int = _MAX_ATTACHMENT_BYTES,
) -> Optional[bytes]:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            # Fast check via Content-Length header when available
            if (resp.content_length or 0) > max_size:
                log_warning(f"Attachment too large ({resp.content_length} bytes), skipping")
                return None
            # Safety net: Content-Length header may lie or be missing
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.content.iter_chunked(64 * 1024):
                total += len(chunk)
                if total > max_size:
                    log_warning(f"Attachment exceeded max size during download ({total} bytes)")
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
    except Exception as e:
        log_error(f"Failed to download attachment: {e}")
        return None


async def _download_single_attachment(
    session: aiohttp.ClientSession,
    attachment: dict,
) -> Tuple[Optional[bytes], str, str]:
    url = attachment.get("url")
    if not url:
        return None, "", ""
    # Fast-path reject using Discord metadata before opening the connection
    size = attachment.get("size", 0)
    if size > _MAX_ATTACHMENT_BYTES:
        log_warning(f"Attachment too large ({size} bytes), skipping: {attachment.get('filename')}")
        return None, "", ""
    content_bytes = await download_attachment(session, url)
    return content_bytes, attachment.get("content_type", "application/octet-stream"), attachment.get("filename", "file")


async def download_resolved_attachments(
    session: aiohttp.ClientSession,
    data: dict,
) -> Dict[str, Any]:
    resolved = data.get("data", {}).get("resolved", {}).get("attachments", {})
    if not resolved:
        return {}

    results = await asyncio.gather(
        *[_download_single_attachment(session, att) for att in resolved.values()],
        return_exceptions=True,
    )

    images: List[Image] = []
    audio_list: List[Audio] = []
    videos: List[Video] = []
    files: List[File] = []

    for result in results:
        if isinstance(result, BaseException):
            log_error(f"Attachment download failed: {result}")
            continue
        content_bytes, content_type, filename = result
        if not content_bytes:
            continue
        if content_type.startswith("image/"):
            images.append(Image(content=content_bytes))
        elif content_type.startswith("audio/"):
            audio_list.append(Audio(content=content_bytes))
        elif content_type.startswith("video/"):
            videos.append(Video(content=content_bytes))
        else:
            files.append(File(content=content_bytes, filename=filename))

    media: Dict[str, Any] = {}
    if images:
        media["images"] = images
    if audio_list:
        media["audio"] = audio_list
    if videos:
        media["videos"] = videos
    if files:
        media["files"] = files
    return media


def extract_interaction_options(data: dict) -> str:
    options = data.get("data", {}).get("options", [])
    for opt in options:
        if opt.get("name") == "message":
            return opt.get("value", "")
    return ""


def extract_user_id(data: dict) -> str:
    member = data.get("member")
    if member:
        return member.get("user", {}).get("id", "")
    return data.get("user", {}).get("id", "")


async def send_response_media(
    session: aiohttp.ClientSession,
    application_id: str,
    interaction_token: str,
    response: Any,
) -> None:
    for attr, label, default_name in _MEDIA_UPLOAD_CONFIG:
        for item in getattr(response, attr, None) or []:
            # aget_content_bytes is async so URL/file-backed media don't block
            # the event loop during the load (items with inline bytes return fast)
            content_bytes = await item.aget_content_bytes()
            if not content_bytes:
                continue
            filename = getattr(item, "filename", None) or default_name
            try:
                await upload_webhook_file(session, application_id, interaction_token, content_bytes, filename)
            except Exception as e:
                log_error(f"Failed to upload {label}: {e}")


def extract_user_name(data: Dict[str, Any]) -> str:
    # Guild interactions nest the user under member.user; DMs put it at the top
    # level. Prefer the display name (global_name), fall back to username then id.
    member = data.get("member")
    candidates: List[Optional[Dict[str, Any]]] = [
        member.get("user") if isinstance(member, dict) else None,
        data.get("user"),
    ]
    for user in candidates:
        if not isinstance(user, dict):
            continue
        name = user.get("global_name") or user.get("username") or user.get("id")
        if name:
            return str(name)
    return "user"


def format_attribution(user_name: str, message: str, max_len: int = 2000) -> str:
    # Ellipsis-trim so attribution reads as a quote, not a mid-word cliff
    prefix = f"{user_name}: "
    remaining = max_len - len(prefix)
    if remaining <= 0:
        # Pathological: user name alone overflows the cap
        return f"{prefix}{message}"[:max_len]
    if len(message) > remaining:
        message = message[: remaining - 1].rstrip() + "…"
    return f"{prefix}{message}"


def format_thread_name(text: str, max_len: int = 100) -> str:
    # Collapse whitespace so thread names display cleanly; empty → "Conversation"
    name = " ".join(text.split()).strip() or "Conversation"
    return name[:max_len]


async def get_original_message_id(
    session: aiohttp.ClientSession,
    application_id: str,
    interaction_token: str,
) -> Optional[str]:
    url = f"{DISCORD_API_BASE}/webhooks/{application_id}/{interaction_token}/messages/@original"
    async with session.get(url) as resp:
        if resp.ok:
            data = await resp.json()
            return data.get("id")
        return None


async def create_message_thread(
    session: aiohttp.ClientSession,
    channel_id: str,
    message_id: str,
    name: str,
    bot_token: str,
) -> Optional[str]:
    # 60 = Discord's shortest auto-archive window (1h); threads created for
    # single-turn Q&A don't need longer retention since the conversation
    # completes within seconds
    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/threads"
    payload = {"name": name[:_THREAD_NAME_MAX], "auto_archive_duration": _THREAD_AUTO_ARCHIVE_MINUTES}
    async with session.post(url, json=payload, headers=bot_api_headers(bot_token)) as resp:
        if resp.ok:
            data = await resp.json()
            return data.get("id")
        return None
