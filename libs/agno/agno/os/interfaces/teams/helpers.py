import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx

from agno.utils.log import log_error, log_info, log_warning

_BOT_CONNECTOR_BASE = "https://api.botframework.com"
_LOGIN_BASE = "https://login.microsoftonline.com"
_BOT_SCOPE = "https://api.botframework.com/.default"

_TOKEN_EXPIRY_SKEW_SECONDS = 60


@dataclass
class TeamsConfig:
    """Runtime configuration + cached bot access token for a single interface instance.

    Prefer :meth:`TeamsConfig.init` over constructing directly — it resolves
    values from ``MICROSOFT_APP_*`` env vars when constructor args are None.
    """

    app_id: str
    app_password: str
    tenant_id: str = "botframework.com"
    app_type: str = "MultiTenant"
    request_timeout: int = 30

    # Cached bot access token (populated by _get_bot_token)
    _cached_token: Optional[str] = field(default=None, repr=False)
    _token_expires_at: float = field(default=0.0, repr=False)

    @classmethod
    def init(
        cls,
        app_id: Optional[str] = None,
        app_password: Optional[str] = None,
        tenant_id: Optional[str] = None,
        app_type: Optional[str] = None,
        request_timeout: int = 30,
    ) -> "TeamsConfig":
        """Build a config using constructor args first, then env vars.

        Env-var fallbacks:
          - ``MICROSOFT_APP_ID`` / ``MICROSOFT_APP_PASSWORD`` — required
          - ``MICROSOFT_APP_TENANT_ID`` — defaults to ``botframework.com``
          - ``MICROSOFT_APP_TYPE`` — defaults to ``MultiTenant``

        Raises ``ValueError`` if ``app_id`` or ``app_password`` cannot be
        resolved from either source.
        """
        aid = app_id or os.getenv("MICROSOFT_APP_ID")
        secret = app_password or os.getenv("MICROSOFT_APP_PASSWORD")
        tid = tenant_id or os.getenv("MICROSOFT_APP_TENANT_ID") or "botframework.com"
        atype = app_type or os.getenv("MICROSOFT_APP_TYPE") or "MultiTenant"

        if not aid:
            raise ValueError("MICROSOFT_APP_ID is not set. Set the environment variable or pass app_id.")
        if not secret:
            raise ValueError("MICROSOFT_APP_PASSWORD is not set. Set the environment variable or pass app_password.")

        return cls(
            app_id=aid,
            app_password=secret,
            tenant_id=tid,
            app_type=atype,
            request_timeout=request_timeout,
        )

    def token_url(self) -> str:
        # 'botframework.com' is the multi-tenant issuer used by MultiTenant bots
        return f"{_LOGIN_BASE}/{self.tenant_id}/oauth2/v2.0/token"


async def _get_bot_token(config: TeamsConfig) -> str:
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
    """Normalised view of an inbound Teams Activity: cleaned text + split attachments."""

    text: str

    image_attachments: List[dict] = field(default_factory=list)
    file_attachments: List[dict] = field(default_factory=list)


_MENTION_TAG_RE = re.compile(r"<at>.*?</at>", flags=re.IGNORECASE | re.DOTALL)


def _clean_mention_text(text: str) -> str:
    if not text:
        return ""
    cleaned = _MENTION_TAG_RE.sub("", text)
    return cleaned.strip()


def extract_activity_content(activity: dict) -> Optional[ActivityContent]:
    """Parse an inbound Teams Activity into text + attachment refs.

    Returns None if the activity has no processable content (Teams sends many
    control activities that we don't reply to).
    """
    activity_type = activity.get("type")
    if activity_type != "message":
        log_info(f"Ignoring non-message activity type: {activity_type}")
        return None

    text = _clean_mention_text(activity.get("text", ""))

    image_atts: List[dict] = []
    file_atts: List[dict] = []
    for att in activity.get("attachments", []) or []:
        content_type = (att.get("contentType") or "").lower()
        # Teams sends inline images as image/* attachments; files come through
        # as 'application/vnd.microsoft.teams.file.download.info' or similar
        if content_type.startswith("image/"):
            image_atts.append(att)
        elif att.get("contentUrl"):
            file_atts.append(att)

    if not text and not image_atts and not file_atts:
        return None

    return ActivityContent(text=text, image_attachments=image_atts, file_attachments=file_atts)


