import asyncio
import hashlib
from base64 import urlsafe_b64decode, urlsafe_b64encode
from time import time
from typing import Any, Literal, NamedTuple, Optional, Type, Union
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from agno.agent.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.os.interfaces.whatsapp.helpers import (
    WhatsAppConfig,
    download_event_media_async,
    extract_message_content,
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
    }
)


class _SessionConfig(NamedTuple):
    session_type: SessionType
    session_class: Type[Any]
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
    session_type, session_class, id_field = _SESSION_DISPATCH[entity_type]
    db = getattr(entity, "db", None)
    return _SessionConfig(
        session_type=session_type,
        session_class=session_class,
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
        lines.append(stripped)
    return "\n".join(lines)


class WhatsAppWebhookResponse(BaseModel):
    status: str = Field(default="ok", description="Processing status")


def _encrypt_phone(phone: str, key: bytes) -> str:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise ImportError("`cryptography` not installed. Please install using `pip install cryptography`")
    # Same phone → same nonce → same ciphertext; safe because identical plaintext
    nonce = hashlib.sha256(phone.encode()).digest()[:12]
    ct = AESGCM(key).encrypt(nonce, phone.encode(), None)
    return urlsafe_b64encode(nonce + ct).decode()


def decrypt_phone(token: str, key: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    raw = urlsafe_b64decode(token)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(key).decrypt(nonce, ct, None).decode()


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
    media_timeout: int = 30,
    enable_encryption: bool = False,
    encryption_key: Optional[bytes] = None,
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
        media_timeout=media_timeout,
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

        if not validate_webhook_signature(payload, signature):
            log_warning("Invalid webhook signature")
            raise HTTPException(status_code=403, detail="Invalid signature")

        body = await request.json()

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
        phone_number = message.get("from")
        if not phone_number:
            log_warning("Message missing 'from' field, skipping")
            return
        # Splits identity: user_id (possibly encrypted) for DB storage, phone_number (raw) for API sends
        user_id = _encrypt_phone(phone_number, encryption_key) if enable_encryption and encryption_key else phone_number
        try:
            message_id = message.get("id")
            await typing_indicator_async(message_id, config)

            parsed = extract_message_content(message)
            if parsed is None:
                msg_type = message.get("type", "unknown")
                # "unsupported" is WhatsApp's label for stickers and other rich types
                label = "this message type" if msg_type == "unsupported" else msg_type.title()
                await send_whatsapp_message_async(phone_number, f"Sorry, {label} is not supported yet.", config)
                return

            # /new starts a fresh session — old session data is preserved
            if parsed.text.strip().lower() == "/new":
                if not session_config.has_db:
                    await send_whatsapp_message_async(
                        phone_number, "Session reset requires storage to be configured.", config
                    )
                    return
                try:
                    new_session_id = f"wa:{entity_id}:{user_id}:{uuid4().hex[:8]}"
                    now = int(time())
                    new_session = session_config.session_class(
                        session_id=new_session_id,
                        user_id=user_id,
                        created_at=now,
                        updated_at=now,
                        **{session_config.id_field: entity_id},
                    )
                    if session_config.is_async_db:
                        await session_config.db.upsert_session(new_session)
                    else:
                        session_config.db.upsert_session(new_session)
                    await send_whatsapp_message_async(phone_number, _SESSION_RESET_MESSAGE, config)
                except Exception as e:
                    log_warning(f"Failed to persist /new session: {str(e)}")
                    await send_whatsapp_message_async(phone_number, _ERROR_MESSAGE, config)
                return

            log_info(f"Processing message from {user_id[:12]}: {parsed.text}")

            # Resolve session: check DB for latest, fall back to deterministic ID
            default_session_id = f"wa:{entity_id}:{user_id}"
            session_id = default_session_id
            if session_config.has_db:
                try:
                    # Find the most recent session for this user + entity
                    session_filter = dict(
                        session_type=session_config.session_type,
                        user_id=user_id,
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
                    log_warning(f"Session lookup failed, using default: {str(e)}")

            # Download media from Meta servers and wrap as Agno media objects
            media_kwargs, skipped_media = await download_event_media_async(parsed, config)
            run_kwargs: dict = {
                "user_id": user_id,
                "session_id": session_id,
                **media_kwargs,
            }

            # Prepend skip notice so the agent (and user) knows media was dropped
            if skipped_media:
                notice = "[Some media could not be downloaded: " + "; ".join(skipped_media) + "]\n\n"
                parsed.text = notice + parsed.text

            if send_user_number_to_context:
                run_kwargs["dependencies"] = {
                    "User's WhatsApp number": phone_number,
                    "Incoming WhatsApp message ID": message_id,
                }
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

            for attr, media_type in (
                ("images", "image"),
                ("videos", "video"),
                ("files", "document"),
                ("audio", "audio"),
            ):
                items = getattr(response, attr, None)
                if items:
                    await upload_and_send_media_async(items, media_type, phone_number, config)
            if response.response_audio:
                await upload_and_send_media_async(
                    [response.response_audio], "audio", phone_number, config, send_text_fallback=False
                )

            response_tools = getattr(response, "tools", None)
            # Only suppress text if a WA tool ran AND didn't error
            tools_sent_message = response_tools and any(
                t.tool_name in _WA_TOOL_NAMES and not t.tool_call_error for t in response_tools
            )
            # Send text if no tool already messaged the user
            if not tools_sent_message and response.content:
                await send_whatsapp_message_async(phone_number, response.content, config)

        except Exception as e:
            log_error(f"Error processing message: {str(e)}")
            try:
                await send_whatsapp_message_async(phone_number, _ERROR_MESSAGE, config)
            except Exception as send_error:
                log_error(f"Error sending error message: {send_error}")

    return router
