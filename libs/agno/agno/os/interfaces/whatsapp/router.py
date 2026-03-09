import asyncio
import hashlib
import re
from time import time
from typing import Any, Literal, NamedTuple, Optional, Type, Union
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from agno.agent.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.media import Audio, File, Image, Video
from agno.os.interfaces.whatsapp.helpers import (
    WhatsAppConfig,
    extract_message_content,
    get_media_async,
    send_whatsapp_message_async,
    typing_indicator_async,
    upload_and_send_media_async,
)
from agno.os.interfaces.whatsapp.security import validate_webhook_signature
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.utils.log import log_error, log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow

_ERROR_MESSAGE = "Sorry, there was an error processing your message. Please try again later."
_SESSION_RESET_MESSAGE = "New conversation started!"

# Metadata lines from ReasoningTools that aren't useful to end users
_REASONING_SKIP_PREFIXES = ("Action:", "Next Action:", "Confidence:")

# WhatsApp tools that send messages directly during agent execution;
# router skips duplicate text when any of these ran
_WA_TOOL_NAMES = frozenset(
    {
        "send_text_message",
        "send_template_message",
        "send_reply_buttons",
        "send_list_message",
        "send_image",
        "send_document",
        "send_location",
        "send_reaction",
        "mark_as_read",
    }
)


class _SessionConfig(NamedTuple):
    session_type: SessionType
    session_cls: Type[Any]
    id_field: str
    db: Any
    has_db: bool
    is_async_db: bool


_SESSION_DISPATCH = {
    "agent": (SessionType.AGENT, AgentSession, "agent_id"),
    "team": (SessionType.TEAM, TeamSession, "team_id"),
    "workflow": (SessionType.WORKFLOW, WorkflowSession, "workflow_id"),
}


def _resolve_session_config(entity: Any, entity_type: str) -> _SessionConfig:
    session_type, session_cls, id_field = _SESSION_DISPATCH[entity_type]
    db = getattr(entity, "db", None)
    return _SessionConfig(
        session_type=session_type,
        session_cls=session_cls,
        id_field=id_field,
        db=db,
        has_db=isinstance(db, (BaseDb, AsyncBaseDb)),
        is_async_db=isinstance(db, AsyncBaseDb),
    )


