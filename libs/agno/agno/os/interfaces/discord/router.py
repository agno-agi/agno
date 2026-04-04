from os import getenv
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agno.agent import Agent, RemoteAgent
from agno.media import Audio, File, Image, Video
from agno.os.interfaces.discord.processing import MAX_ATTACHMENT_BYTES, run_entity, run_entity_stream
from agno.os.interfaces.discord.security import verify_discord_signature
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error, log_warning
from agno.workflow import RemoteWorkflow, Workflow

try:
    import aiohttp
except ImportError:
    raise ImportError("Discord interface requires `aiohttp`. Install using `pip install agno[discord]`")

DISCORD_API_BASE = "https://discord.com/api/v10"

# Discord Interaction Types
INTERACTION_PING = 1
INTERACTION_APPLICATION_COMMAND = 2
# Discord Interaction Response Types
RESPONSE_PONG = 1
RESPONSE_CHANNEL_MESSAGE_WITH_SOURCE = 4
RESPONSE_DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE = 5


class DiscordPongResponse(BaseModel):
    type: int = Field(default=RESPONSE_PONG, description="Interaction response type (PONG)")


class DiscordDeferredResponse(BaseModel):
    type: int = Field(
        default=RESPONSE_DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE,
        description="Interaction response type (deferred channel message)",
    )


# --- Session ID scheme ---
# Session IDs use a "dc:" prefix to namespace Discord sessions.
# Format variants:
#   dc:dm:{channel_id}                      — Direct messages (no guild)
#   dc:thread:{channel_id}                  — Thread channels (types 10, 11, 12)
#   dc:channel:{channel_id}:user:{user_id}  — Guild channels (scoped per user)


def _extract_user_id(data: dict) -> str:
    member = data.get("member")
    if member:
        return member.get("user", {}).get("id", "")
    user = data.get("user", {})
    return user.get("id", "")