async def _download_attachment(
    url: str, config: TeamsConfig, use_bot_token: bool = True
) -> Tuple[Optional[bytes], Optional[str]]:
    headers: Dict[str, str] = {}
    if use_bot_token:
        try:
            token = await _get_bot_token(config)
            headers["Authorization"] = f"Bearer {token}"
        except Exception as e:
            log_warning(f"Could not fetch bot token for attachment download: {e}")

    try:
        async with httpx.AsyncClient(timeout=config.request_timeout) as client:
            resp = await client.get(url, headers=headers, follow_redirects=True)
            resp.raise_for_status()
            mime = resp.headers.get("content-type", "").split(";")[0].strip() or None
            return resp.content, mime
    except httpx.HTTPError as e:
        log_warning(f"Attachment download failed for {url}: {e}")
        return None, None


async def download_attachments_async(parsed: ActivityContent, config: TeamsConfig) -> Tuple[dict, List[str]]:
    """Download attachment bytes and package them as Agno media objects.

    Returns (run_kwargs, skipped_labels). run_kwargs mirrors the WhatsApp helper —
    keys like 'images' / 'files' are ready to splat into `entity.arun(...)`.
    """
    from agno.media import File, Image

    run_kwargs: dict = {}
    skipped: List[str] = []

    images: List[Image] = []
    for att in parsed.image_attachments:
        url = att.get("contentUrl")
        if not url:
            continue
        content, mime = await _download_attachment(url, config)
        if not content:
            skipped.append("image")
            continue
        images.append(Image(content=content, mime_type=mime or "image/png"))
    if images:
        run_kwargs["images"] = images

    files: List[File] = []
    for att in parsed.file_attachments:
        url = att.get("contentUrl")
        if not url:
            continue
        content, mime = await _download_attachment(url, config)
        if not content:
            skipped.append("file")
            continue
        files.append(File(content=content, mime_type=mime or "application/octet-stream"))
    if files:
        run_kwargs["files"] = files

    return run_kwargs, skipped


_CONVERSATION_REF_KEY = "teams_conversation_ref"


def build_conversation_ref(service_url: str, conversation_id: str, bot_identity: Optional[dict]) -> dict:
    """Package the 3 fields needed to send a proactive message later."""
    return {
        "service_url": service_url,
        "conversation_id": conversation_id,
        "bot_identity": bot_identity,
    }


def extract_conversation_ref(session_data: Optional[dict]) -> Optional[dict]:
    """Inverse of build_conversation_ref — returns None if any field is missing."""
    if not session_data:
        return None
    ref = session_data.get(_CONVERSATION_REF_KEY)
    if not isinstance(ref, dict):
        return None
    if not ref.get("service_url") or not ref.get("conversation_id"):
        return None
    return ref


def merge_conversation_ref(session_data: Optional[dict], ref: dict) -> dict:
    """Return a new session_data dict with the conversation ref merged in.

    Preserves all other keys the caller may already be storing.
    """
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
    config: TeamsConfig,
    reply_to_activity_id: Optional[str] = None,
) -> Optional[dict]:
    token = await _get_bot_token(config)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

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
        log_error(f"Unexpected error posting activity: {e}")
        raise


async def typing_indicator_async(
    service_url: str,
    conversation_id: str,
    config: TeamsConfig,
    reply_to_activity_id: Optional[str] = None,
    bot_identity: Optional[dict] = None,
) -> None:
    """Send a `type: typing` activity so Teams shows the '... is typing' UI."""
    activity: dict = {"type": "typing"}
    if reply_to_activity_id:
        activity["replyToId"] = reply_to_activity_id
    if bot_identity:
        activity["from"] = bot_identity
    try:
        await _post_activity(service_url, conversation_id, activity, config, reply_to_activity_id)
    except Exception as e:
        log_warning(f"Typing indicator failed (non-fatal): {e}")


async def send_teams_message_async(
    service_url: str,
    conversation_id: str,
    message: Any,
    config: TeamsConfig,
    reply_to_activity_id: Optional[str] = None,
    italics: bool = False,
    bot_identity: Optional[dict] = None,
) -> None:
    """Post a text (markdown) message to a Teams conversation.

    ``message`` may be a string or a pydantic ``BaseModel`` — models are
    serialised via ``model_dump_json(indent=2)``. Empty / whitespace-only
    payloads are silently skipped (the Bot Connector rejects them).

    Pass ``reply_to_activity_id`` to thread the reply under an inbound
    activity, or leave it None for a top-level message (required for
    proactive alerts). ``bot_identity`` is the outbound ``from`` field
    that Bot Connector requires — usually the ``recipient`` echoed back
    from the inbound activity.
    """
    if message is not None and not isinstance(message, str):
        from pydantic import BaseModel

        message = message.model_dump_json(indent=2) if isinstance(message, BaseModel) else str(message)
    if not message or not message.strip():
        return

    if italics:
        message = "\n".join([f"_{line}_" for line in message.split("\n")])

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
