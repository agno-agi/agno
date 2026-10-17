"""Lark (Feishu) HTTP client and message helpers.

This module talks to the Lark Open Platform REST API directly via ``httpx`` —
no SDK dependency, mirroring the WhatsApp interface's lightweight approach.

The :class:`LarkClient` handles ``tenant_access_token`` acquisition and refresh
(2-hour lifetime, refreshed 5 minutes before expiry) so callers never touch
auth. All IM operations needed by the interface live here:

  * send / reply a message (text or interactive card)
  * PATCH a card in place (used for streaming)
  * download an inbound image/file/audio/video resource
  * upload an outbound image/file and send it

API reference: https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
from dataclasses import dataclass
from typing import Any, List, Optional

import httpx

from agno.utils.log import log_info, log_warning

# Default to the Feishu (飞书) domain; Lark international users pass domain="https://open.larksuite.com".
_DEFAULT_DOMAIN = "https://open.feishu.cn"
_API_BASE = "/open-apis"

# Refresh the tenant_access_token this far before its real expiry to avoid races.
_TOKEN_REFRESH_BUFFER_SECONDS = 300

# Lark message size limits.
_LARK_TEXT_MAX_BYTES = 150_000  # text message body cap
_LARK_CARD_MAX_BYTES = 30_000  # interactive card cap
# Chunk plain-text sends at this size to leave room for batch prefixes.
_TEXT_CHUNK_BYTES = 28_000


@dataclass
class LarkConfig:
    """Resolved Lark app credentials and settings.

    Created once by :func:`attach_routes` via :meth:`init` and shared with all
    helpers. Falls back to environment variables when constructor args are None.
    """

    app_id: str
    app_secret: str
    verification_token: Optional[str] = None
    encrypt_key: Optional[str] = None
    domain: str = _DEFAULT_DOMAIN
    media_timeout: int = 30

    @classmethod
    def init(
        cls,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        verification_token: Optional[str] = None,
        encrypt_key: Optional[str] = None,
        domain: Optional[str] = None,
        media_timeout: int = 30,
    ) -> "LarkConfig":
        aid = app_id or os.getenv("LARK_APP_ID")
        asec = app_secret or os.getenv("LARK_APP_SECRET")
        if not aid:
            raise ValueError("LARK_APP_ID is not set. Set the environment variable or pass app_id.")
        if not asec:
            raise ValueError("LARK_APP_SECRET is not set. Set the environment variable or pass app_secret.")
        return cls(
            app_id=aid,
            app_secret=asec,
            verification_token=verification_token or os.getenv("LARK_VERIFICATION_TOKEN"),
            encrypt_key=encrypt_key or os.getenv("LARK_ENCRYPT_KEY"),
            domain=domain or _DEFAULT_DOMAIN,
            media_timeout=media_timeout,
        )

    @property
    def base_url(self) -> str:
        return f"{self.domain}{_API_BASE}"


class LarkClient:
    """Async Lark Open API client with automatic token management.

    A single client is shared per interface instance. Token refresh is
    serialised with a lock so concurrent webhook handlers don't storm the token
    endpoint.
    """

    def __init__(self, config: LarkConfig) -> None:
        self.config = config
        self._tenant_access_token: Optional[str] = None
        # Wall-clock expiry time (seconds since epoch) at which the cached token must be refreshed.
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    async def _get_token(self) -> str:
        """Return a valid ``tenant_access_token``, refreshing if necessary."""
        # Fast path: cached and still valid (outside the refresh buffer).
        if self._tenant_access_token and asyncio.get_event_loop().time() < self._token_expires_at:
            return self._tenant_access_token

        async with self._token_lock:
            # Re-check inside the lock — another coroutine may have just refreshed.
            if self._tenant_access_token and asyncio.get_event_loop().time() < self._token_expires_at:
                return self._tenant_access_token

            url = f"{self.config.base_url}/auth/v3/tenant_access_token/internal"
            body = {"app_id": self.config.app_id, "app_secret": self.config.app_secret}
            async with httpx.AsyncClient(timeout=self.config.media_timeout, trust_env=False) as client:
                resp = await client.post(url, json=body)
                resp.raise_for_status()
                data = resp.json()

            if data.get("code") != 0:
                raise RuntimeError(f"Lark token request failed: {data.get('msg')} (code {data.get('code')})")

            self._tenant_access_token = data["tenant_access_token"]
            expire = int(data.get("expire", 7200))
            # Schedule refresh `buffer` seconds before the real expiry.
            self._token_expires_at = asyncio.get_event_loop().time() + max(expire - _TOKEN_REFRESH_BUFFER_SECONDS, 60)
            log_info("Refreshed Lark tenant_access_token")
            return self._tenant_access_token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        data: Optional[dict] = None,
        files: Optional[dict] = None,
        expect_json: bool = True,
    ) -> Any:
        """Authenticated request to the Lark Open API.

        Set ``expect_json=False`` for binary downloads (resource fetches).
        """
        token = await self._get_token()
        url = f"{self.config.base_url}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        if files is None:
            headers["Content-Type"] = "application/json; charset=utf-8"

        async with httpx.AsyncClient(timeout=self.config.media_timeout, trust_env=False) as client:
            resp = await client.request(
                method, url, params=params, json=json_body, data=data, files=files, headers=headers
            )
            resp.raise_for_status()
            if not expect_json:
                return resp.content
            payload = resp.json()

        code = payload.get("code")
        if code != 0:
            raise RuntimeError(f"Lark API {method} {path} failed: {payload.get('msg')} (code {code})")
        return payload.get("data")

    # ------------------------------------------------------------------ #
    # Send / reply / patch
    # ------------------------------------------------------------------ #

    async def send_message(
        self,
        receive_id: str,
        msg_type: str,
        content: str,
        receive_id_type: str = "chat_id",
    ) -> Optional[str]:
        """Send a message. Returns the new ``message_id`` (or ``None``)."""
        path = "/im/v1/messages"
        params = {"receive_id_type": receive_id_type}
        body = {"receive_id": receive_id, "msg_type": msg_type, "content": content}
        data = await self._request("POST", path, params=params, json_body=body)
        return data.get("message_id") if isinstance(data, dict) else None

    async def reply_message(
        self,
        message_id: str,
        msg_type: str,
        content: str,
    ) -> Optional[str]:
        """Reply to a specific message (threaded). Returns the new ``message_id``."""
        path = f"/im/v1/messages/{message_id}/reply"
        body = {"msg_type": msg_type, "content": content}
        data = await self._request("POST", path, json_body=body)
        return data.get("message_id") if isinstance(data, dict) else None

    async def patch_card(self, message_id: str, card_content: str) -> None:
        """Update an existing interactive card in place (streaming edits)."""
        path = f"/im/v1/messages/{message_id}"
        body = {"content": card_content}
        await self._request("PATCH", path, json_body=body)

    async def update_text(self, message_id: str, content: str) -> None:
        """Edit a previously sent text/post message (PUT)."""
        path = f"/im/v1/messages/{message_id}"
        body = {"msg_type": "text", "content": content}
        await self._request("PUT", path, json_body=body)

    # ------------------------------------------------------------------ #
    # Media
    # ------------------------------------------------------------------ #

    async def download_resource(self, message_id: str, file_key: str, resource_type: str) -> Optional[bytes]:
        """Download an inbound image/file/audio/video resource.

        ``resource_type`` is the ``type`` query param: ``image``, ``file``,
        ``audio``, ``video``, or ``media``.
        """
        path = f"/im/v1/messages/{message_id}/resources/{file_key}"
        params = {"type": resource_type}
        try:
            return await self._request("GET", path, params=params, expect_json=False)
        except httpx.HTTPError as e:
            log_warning(f"Failed to download Lark resource {file_key}: {e}")
            return None

    async def upload_image(self, image_bytes: bytes) -> Optional[str]:
        """Upload an image and return its ``image_key``."""
        path = "/im/v1/images"
        files = {"image": ("image", io.BytesIO(image_bytes), "application/octet-stream")}
        data = {"image_type": "message"}
        result = await self._request("POST", path, data=data, files=files)
        return result.get("image_key") if isinstance(result, dict) else None

    async def upload_file(self, file_bytes: bytes, filename: str) -> Optional[str]:
        """Upload a file and return its ``file_key``."""
        path = "/im/v1/files"
        files = {"file": (filename, io.BytesIO(file_bytes), "application/octet-stream")}
        data = {"file_type": "stream", "file_name": filename}
        result = await self._request("POST", path, data=data, files=files)
        return result.get("file_key") if isinstance(result, dict) else None

    # ------------------------------------------------------------------ #
    # Bot info
    # ------------------------------------------------------------------ #

    async def get_bot_open_id(self) -> Optional[str]:
        """Fetch the bot's own ``open_id`` (used for @mention detection in groups).

        This bypasses :meth:`_request` because ``/bot/v3/info`` returns ``bot``
        at the top level (not wrapped in ``data``).
        """
        try:
            token = await self._get_token()
            url = f"{self.config.base_url}/bot/v3/info"
            headers = {"Authorization": f"Bearer {token}"}
            async with httpx.AsyncClient(timeout=self.config.media_timeout, trust_env=False) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
            if payload.get("code") != 0:
                log_warning(f"Lark bot info failed: {payload.get('msg')}")
                return None
            bot = payload.get("bot", {})
            return bot.get("open_id") if isinstance(bot, dict) else None
        except Exception as e:
            log_warning(f"Failed to fetch Lark bot info: {e}")
            return None


# ---------------------------------------------------------------------- #
# Inbound message parsing
# ---------------------------------------------------------------------- #


@dataclass
class LarkMessagePayload:
    """Parsed inbound Lark message."""

    text: str = ""
    chat_id: str = ""
    chat_type: str = ""  # "p2p" or "group"
    message_id: str = ""
    message_type: str = ""
    sender_open_id: str = ""
    sender_user_id: str = ""
    # Raw mentions list; router uses this for @mention detection + stripping.
    mentions: List[dict] = None  # type: ignore[assignment]
    images: List[Any] = None  # type: ignore[assignment]
    audio: List[Any] = None  # type: ignore[assignment]
    videos: List[Any] = None  # type: ignore[assignment]
    files: List[Any] = None  # type: ignore[assignment]
    warning: Optional[str] = None

    def __post_init__(self) -> None:
        if self.mentions is None:
            self.mentions = []
        if self.images is None:
            self.images = []
        if self.audio is None:
            self.audio = []
        if self.videos is None:
            self.videos = []
        if self.files is None:
            self.files = []


def _extract_text_from_post(content: dict) -> str:
    """Flatten a Lark ``post`` (rich text) content dict into plain text.

    The ``post`` content is locale-keyed, e.g. ``{"zh_cn": {"title": ..., "content": [[{tag, text}, ...]]}}``.
    """
    parts: List[str] = []
    for locale_body in content.values():
        if not isinstance(locale_body, dict):
            continue
        title = locale_body.get("title")
        if title:
            parts.append(str(title))
        for paragraph in locale_body.get("content", []) or []:
            if not isinstance(paragraph, list):
                continue
            line_parts: List[str] = []
            for node in paragraph:
                if not isinstance(node, dict):
                    continue
                tag = node.get("tag")
                if tag == "text":
                    line_parts.append(str(node.get("text", "")))
                elif tag == "a":
                    line_parts.append(str(node.get("text", node.get("href", ""))))
                elif tag == "at":
                    # @mention inside rich text — keep the user_id placeholder so the
                    # router's mention-stripping logic still works.
                    line_parts.append(str(node.get("user_id", "")))
            if line_parts:
                parts.append("".join(line_parts))
    return "\n".join(parts)


async def extract_message_payload(event: dict, client: LarkClient) -> Optional[LarkMessagePayload]:
    """Parse a Lark ``im.message.receive_v1`` event into a :class:`LarkMessagePayload`.

    Downloads any inbound media and wraps it as agno ``Image``/``Audio``/``Video``/``File``
    objects. Returns ``None`` for unsupported message types.
    """
    from agno.media import Audio, File, Image, Video

    message = event.get("event", {}).get("message", {})
    sender = event.get("event", {}).get("sender", {}).get("sender_id", {})

    payload = LarkMessagePayload(
        chat_id=message.get("chat_id", ""),
        chat_type=message.get("chat_type", ""),
        message_id=message.get("message_id", ""),
        message_type=message.get("message_type", ""),
        sender_open_id=sender.get("open_id", ""),
        sender_user_id=sender.get("user_id", ""),
        mentions=message.get("mentions", []) or [],
    )

    msg_type = payload.message_type
    content_str = message.get("content", "{}")
    try:
        content = json.loads(content_str) if isinstance(content_str, str) else (content_str or {})
    except json.JSONDecodeError:
        content = {}

    if msg_type == "text":
        payload.text = content.get("text", "")
    elif msg_type == "post":
        payload.text = _extract_text_from_post(content)
    elif msg_type == "image":
        image_key = content.get("image_key")
        if image_key:
            data = await client.download_resource(payload.message_id, image_key, "image")
            if data:
                payload.images = [Image(content=data)]
    elif msg_type == "file":
        file_key = content.get("file_key")
        if file_key:
            data = await client.download_resource(payload.message_id, file_key, "file")
            if data:
                payload.files = [File(content=data, filename=content.get("file_name"))]
    elif msg_type == "audio":
        file_key = content.get("file_key")
        if file_key:
            data = await client.download_resource(payload.message_id, file_key, "audio")
            if data:
                payload.audio = [Audio(content=data)]
    elif msg_type == "video":
        file_key = content.get("file_key")
        if file_key:
            data = await client.download_resource(payload.message_id, file_key, "video")
            if data:
                payload.videos = [Video(content=data)]
    elif msg_type == "media":
        # Grouped media (file + name); treat as a file download.
        file_key = content.get("file_key")
        if file_key:
            data = await client.download_resource(payload.message_id, file_key, "media")
            if data:
                payload.files = [File(content=data, filename=content.get("file_name"))]
    else:
        log_warning(f"Unsupported Lark message type: {msg_type}")
        return None

    return payload


# ---------------------------------------------------------------------- #
# Outbound message helpers
# ---------------------------------------------------------------------- #


def format_message(text: Any) -> str:
    """Coerce an agent response to a plain string suitable for Lark.

    Lark markdown cards render standard markdown, so no syntax conversion is
    needed (unlike WhatsApp). We only collapse ``pydantic`` output_schema
    responses to JSON text.
    """
    if text is None:
        return ""
    if isinstance(text, str):
        return text
    from pydantic import BaseModel

    if isinstance(text, BaseModel):
        return text.model_dump_json(indent=2)
    return str(text)


def _text_content(text: str) -> str:
    """Build the JSON ``content`` string for a ``text`` message."""
    return json.dumps({"text": text}, ensure_ascii=False)


async def send_text_message(client: LarkClient, chat_id: str, text: Any) -> None:
    """Send a plain text message, chunking if it exceeds Lark's text limit."""
    message = format_message(text)
    if not message or not message.strip():
        return

    encoded = message.encode("utf-8")
    if len(encoded) <= _LARK_TEXT_MAX_BYTES:
        await client.send_message(chat_id, "text", _text_content(message))
        return

    # Chunk on a UTF-8 boundary to avoid splitting multi-byte characters.
    chunks: List[str] = []
    buf = io.BytesIO(encoded)
    while True:
        raw_chunk = buf.read(_TEXT_CHUNK_BYTES)
        if not raw_chunk:
            break
        chunks.append(raw_chunk.decode("utf-8", errors="ignore"))

    total = len(chunks)
    for i, chunk in enumerate(chunks, 1):
        batched = f"[{i}/{total}] {chunk}"
        await client.send_message(chat_id, "text", _text_content(batched))


