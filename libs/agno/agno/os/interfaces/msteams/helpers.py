import os
import re
import time
from dataclasses import dataclass, field
from mimetypes import guess_type
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from agno.utils.log import log_error, log_info, log_warning

_LOGIN_BASE = "https://login.microsoftonline.com"
_BOT_SCOPE = "https://api.botframework.com/.default"

_TOKEN_EXPIRY_SKEW_SECONDS = 60


@dataclass
class MSTeamsConfig:
    app_id: str
    app_password: str
    tenant_id: str
    request_timeout: int = 30

    _cached_token: Optional[str] = field(default=None, repr=False)
    _token_expires_at: float = field(default=0.0, repr=False)

    @classmethod
    def init(
        cls,
        app_id: Optional[str] = None,
        app_password: Optional[str] = None,
        tenant_id: Optional[str] = None,
        request_timeout: int = 30,
    ) -> "MSTeamsConfig":
        """Resolve and validate credentials from args, then MICROSOFT_APP_* env vars."""
        from agno.os.interfaces.msteams.security import dev_bypass_enabled

        aid = (app_id or os.getenv("MICROSOFT_APP_ID") or "").strip()
        secret = (app_password or os.getenv("MICROSOFT_APP_PASSWORD") or "").strip()
        tid = (tenant_id or os.getenv("MICROSOFT_APP_TENANT_ID") or "").strip()

        # Both must be missing, not either: half-configured would leave app_id
        # empty, which the validator reads as "no credentials" and waves past.
        if dev_bypass_enabled() and not aid and not secret:
            log_warning("MICROSOFT_APP_SKIP_JWT_VALIDATION=true — Bot Framework JWT check disabled")
            return cls(app_id="", app_password="", tenant_id=tid, request_timeout=request_timeout)

        if not aid:
            raise ValueError("MICROSOFT_APP_ID is not set. Set the environment variable or pass app_id.")
        if not secret:
            raise ValueError("MICROSOFT_APP_PASSWORD is not set. Set the environment variable or pass app_password.")
        if not tid:
            raise ValueError("MICROSOFT_APP_TENANT_ID is not set. Set the environment variable or pass tenant_id.")

        return cls(
            app_id=aid,
            app_password=secret,
            tenant_id=tid,
            request_timeout=request_timeout,
        )

    def token_url(self) -> str:
        return f"{_LOGIN_BASE}/{self.tenant_id}/oauth2/v2.0/token"


async def _get_bot_token(config: MSTeamsConfig) -> str:
    if not config.app_id and not config.app_password:
        return ""
    now = time.time()
    if config._cached_token and config._token_expires_at - _TOKEN_EXPIRY_SKEW_SECONDS > now:
        return config._cached_token

    data = {
        "grant_type": "client_credentials",
        "client_id": config.app_id,
        "client_secret": config.app_password,
        "scope": _BOT_SCOPE,
    }

    async with httpx.AsyncClient(timeout=config.request_timeout) as client:
        resp = await client.post(config.token_url(), data=data)
        resp.raise_for_status()
        payload = resp.json()

    token = payload.get("access_token")
    if not token:
        raise RuntimeError(f"Bot Framework token response missing access_token: {payload}")

    config._cached_token = token
    config._token_expires_at = now + int(payload.get("expires_in", 3600))
    return token


@dataclass
class ActivityContent:
    text: str

    image_attachments: List[dict] = field(default_factory=list)
    file_attachments: List[dict] = field(default_factory=list)


_MENTION_TAG_RE = re.compile(r"<at>(.*?)</at>", flags=re.IGNORECASE | re.DOTALL)


def _clean_mention_text(
    text: Optional[str], recipient: Optional[dict] = None, entities: Optional[List[dict]] = None
) -> str:
    if not text:
        return ""
    if recipient and recipient.get("id") and recipient.get("name"):
        for entity in entities or []:
            if (
                entity.get("type") == "mention"
                and (entity.get("mentioned") or {}).get("id") == recipient["id"]
                and entity.get("text")
            ):
                text = text.replace(entity["text"], recipient["name"])
    return _MENTION_TAG_RE.sub(r"@\1", text).strip()


def extract_activity_content(activity: dict) -> Optional[ActivityContent]:
    """Returns None for a non-message activity, or a message with neither text
    nor attachments."""
    activity_type = activity.get("type")
    if activity_type != "message":
        log_info(f"Ignoring non-message activity type: {activity_type}")
        return None

    text = _clean_mention_text(activity.get("text"), activity.get("recipient"), activity.get("entities"))

    image_atts: List[dict] = []
    file_atts: List[dict] = []
    for att in activity.get("attachments", []) or []:
        content_type = (att.get("contentType") or "").lower()
        # Teams sends inline images as image/* attachments; files come through
        # as 'application/vnd.microsoft.teams.file.download.info' or similar
        if content_type.startswith("image/"):
            image_atts.append(att)
        # Ask the same resolver the download will use. Gating on contentUrl alone
        # would drop an attachment carrying only content.downloadUrl before
        # anything could report it -- and that field is the one Teams prefers.
        elif _attachment_download_url(att):
            file_atts.append(att)

    if not text and not image_atts and not file_atts:
        return None

    return ActivityContent(text=text, image_attachments=image_atts, file_attachments=file_atts)


