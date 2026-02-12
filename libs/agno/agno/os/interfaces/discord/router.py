import time
from os import getenv
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from agno.agent import Agent, RemoteAgent
from agno.media import Audio, File, Image, Video
from agno.os.interfaces.discord.security import verify_discord_signature
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error, log_warning
from agno.utils.message import get_text_from_message
from agno.workflow import RemoteWorkflow, Workflow

try:
    import aiohttp
except ImportError:
    raise ImportError("Discord interface requires `aiohttp`. Install using `pip install agno[discord]`")

DISCORD_API_BASE = "https://discord.com/api/v10"

# Discord Interaction Types
INTERACTION_PING = 1
INTERACTION_APPLICATION_COMMAND = 2
INTERACTION_MESSAGE_COMPONENT = 3
# Discord Interaction Response Types
RESPONSE_PONG = 1
RESPONSE_CHANNEL_MESSAGE_WITH_SOURCE = 4
RESPONSE_DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE = 5
RESPONSE_DEFERRED_UPDATE_MESSAGE = 6


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    show_reasoning: bool = True,
    max_message_chars: int = 1900,
    allowed_guild_ids: Optional[List[str]] = None,
    allowed_channel_ids: Optional[List[str]] = None,
) -> APIRouter:
    entity_type = "agent" if agent else "team" if team else "workflow" if workflow else "unknown"

    # Lazy aiohttp session for webhook operations
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
        components: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        session = await _get_session()
        url = f"{DISCORD_API_BASE}/webhooks/{application_id}/{interaction_token}/messages/@original"
        payload: Dict[str, Any] = {"content": content}
        if components is not None:
            payload["components"] = components
        async with session.patch(url, json=payload) as resp:
            resp.raise_for_status()

    async def _send_webhook(
        application_id: str,
        interaction_token: str,
        content: str,
        ephemeral: bool = False,
    ) -> None:
        session = await _get_session()
        url = f"{DISCORD_API_BASE}/webhooks/{application_id}/{interaction_token}"
        payload: Dict[str, Any] = {"content": content}
        if ephemeral:
            payload["flags"] = 64
        async with session.post(url, json=payload) as resp:
            resp.raise_for_status()

    async def _download_bytes(url: str, max_size: int = 25 * 1024 * 1024) -> Optional[bytes]:
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

    # --- Route handler ---

    @router.post(
        "/interactions",
        operation_id=f"discord_interactions_{entity_type}",
        name="discord_interactions",
        description="Process incoming Discord interactions",
        responses={
            200: {"description": "Interaction processed"},
            401: {"description": "Invalid signature"},
        },
    )
    async def discord_interactions(request: Request, background_tasks: BackgroundTasks):
        body = await request.body()
        signature = request.headers.get("X-Signature-Ed25519", "")
        timestamp = request.headers.get("X-Signature-Timestamp", "")

        if not signature or not timestamp:
            raise HTTPException(status_code=401, detail="Missing signature headers")

        if not verify_discord_signature(body, timestamp, signature):
            raise HTTPException(status_code=401, detail="Invalid signature")

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

        # MESSAGE_COMPONENT — Button/select callbacks (HITL)
        if interaction_type == INTERACTION_MESSAGE_COMPONENT:
            application_id = data.get("application_id") or getenv("DISCORD_APPLICATION_ID") or ""
            interaction_token = data.get("token", "")
            custom_id = data.get("data", {}).get("custom_id", "")

            background_tasks.add_task(
                _process_component,
                custom_id=custom_id,
                application_id=application_id,
                interaction_token=interaction_token,
                user_id=_extract_user_id(data),
            )

            return JSONResponse(content={"type": RESPONSE_DEFERRED_UPDATE_MESSAGE})

        # Unhandled interaction type — return 400, not PONG (PONG is only valid for PING)
        log_warning(f"Unhandled Discord interaction type: {interaction_type}")
        return JSONResponse(
            status_code=400,
            content={"error": f"Unhandled interaction type: {interaction_type}"},
        )

    # --- Background processing ---

    # Store pending HITL runs keyed by run_id
    _pending_hitl: Dict[str, Any] = {}
    _hitl_ttl_seconds = 15 * 60  # Discord interaction tokens expire after 15 minutes

    def _cleanup_stale_hitl() -> None:
        now = time.time()
        stale_keys = [k for k, v in _pending_hitl.items() if now - v.get("created_at", 0) > _hitl_ttl_seconds]
        for k in stale_keys:
            del _pending_hitl[k]

    async def _process_command(data: dict, application_id: str, interaction_token: str):
        try:
            _cleanup_stale_hitl()
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
                await _send_followup(application_id, interaction_token, "Please provide a message.")
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

            # Run agent/team/workflow
            response = None
            if agent:
                response = await agent.arun(
                    message_text,
                    user_id=user_id,
                    session_id=session_id,
                    images=images or None,
                    files=files or None,
                    audio=audio_list or None,
                    videos=videos or None,
                )
            elif team:
                response = await team.arun(  # type: ignore
                    message_text,
                    user_id=user_id,
                    session_id=session_id,
                    images=images or None,
                    files=files or None,
                    audio=audio_list or None,
                    videos=videos or None,
                )
            elif workflow:
                response = await workflow.arun(  # type: ignore
                    message_text,
                    user_id=user_id,
                    session_id=session_id,
                    images=images or None,
                    files=files or None,
                    audio=audio_list or None,
                    videos=videos or None,
                )

            if not response:
                await _send_followup(application_id, interaction_token, "No response generated.")
                return

            if response.status == "ERROR":
                log_error(f"Error processing message: {response.content}")
                await _send_followup(
                    application_id, interaction_token, "Sorry, there was an error processing your message."
                )
                return

            # Handle HITL — agent paused for confirmation
            if agent and hasattr(response, "is_paused") and response.is_paused:
                await _send_hitl_buttons(application_id, interaction_token, response, user_id)
                return

            # Send reasoning content
            if show_reasoning and hasattr(response, "reasoning_content") and response.reasoning_content:
                await _send_followup(
                    application_id,
                    interaction_token,
                    f"*{response.reasoning_content}*",
                    edit_original=True,
                )
                # Send actual content as a new follow-up
                content = get_text_from_message(response.content) if response.content is not None else ""
                await _send_followup(application_id, interaction_token, content)
            else:
                content = get_text_from_message(response.content) if response.content is not None else ""
                await _send_followup(application_id, interaction_token, content, edit_original=True)

            # Upload output media
            await _upload_response_media(application_id, interaction_token, response)

        except Exception as e:
            log_error(f"Error processing Discord command: {e}")
            try:
                await _send_followup(
                    application_id, interaction_token, "Sorry, there was an error processing your message."
                )
            except Exception:
                pass

    async def _process_component(custom_id: str, application_id: str, interaction_token: str, user_id: str):
        try:
            # Sweep stale entries on each access (lazy TTL cleanup)
            _cleanup_stale_hitl()

            # custom_id format: "hitl:{run_id}:{action}" where action is "confirm" or "cancel"
            parts = custom_id.split(":")
            if len(parts) != 3 or parts[0] != "hitl":
                log_warning(f"Unknown component custom_id: {custom_id}")
                return

            run_id = parts[1]
            action = parts[2]

            pending = _pending_hitl.get(run_id)
            if not pending:
                await _send_webhook(
                    application_id,
                    interaction_token,
                    "This action has expired or already been handled.",
                    ephemeral=True,
                )
                return

            # C1 fix: Only the original requester can confirm/cancel
            if pending.get("initiator_user_id") and pending["initiator_user_id"] != user_id:
                await _send_webhook(
                    application_id,
                    interaction_token,
                    "Only the original requester can confirm this action.",
                    ephemeral=True,
                )
                return

            # Remove from pending now that we've validated
            _pending_hitl.pop(run_id, None)

            run_response = pending["run_response"]

            confirmed = action == "confirm"

            for tool in run_response.tools_requiring_confirmation:
                tool.confirmed = confirmed

            if agent:
                continued = await agent.acontinue_run(run_response=run_response)  # type: ignore[call-overload]

                # H4 fix: Use the component callback's own token for responses (not the stored originals)
                if continued:
                    content = get_text_from_message(continued.content) if continued.content is not None else ""
                    status_msg = "Confirmed" if confirmed else "Cancelled"
                    await _send_followup(application_id, interaction_token, f"*{status_msg}*\n\n{content}")
                else:
                    await _send_followup(
                        application_id, interaction_token, "Action cancelled." if not confirmed else "Done."
                    )
        except Exception as e:
            log_error(f"Error processing Discord component: {e}")

    # --- Helper functions ---

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

    async def _download_attachment(
        attachment: dict,
        images: List[Image],
        files: List[File],
        audio_list: List[Audio],
        videos: List[Video],
    ):
        url = attachment.get("url")
        if not url:
            return
        content_type = attachment.get("content_type", "application/octet-stream")
        filename = attachment.get("filename", "file")
        size = attachment.get("size", 0)

        # 25MB size cap
        if size > 25 * 1024 * 1024:
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

    async def _send_followup(
        application_id: str,
        interaction_token: str,
        message: str,
        edit_original: bool = False,
    ):
        if not message:
            message = "(empty response)"

        if edit_original:
            batches = _split_message(message)
            # First batch edits the deferred "thinking..." message
            await _edit_original(application_id, interaction_token, batches[0])
            # Remaining batches as new follow-ups
            for batch in batches[1:]:
                await _send_webhook(application_id, interaction_token, batch)
        else:
            batches = _split_message(message)
            for batch in batches:
                await _send_webhook(application_id, interaction_token, batch)

    def _split_message(message: str) -> List[str]:
        if len(message) <= max_message_chars:
            return [message]

        batches = [message[i : i + max_message_chars] for i in range(0, len(message), max_message_chars)]
        return [f"[{i}/{len(batches)}] {batch}" for i, batch in enumerate(batches, 1)]

    async def _send_hitl_buttons(application_id: str, interaction_token: str, run_response, initiator_user_id: str):
        run_id = run_response.run_id or "unknown"

        tool_names = [t.tool_name for t in run_response.tools_requiring_confirmation]
        tool_list = ", ".join(tool_names) if tool_names else "a tool"

        # Store for later retrieval when button is clicked
        _pending_hitl[run_id] = {
            "run_response": run_response,
            "application_id": application_id,
            "interaction_token": interaction_token,
            "initiator_user_id": initiator_user_id,
            "created_at": time.time(),
        }

        components = [
            {
                "type": 1,  # ACTION_ROW
                "components": [
                    {
                        "type": 2,  # BUTTON
                        "style": 1,  # PRIMARY
                        "label": "Confirm",
                        "custom_id": f"hitl:{run_id}:confirm",
                    },
                    {
                        "type": 2,  # BUTTON
                        "style": 2,  # SECONDARY
                        "label": "Cancel",
                        "custom_id": f"hitl:{run_id}:cancel",
                    },
                ],
            }
        ]

        await _edit_original(
            application_id,
            interaction_token,
            f"Tool requiring confirmation: **{tool_list}**",
            components=components,
        )

    async def _upload_response_media(application_id: str, interaction_token: str, response):
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
                    await _upload_webhook_file(application_id, interaction_token, filename, content_bytes)
                except Exception as e:
                    log_error(f"Failed to upload {attr.rstrip('s')}: {e}")

    return router