def _format_reasoning(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped in ("—", "---"):
            continue
        if stripped.startswith(_REASONING_SKIP_PREFIXES):
            continue
        # Convert markdown headers to WhatsApp bold
        header = re.match(r"^#{1,3}\s+(.+)$", stripped)
        if header:
            lines.append(f"*{header.group(1)}*")
        else:
            lines.append(stripped)
    return "\n".join(lines)


class WhatsAppWebhookResponse(BaseModel):
    status: str = Field(default="ok", description="Processing status")


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    show_reasoning: bool = False,
    send_user_number_to_context: bool = False,
    access_token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    verify_token: Optional[str] = None,
) -> APIRouter:
    if agent is None and team is None and workflow is None:
        raise ValueError("Either agent, team, or workflow must be provided.")

    # Inner functions capture config via closure to keep each instance isolated
    entity = agent or team or workflow
    # entity_type drives session dispatch and /new handler
    entity_type: Literal["agent", "team", "workflow"] = "agent" if agent else "team" if team else "workflow"
    raw_name = getattr(entity, "name", None)
    # entity_name labels messages; entity_id namespaces session IDs
    entity_name = raw_name if isinstance(raw_name, str) else entity_type
    # Multiple WhatsApp routers on one app need unique operation_ids
    op_suffix = entity_name.lower().replace(" ", "_")
    entity_id = getattr(entity, "id", None) or entity_name

    # Used by /new handler (create sessions) and process_message (find latest)
    session_config = _resolve_session_config(entity, entity_type)

    config = WhatsAppConfig.init(
        access_token=access_token,
        phone_number_id=phone_number_id,
        verify_token=verify_token,
    )

    @router.get("/status", operation_id=f"whatsapp_status_{op_suffix}")
    async def status():
        return {"status": "available"}

    @router.get(
        "/webhook",
        operation_id=f"whatsapp_verify_{op_suffix}",
        name="whatsapp_verify",
        description="Handle WhatsApp webhook verification",
    )
    async def verify_webhook(request: Request):
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        if not config.verify_token:
            raise HTTPException(status_code=500, detail="WHATSAPP_VERIFY_TOKEN is not set")

        if mode == "subscribe" and token == config.verify_token:
            if not challenge:
                raise HTTPException(status_code=400, detail="No challenge received")
            return PlainTextResponse(content=challenge)

        raise HTTPException(status_code=403, detail="Invalid verify token or mode")

    @router.post(
        "/webhook",
        operation_id=f"whatsapp_webhook_{op_suffix}",
        name="whatsapp_webhook",
        description="Process incoming WhatsApp messages",
        response_model=WhatsAppWebhookResponse,
        responses={
            200: {"description": "Event processed successfully"},
            403: {"description": "Invalid webhook signature"},
        },
    )
    async def webhook(request: Request, background_tasks: BackgroundTasks):
        payload = await request.body()
        signature = request.headers.get("X-Hub-Signature-256")

        body = await request.json()

        if not validate_webhook_signature(payload, signature):
            log_warning("Invalid webhook signature")
            raise HTTPException(status_code=403, detail="Invalid signature")

        if body.get("object") != "whatsapp_business_account":
            log_warning(f"Received non-WhatsApp webhook object: {body.get('object')}")
            return WhatsAppWebhookResponse(status="ignored")

        # ACK immediately, process in background. Meta retries if no 200 within ~20s
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                for message in change.get("value", {}).get("messages", []):
                    background_tasks.add_task(process_message, message)

        return WhatsAppWebhookResponse(status="processing")

    async def process_message(message: dict):
        # Extract early so error handler can notify the user
        phone_number = message["from"]
        # Hash phone number before it reaches storage — deterministic so the
        # same phone always resolves to the same session, but irreversible
        hashed_phone = hashlib.sha256(phone_number.encode()).hexdigest()
        try:
            message_id = message.get("id")
            await typing_indicator_async(message_id, config)

            parsed = extract_message_content(message)
            if parsed is None:
                return

            # /new starts a fresh session — old session data is preserved
            if parsed.text.strip().lower() == "/new":
                if not session_config.has_db:
                    await send_whatsapp_message_async(
                        phone_number, "Session reset requires storage to be configured.", config
                    )
                    return
                try:
                    new_session_id = f"wa:{entity_id}:{hashed_phone}:{uuid4().hex[:8]}"
                    new_session = session_config.session_cls(
                        session_id=new_session_id,
                        user_id=hashed_phone,
                        created_at=int(time()),
                        **{session_config.id_field: entity_id},
                    )
                    if session_config.is_async_db:
                        await session_config.db.upsert_session(new_session)
                    else:
                        session_config.db.upsert_session(new_session)
                    await send_whatsapp_message_async(phone_number, _SESSION_RESET_MESSAGE, config)
                except Exception as e:
                    log_warning(f"Failed to persist /new session: {e}")
                    await send_whatsapp_message_async(phone_number, _ERROR_MESSAGE, config)
                return

            log_info(f"Processing message from {hashed_phone[:12]}: {parsed.text}")

            # Resolve session: check DB for latest, fall back to deterministic ID
            default_session_id = f"wa:{entity_id}:{hashed_phone}"
            session_id = default_session_id
            if session_config.has_db:
                try:
                    # Find the most recent session for this user + entity
                    session_filter = dict(
                        session_type=session_config.session_type,
                        user_id=hashed_phone,
                        component_id=entity_id,
                        limit=1,
                        sort_by="updated_at",
                        sort_order="desc",
                    )
                    if session_config.is_async_db:
                        sessions = await session_config.db.get_sessions(**session_filter)
                    else:
                        sessions = session_config.db.get_sessions(**session_filter)
                    if sessions:
                        session_id = sessions[0].session_id
                except Exception as e:
                    log_warning(f"Session lookup failed, using default: {e}")

            # Download media from Meta servers and wrap as Agno media objects
            run_kwargs: dict = {
                "user_id": hashed_phone,
                "session_id": session_id,
            }
            if parsed.image_id:
                media = await get_media_async(parsed.image_id, config)
                if isinstance(media, bytes):
                    run_kwargs["images"] = [Image(content=media)]
            if parsed.doc_id:
                media = await get_media_async(parsed.doc_id, config)
                if isinstance(media, bytes):
                    run_kwargs["files"] = [File(content=media)]
            if parsed.video_id:
                media = await get_media_async(parsed.video_id, config)
                if isinstance(media, bytes):
                    run_kwargs["videos"] = [Video(content=media)]
            if parsed.audio_id:
                media = await get_media_async(parsed.audio_id, config)
                if isinstance(media, bytes):
                    run_kwargs["audio"] = [Audio(content=media)]

            # Inject phone number so the agent can reference the user in responses
            if send_user_number_to_context:
                run_kwargs["dependencies"] = {"User info": f"User's Whatsapp number = {phone_number}"}
                run_kwargs["add_dependencies_to_context"] = True

            # Refresh typing indicator every 20s while the agent runs
            # WhatsApp auto-dismisses the indicator after ~25s
            async def _keep_typing():
                try:
                    while True:
                        await asyncio.sleep(20)
                        await typing_indicator_async(message_id, config)
                except asyncio.CancelledError:
                    pass

            typing_task = asyncio.create_task(_keep_typing())
            try:
                response = await entity.arun(parsed.text, **run_kwargs)  # type: ignore[union-attr]
            finally:
                typing_task.cancel()

            if response.status == "ERROR":
                await send_whatsapp_message_async(phone_number, _ERROR_MESSAGE, config)
                log_error(response.content)
                return

            if show_reasoning and hasattr(response, "reasoning_content") and response.reasoning_content:
                reasoning = _format_reasoning(response.reasoning_content)
                if reasoning:
                    await send_whatsapp_message_async(phone_number, reasoning, config, italics=True)

            # Send media first, then decide whether to also send text
            has_media = False
            for attr, media_type in (
                ("images", "image"),
                ("files", "document"),
                ("audio", "audio"),
            ):
                items = getattr(response, attr, None)
                if items:
                    await upload_and_send_media_async(items, media_type, phone_number, config, response.content)
                    has_media = True
            if response.response_audio:
                # Single audio object (not a list) — no text fallback on failure
                await upload_and_send_media_async(
                    [response.response_audio], "audio", phone_number, config, send_text_fallback=False
                )
                has_media = True

            response_tools = getattr(response, "tools", None)
            tools_sent_message = response_tools and any(t.tool_name in _WA_TOOL_NAMES for t in response_tools)
            # Only send text if no media was uploaded and no tool already messaged the user
            if not has_media and not tools_sent_message:
                await send_whatsapp_message_async(phone_number, response.content or "", config)
            # Media caption is capped at 1024 chars; send full text separately when truncated
            elif has_media and response.content and len(response.content) > 1024:
                await send_whatsapp_message_async(phone_number, response.content, config)

        except Exception as e:
            log_error(f"Error processing message: {e}")
            try:
                await send_whatsapp_message_async(phone_number, _ERROR_MESSAGE, config)
            except Exception as send_error:
                log_error(f"Error sending error message: {send_error}")

    return router