def _attachment_download_url(att: dict) -> Optional[str]:
    """Prefer ``content.downloadUrl``: ``contentUrl`` points at SharePoint, which
    wants user credentials and answers the bot token with a login page."""
    content = att.get("content")
    if isinstance(content, dict) and content.get("downloadUrl"):
        return content["downloadUrl"]
    return att.get("contentUrl")


class _AttachmentTooLarge(ValueError):
    pass


# Archives are not readable model inputs; do not lose the accompanying text.
_ARCHIVE_MIME_TYPES = {"application/zip", "application/x-zip-compressed", "application/x-zip"}


async def _download_attachment(
    url: str,
    config: MSTeamsConfig,
    use_bot_token: bool = False,
    max_file_size: int = 1_073_741_824,
    name: str = "image",
) -> Tuple[Optional[bytes], Optional[str]]:
    headers: Dict[str, str] = {}
    if use_bot_token:
        try:
            token = await _get_bot_token(config)
            if token:
                headers["Authorization"] = f"Bearer {token}"
        except Exception as e:
            status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
            log_warning(f"Attachment token failed: {name}, status={status}, {type(e).__name__}")

    try:
        async with httpx.AsyncClient(timeout=config.request_timeout) as client:
            async with client.stream("GET", url, headers=headers, follow_redirects=True) as resp:
                resp.raise_for_status()
                length = resp.headers.get("content-length", "")
                if length.isdigit() and int(length) > max_file_size:
                    raise _AttachmentTooLarge
                content = bytearray()
                async for chunk in resp.aiter_bytes():
                    if len(content) + len(chunk) > max_file_size:
                        raise _AttachmentTooLarge
                    content.extend(chunk)
                mime = resp.headers.get("content-type", "").split(";")[0].strip().lower() or None
                return bytes(content), mime
    except httpx.HTTPError as e:
        status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
        log_warning(f"Attachment download failed: {name}, status={status}, {type(e).__name__}")
        return None, None


async def download_attachments_async(
    parsed: ActivityContent,
    config: MSTeamsConfig,
    service_url: Optional[str] = None,
    max_file_size: int = 1_073_741_824,
) -> Tuple[dict, List[str]]:
    """Returns (run_kwargs, skipped_labels); run_kwargs splats into ``entity.arun``."""
    from agno.media import File, Image

    run_kwargs: dict = {}
    skipped: List[str] = []

    images: List[Image] = []
    for att in parsed.image_attachments:
        url = _attachment_download_url(att)
        if not url:
            # Reported, not dropped: to the user an attachment with no url is the
            # same loss as one whose download failed, which is already reported.
            skipped.append("image")
            continue
        content_info = att.get("content")
        preauthorized = isinstance(content_info, dict) and bool(content_info.get("downloadUrl"))
        use_token = bool(service_url and urlparse(url).hostname == urlparse(service_url).hostname and not preauthorized)
        try:
            content, mime = await _download_attachment(
                url, config, use_bot_token=use_token, max_file_size=max_file_size, name=att.get("name") or "image"
            )
        except _AttachmentTooLarge:
            skipped.append(f"{att.get('name') or 'image'} (too large)")
            continue
        if not content:
            skipped.append("image")
            continue
        # The activity's own contentType first, not the download's: it is what
        # classified this attachment as an image, while Teams serves its
        # attachment CDN as application/octet-stream, which the model rejects.
        declared = (att.get("contentType") or "").lower()
        images.append(Image(content=content, mime_type=declared or mime or "image/png"))

    files: List[File] = []
    for att in parsed.file_attachments:
        name = att.get("name")
        url = _attachment_download_url(att)
        if not url:
            skipped.append(name or "file")
            continue
        content_info = att.get("content")
        preauthorized = isinstance(content_info, dict) and bool(content_info.get("downloadUrl"))
        use_token = bool(service_url and urlparse(url).hostname == urlparse(service_url).hostname and not preauthorized)
        try:
            content, mime = await _download_attachment(
                url, config, use_bot_token=use_token, max_file_size=max_file_size, name=name or "file"
            )
        except _AttachmentTooLarge:
            skipped.append(f"{name or 'file'} (too large)")
            continue
        if not content:
            skipped.append(name or "file")
            continue
        # Resolve the type the way the model would, then decide. Forwarding an
        # unsupported file with mime_type=None does not hide it -- the model falls
        # back to guessing from the filename and the provider rejects the run,
        # costing the user their message text as well as the attachment.
        resolved_mime = guess_type(name or "")[0] if not mime or mime == "application/octet-stream" else mime
        # An image uploaded from the paperclip arrives here rather than above:
        # Teams marks it as a file attachment, and only a pasted image carries an
        # image/* contentType. File's allowlist holds no image types at all, so
        # measuring one against it would drop the photo as unreadable.
        if (resolved_mime or "").startswith("image/"):
            images.append(Image(content=content, mime_type=resolved_mime))
            continue
        if resolved_mime in _ARCHIVE_MIME_TYPES or resolved_mime not in File.valid_mime_types():
            skipped.append(name or "file")
            continue
        files.append(File(content=content, mime_type=resolved_mime, filename=name))

    if images:
        run_kwargs["images"] = images
    if files:
        run_kwargs["files"] = files

    return run_kwargs, skipped