async def send_response_media(client: LarkClient, response: Any, chat_id: str) -> bool:
    """Send any images/audio/videos/files attached to an agent response.

    Returns ``True`` if at least one media item was sent.
    """
    any_sent = False
    for attr, is_image in (
        ("images", True),
        ("videos", False),
        ("audio", False),
        ("files", False),
    ):
        items = getattr(response, attr, None) or []
        for item in items:
            try:
                raw_bytes = await item.aget_content_bytes()
            except Exception as e:
                log_warning(f"Could not read {attr} content for Lark: {e}")
                continue
            if not raw_bytes:
                log_warning(f"Empty content for Lark {attr}, skipping")
                continue

            if is_image:
                image_key = await client.upload_image(raw_bytes)
                if image_key:
                    content = json.dumps({"image_key": image_key}, ensure_ascii=False)
                    await client.send_message(chat_id, "image", content)
                    any_sent = True
            else:
                filename = getattr(item, "name", None) or getattr(item, "filename", None) or attr
                file_key = await client.upload_file(raw_bytes, filename)
                if file_key:
                    content = json.dumps({"file_key": file_key}, ensure_ascii=False)
                    await client.send_message(chat_id, "file", content)
                    any_sent = True
    return any_sent


def strip_mention_placeholders(text: str) -> str:
    """Remove ``@_user_N`` mention placeholders from message text.

    Lark delivers @mentions as ``@_user_1`` placeholders in the text content
    rather than the user's name. The router strips them before sending the
    text to the agent.
    """
    return re.sub(r"@_user_\d+", "", text).strip()


def is_bot_mentioned(mentions: List[dict], bot_open_id: Optional[str]) -> bool:
    """Return ``True`` if the bot itself is in the ``mentions`` list."""
    if not bot_open_id or not mentions:
        return False
    for mention in mentions:
        mention_id = mention.get("id", {}) if isinstance(mention, dict) else {}
        if mention_id.get("open_id") == bot_open_id:
            return True
    return False