def _build_session_id(data: dict) -> str:
    channel_id = data.get("channel_id", "")
    guild_id = data.get("guild_id")
    user_id = _extract_user_id(data)

    # DM — no guild
    if not guild_id:
        return f"dc:dm:{channel_id}"

    # Check if this is a thread (channel object may be absent in some interaction payloads)
    channel = data.get("channel")
    if channel:
        channel_type = channel.get("type")
        # Thread types: PUBLIC_THREAD=11, PRIVATE_THREAD=12, ANNOUNCEMENT_THREAD=10
        if channel_type in (10, 11, 12):
            return f"dc:thread:{channel_id}"

    # Regular guild channel — scope per user
    return f"dc:channel:{channel_id}:user:{user_id}"


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    stream: bool = False,
    show_reasoning: bool = True,
    max_message_chars: int = 1900,
    allowed_guild_ids: Optional[List[str]] = None,
    allowed_channel_ids: Optional[List[str]] = None,
) -> APIRouter:
    entity_type = "agent" if agent else "team" if team else "workflow" if workflow else "unknown"

    # Lazy-initialized aiohttp session, shared across all webhook calls within the
    # router's lifetime.  Created on first use because attach_routes() runs at import
    # time (sync), before any event loop exists.
    _http_session: Optional[aiohttp.ClientSession] = None

    async def _get_session() -> aiohttp.ClientSession:
        nonlocal _http_session
        if _http_session is None or _http_session.closed:
            _http_session = aiohttp.ClientSession()
        return _http_session

    # --- Webhook I/O helpers ---

    async def _edit_original(
        application_id: str,
        interaction_token: str,
        content: str,
    ) -> None:
        session = await _get_session()
        url = f"{DISCORD_API_BASE}/webhooks/{application_id}/{interaction_token}/messages/@original"
        payload: Dict[str, Any] = {"content": content}
        async with session.patch(url, json=payload) as resp:
            resp.raise_for_status()

    async def _send_webhook(
        application_id: str,
        interaction_token: str,
        content: str,
    ) -> None:
        session = await _get_session()
        url = f"{DISCORD_API_BASE}/webhooks/{application_id}/{interaction_token}"
        payload: Dict[str, Any] = {"content": content}
        async with session.post(url, json=payload) as resp:
            resp.raise_for_status()

    async def _download_bytes(url: str, max_size: int = MAX_ATTACHMENT_BYTES) -> Optional[bytes]:
        session = await _get_session()
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                resp.raise_for_status()
                content_length = resp.content_length or 0
                if content_length > max_size:
                    log_warning(f"Attachment too large ({content_length} bytes), skipping")
                    return None
                # Read in chunks to handle chunked transfers where content_length is 0/None
                chunks = []
                total = 0
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    if total > max_size:
                        log_warning(f"Attachment exceeded max size during download ({total} bytes), aborting")
                        return None
                    chunks.append(chunk)
                return b"".join(chunks)
        except Exception as e:
            log_error(f"Failed to download attachment: {e}")
            return None

    async def _upload_webhook_file(
        application_id: str,
        interaction_token: str,
        filename: str,
        content_bytes: bytes,
    ) -> None:
        session = await _get_session()
        url = f"{DISCORD_API_BASE}/webhooks/{application_id}/{interaction_token}"
        form = aiohttp.FormData()
        form.add_field("payload_json", '{"content": ""}', content_type="application/json")
        form.add_field("files[0]", content_bytes, filename=filename)
        async with session.post(url, data=form) as resp:
            resp.raise_for_status()

    # --- WebhookReplier ---
    # Nested inside attach_routes() so it captures the closure over _edit_original,
    # _send_webhook, and _upload_webhook_file (which themselves share _http_session).

    class WebhookReplier:
        """Replier implementation for Discord HTTP Interactions (webhook-based).

        Uses Discord's interaction webhook endpoints to deliver responses.  The
        interaction token is valid for **15 minutes** from the initial interaction
        — all messages (including follow-ups and media uploads) must complete
        within that window.
        """

        def __init__(self, application_id: str, interaction_token: str):
            self._app_id = application_id
            self._token = interaction_token

        async def send_initial_response(self, text: str) -> None:
            await _edit_original(self._app_id, self._token, text)

        async def edit_response(self, text: str) -> None:
            await _edit_original(self._app_id, self._token, text)

        async def send_followup(self, text: str) -> None:
            await _send_webhook(self._app_id, self._token, text)

        async def send_media(self, content: bytes, filename: str) -> None:
            await _upload_webhook_file(self._app_id, self._token, filename, content)

    # --- Route handler ---

    @router.post(
        "/interactions",
        operation_id=f"discord_interactions_{entity_type}",
        name="discord_interactions",
        description="Process incoming Discord interactions",
        response_model=Union[DiscordPongResponse, DiscordDeferredResponse],
        response_model_exclude_none=True,
        responses={
            200: {"description": "Interaction processed"},
            400: {"description": "Missing signature headers"},
            403: {"description": "Invalid signature"},
        },
    )
    async def discord_interactions(request: Request, background_tasks: BackgroundTasks):
        body = await request.body()
        signature = request.headers.get("X-Signature-Ed25519", "")
        timestamp = request.headers.get("X-Signature-Timestamp", "")

        if not signature or not timestamp:
            raise HTTPException(status_code=400, detail="Missing signature headers")

        if not verify_discord_signature(body, timestamp, signature):
            raise HTTPException(status_code=403, detail="Invalid signature")

        data = await request.json()
        interaction_type = data.get("type")

        # PING — Discord verification handshake
        if interaction_type == INTERACTION_PING:
            return JSONResponse(content={"type": RESPONSE_PONG})

        # Check guild/channel allowlists
        guild_id = data.get("guild_id")
        channel_id = data.get("channel_id")

        if allowed_guild_ids and guild_id not in allowed_guild_ids:
            return JSONResponse(
                content={
                    "type": RESPONSE_CHANNEL_MESSAGE_WITH_SOURCE,
                    "data": {"content": "This bot is not enabled in this server.", "flags": 64},
                }
            )

        if allowed_channel_ids and channel_id not in allowed_channel_ids:
            return JSONResponse(
                content={
                    "type": RESPONSE_CHANNEL_MESSAGE_WITH_SOURCE,
                    "data": {"content": "This bot is not enabled in this channel.", "flags": 64},
                }
            )

        # APPLICATION_COMMAND — Slash command
        if interaction_type == INTERACTION_APPLICATION_COMMAND:
            application_id = data.get("application_id") or getenv("DISCORD_APPLICATION_ID") or ""
            interaction_token = data.get("token", "")

            background_tasks.add_task(
                _process_command,
                data=data,
                application_id=application_id,
                interaction_token=interaction_token,
            )

            return JSONResponse(content={"type": RESPONSE_DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE})

        # Unhandled interaction type
        log_warning(f"Unhandled Discord interaction type: {interaction_type}")
        return JSONResponse(
            status_code=400,
            content={"error": f"Unhandled interaction type: {interaction_type}"},
        )

    # --- Background processing ---

    # Runs as a FastAPI BackgroundTask after the 3s deferred ACK.  Extracts options
    # from the slash command payload, downloads attachments, and delegates to run_entity().
    async def _process_command(data: dict, application_id: str, interaction_token: str):
        try:
            command_data = data.get("data", {})
            options = command_data.get("options", [])

            # Extract message text from the "message" option
            message_text = ""
            attachment_id = None
            for opt in options:
                if opt.get("name") == "message":
                    message_text = opt.get("value", "")
                elif opt.get("name") == "file":
                    attachment_id = opt.get("value")

            if not message_text:
                await _edit_original(application_id, interaction_token, "Please provide a message.")
                return

            user_id = _extract_user_id(data)
            session_id = _build_session_id(data)

            # Resolve attachments
            images: List[Image] = []
            files: List[File] = []
            audio_list: List[Audio] = []
            videos: List[Video] = []

            if attachment_id:
                resolved = data.get("data", {}).get("resolved", {}).get("attachments", {})
                attachment = resolved.get(str(attachment_id), {})
                if attachment:
                    await _download_attachment(attachment, images, files, audio_list, videos)

            # Delegate to shared processing via WebhookReplier
            entity = agent or team or workflow
            replier = WebhookReplier(
                application_id=application_id,
                interaction_token=interaction_token,
            )

            # Streaming is only supported for local Agent/Team (not Workflow or Remote entities)
            use_stream = stream and (agent or team) and not isinstance(entity, (RemoteAgent, RemoteTeam))

            if use_stream:
                await run_entity_stream(
                    entity=entity,  # type: ignore[arg-type]
                    message_text=message_text,
                    user_id=user_id,
                    session_id=session_id,
                    replier=replier,
                    show_reasoning=show_reasoning,
                    max_message_chars=max_message_chars,
                    images=images or None,
                    files=files or None,
                    audio=audio_list or None,
                    videos=videos or None,
                )
            else:
                await run_entity(
                    entity=entity,  # type: ignore[arg-type]
                    message_text=message_text,
                    user_id=user_id,
                    session_id=session_id,
                    replier=replier,
                    show_reasoning=show_reasoning,
                    max_message_chars=max_message_chars,
                    images=images or None,
                    files=files or None,
                    audio=audio_list or None,
                    videos=videos or None,
                )

        except Exception as e:
            log_error(f"Error processing Discord command: {e}")
            try:
                await _send_webhook(
                    application_id, interaction_token, "Sorry, there was an error processing your message."
                )
            except Exception:
                pass

    # --- Helper functions ---

    async def _download_attachment(
        attachment: dict,
        images: List[Image],
        files: List[File],
        audio_list: List[Audio],
        videos: List[Video],
    ):
        """Download a single Discord CDN attachment and sort it into the right media list.

        Discord CDN URLs are short-lived signed URLs.  Content-type from the
        attachment metadata is used to classify into image/video/audio/file
        categories, which map directly to the agno media types that models accept.
        """
        url = attachment.get("url")
        if not url:
            return
        content_type = attachment.get("content_type", "application/octet-stream")
        filename = attachment.get("filename", "file")
        size = attachment.get("size", 0)

        if size > MAX_ATTACHMENT_BYTES:
            log_warning(f"Attachment too large ({size} bytes), skipping: {filename}")
            return

        content_bytes = await _download_bytes(url)
        if not content_bytes:
            return

        if content_type.startswith("image/"):
            images.append(Image(content=content_bytes))
        elif content_type.startswith("video/"):
            videos.append(Video(content=content_bytes))
        elif content_type.startswith("audio/"):
            audio_list.append(Audio(content=content_bytes))
        else:
            files.append(File(content=content_bytes, filename=filename))

    async def _close_http_session() -> None:
        nonlocal _http_session
        if _http_session is not None and not _http_session.closed:
            await _http_session.close()
            _http_session = None

    router._close_http_session = _close_http_session  # type: ignore[attr-defined]

    return router