_CONVERSATION_REF_KEY = "msteams_conversation_ref"


def build_conversation_ref(service_url: str, conversation_id: str, bot_identity: Optional[dict]) -> dict:
    return {
        "service_url": service_url,
        "conversation_id": conversation_id,
        "bot_identity": bot_identity,
    }


def extract_conversation_ref(session_data: Optional[dict]) -> Optional[dict]:
    if not session_data:
        return None
    ref = session_data.get(_CONVERSATION_REF_KEY)
    if not isinstance(ref, dict):
        return None
    if not ref.get("service_url") or not ref.get("conversation_id"):
        return None
    return ref


def merge_conversation_ref(session_data: Optional[dict], ref: dict) -> dict:
    """Merge the ref into a copy, preserving every other key already stored."""
    merged = dict(session_data) if session_data else {}
    merged[_CONVERSATION_REF_KEY] = ref
    return merged


def _reply_endpoint(service_url: str, conversation_id: str, activity_id: Optional[str] = None) -> str:
    base = service_url.rstrip("/")
    if activity_id:
        return f"{base}/v3/conversations/{conversation_id}/activities/{activity_id}"
    return f"{base}/v3/conversations/{conversation_id}/activities"


async def _post_activity(
    service_url: str,
    conversation_id: str,
    activity: dict,
    config: MSTeamsConfig,
    reply_to_activity_id: Optional[str] = None,
) -> Optional[dict]:
    headers = {"Content-Type": "application/json"}
    if config.app_id:
        token = await _get_bot_token(config)
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=config.request_timeout) as client:
            resp = await client.post(
                _reply_endpoint(service_url, conversation_id, reply_to_activity_id),
                headers=headers,
                json=activity,
            )
            resp.raise_for_status()
            try:
                return resp.json()
            except Exception:
                return None
    except httpx.HTTPStatusError as e:
        log_error(f"Bot Connector rejected activity: {e.response.status_code} {e.response.text}")
        raise
    except Exception as e:
        log_error(f"Unexpected error posting activity: {str(e)}")
        raise


async def typing_indicator_async(
    service_url: str,
    conversation_id: str,
    config: MSTeamsConfig,
    reply_to_activity_id: Optional[str] = None,
    bot_identity: Optional[dict] = None,
) -> None:
    activity: dict = {"type": "typing"}
    if reply_to_activity_id:
        activity["replyToId"] = reply_to_activity_id
    if bot_identity:
        activity["from"] = bot_identity
    try:
        await _post_activity(service_url, conversation_id, activity, config, reply_to_activity_id)
    except Exception as e:
        log_warning(f"Typing indicator failed (non-fatal): {str(e)}")


async def send_teams_message_async(
    service_url: str,
    conversation_id: str,
    message: Any,
    config: MSTeamsConfig,
    reply_to_activity_id: Optional[str] = None,
    italics: bool = False,
    bot_identity: Optional[dict] = None,
) -> None:
    """Post a markdown message, serialising a pydantic model if given one.

    Empty payloads are skipped: the Bot Connector rejects them. ``bot_identity``
    becomes the outbound ``from``, and omitting it is not a safe degradation --
    the Connector answers a proactive send with no ``from`` as
    ``400 MissingProperty: The 'Activity.From' field is required`` (measured
    against Web Chat). This is why the conversation reference persists it.
    """
    if message is not None and not isinstance(message, str):
        from pydantic import BaseModel

        message = message.model_dump_json(indent=2) if isinstance(message, BaseModel) else str(message)
    if not message or not message.strip():
        return

    if italics:
        # Two trailing spaces before each newline. The activity is sent as
        # markdown, which renders a lone newline as a space, so joining on "\n"
        # collapses the reasoning steps into one run-on paragraph.
        message = "  \n".join([f"_{line}_" for line in message.split("\n")])

    activity: dict = {
        "type": "message",
        "text": message,
        "textFormat": "markdown",
    }
    if reply_to_activity_id:
        activity["replyToId"] = reply_to_activity_id

    if bot_identity:
        activity["from"] = bot_identity

    await _post_activity(service_url, conversation_id, activity, config, reply_to_activity_id)
