from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from agno.media import Audio, File, Image, Video
from agno.utils.log import log_error, log_warning

DISCORD_API_BASE = "https://discord.com/api/v10"
DC_MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
DC_MAX_MESSAGE_CONTENT = 2000
DC_MAX_EMBED_DESC = 4096
# Leave room for [N/M] prefix on overflow
DC_CHUNK_SIZE = 3900

EMBED_COLOR_PROCESSING = 0x5865F2  # Discord blurple
EMBED_COLOR_COMPLETE = 0x57F287  # Green
EMBED_COLOR_ERROR = 0xED4245  # Red

_ERROR_MESSAGE = "Sorry, there was an error processing your message."

# Prevent model output from pinging @everyone/@here/roles
_SAFE_MENTIONS: Dict[str, Any] = {"parse": []}


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


async def patch_webhook_message(
    session: aiohttp.ClientSession,
    application_id: str,
    interaction_token: str,
    *,
    content: Optional[str] = None,
    embeds: Optional[List[Dict[str, Any]]] = None,
    components: Optional[List[Dict[str, Any]]] = None,
) -> None:
    url = f"{DISCORD_API_BASE}/webhooks/{application_id}/{interaction_token}/messages/@original"
    payload: Dict[str, Any] = {"allowed_mentions": _SAFE_MENTIONS}
    if content is not None:
        payload["content"] = content
    if embeds is not None:
        payload["embeds"] = embeds
    if components is not None:
        payload["components"] = components
    async with session.patch(url, json=payload) as resp:
        if not resp.ok:
            body = await resp.text()
            log_error(f"Failed to patch webhook message ({resp.status}): {body}")
            raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=resp.status, message=body)


async def post_followup_message(
    session: aiohttp.ClientSession,
    application_id: str,
    interaction_token: str,
    *,
    content: Optional[str] = None,
    embeds: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    url = f"{DISCORD_API_BASE}/webhooks/{application_id}/{interaction_token}"
    payload: Dict[str, Any] = {"allowed_mentions": _SAFE_MENTIONS}
    if content is not None:
        payload["content"] = content
    if embeds is not None:
        payload["embeds"] = embeds
    async with session.post(url, json=payload) as resp:
        if not resp.ok:
            body = await resp.text()
            log_error(f"Failed to post followup ({resp.status}): {body}")
            raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=resp.status, message=body)
        data = await resp.json()
        return data.get("id")


async def upload_webhook_file(
    session: aiohttp.ClientSession,
    application_id: str,
    interaction_token: str,
    content_bytes: bytes,
    filename: str,
) -> None:
    url = f"{DISCORD_API_BASE}/webhooks/{application_id}/{interaction_token}"
    form = aiohttp.FormData()
    form.add_field(
        "payload_json",
        json.dumps({"content": "", "allowed_mentions": _SAFE_MENTIONS}),
        content_type="application/json",
    )
    form.add_field("files[0]", content_bytes, filename=filename)
    async with session.post(url, data=form) as resp:
        if not resp.ok:
            body = await resp.text()
            log_error(f"Failed to upload file ({resp.status}): {body}")
            raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=resp.status, message=body)


async def download_attachment(
    session: aiohttp.ClientSession,
    url: str,
    max_size: int = DC_MAX_ATTACHMENT_BYTES,
) -> Optional[bytes]:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            if (resp.content_length or 0) > max_size:
                log_warning(f"Attachment too large ({resp.content_length} bytes), skipping")
                return None
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


async def _download_one(
    session: aiohttp.ClientSession,
    attachment: dict,
) -> Tuple[Optional[bytes], str, str]:
    url = attachment.get("url")
    if not url:
        return None, "", ""
    size = attachment.get("size", 0)
    if size > DC_MAX_ATTACHMENT_BYTES:
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
        *[_download_one(session, att) for att in resolved.values()],
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
    media_attrs = [
        ("images", "image.png"),
        ("files", "file"),
        ("videos", "video.mp4"),
        ("audio", "audio.mp3"),
    ]
    for attr, default_name in media_attrs:
        items = getattr(response, attr, None)
        if not items:
            continue
        for item in items:
            content_bytes = item.get_content_bytes()
            if not content_bytes:
                continue
            filename = getattr(item, "filename", None) or default_name
            try:
                await upload_webhook_file(session, application_id, interaction_token, content_bytes, filename)
            except Exception as e:
                log_error(f"Failed to upload {attr.rstrip('s')}: {e}")
