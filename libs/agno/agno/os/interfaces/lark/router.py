"""FastAPI router factory for the Lark interface.

Exposes two endpoints mounted under the interface prefix (default ``/lark``):

  * ``POST /lark/webhook`` — receives Lark event subscription callbacks.
    Verifies the signature (when ``encrypt_key`` is set), decrypts the body,
    handles the URL verification challenge, dedups by ``event_id``, and
    dispatches ``im.message.receive_v1`` events to a background task.
  * ``GET  /lark/status``  — health check.

The message processing flow mirrors the Telegram/WhatsApp interfaces:
webhook → ACK 200 immediately → ``BackgroundTask`` runs the agent →
response sent back via the Lark IM API.
"""

from __future__ import annotations

import json
from time import time
from typing import Literal, Optional, Union
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agno.agent.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.os.interfaces.lark.events import dispatch_stream_event
from agno.os.interfaces.lark.formatting import build_card_content
from agno.os.interfaces.lark.helpers import (
    LarkClient,
    LarkConfig,
    extract_message_payload,
    is_bot_mentioned,
    send_response_media,
    send_text_message,
    strip_mention_placeholders,
)
from agno.os.interfaces.lark.security import maybe_decrypt_body, verify_lark_signature
from agno.os.interfaces.lark.state import (
    BotState,
    StreamState,
    build_session_store_config,
    find_latest_session_id,
)
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.utils.log import log_error, log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow

_ERROR_MESSAGE = "Sorry, there was an error processing your message. Please try again later."
_SESSION_RESET_MESSAGE = "New conversation started!"
_HELP_MESSAGE = (
    "I'm a Lark bot powered by Agno. Send me a message and I'll respond.\n\n"
    "Commands:\n"
    "/new — start a new conversation\n"
    "/help — show this help"
)

# Lark chat types: "p2p" (direct message) or "group".
_LARK_GROUP_CHAT_TYPES = frozenset({"group"})


class LarkWebhookResponse(BaseModel):
    status: str = Field(default="ok", description="Processing status")


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    prefix: str = "/lark",
    tags: Optional[list] = None,
    # Credentials (fall back to env vars inside LarkConfig.init)
    app_id: Optional[str] = None,
    app_secret: Optional[str] = None,
    verification_token: Optional[str] = None,
    encrypt_key: Optional[str] = None,
    domain: Optional[str] = None,
    media_timeout: int = 30,
    # Behavior
    streaming: bool = True,
    show_reasoning: bool = False,
    reply_to_mentions_only: bool = True,
    quoted_responses: bool = False,
) -> APIRouter:
    if agent is None and team is None and workflow is None:
        raise ValueError("Either agent, team, or workflow must be provided.")

    # entity drives session dispatch and the /new handler.
    entity = agent or team or workflow
    entity_type: Literal["agent", "team", "workflow"] = "agent" if agent else "team" if team else "workflow"
    raw_name = getattr(entity, "name", None)
    entity_name = raw_name if isinstance(raw_name, str) else entity_type
    op_suffix = entity_name.lower().replace(" ", "_")
    entity_id = getattr(entity, "id", None) or entity_name

    session_config = build_session_store_config(entity, entity_type)

    config = LarkConfig.init(
        app_id=app_id,
        app_secret=app_secret,
        verification_token=verification_token,
        encrypt_key=encrypt_key,
        domain=domain,
        media_timeout=media_timeout,
    )
    client = LarkClient(config)
    bot_state = BotState(client=client, session_config=session_config, entity_id=entity_id)

    # ------------------------------------------------------------------ #
    # Endpoints
    # ------------------------------------------------------------------ #

    @router.get("/status", operation_id=f"lark_status_{op_suffix}")
    async def status():
        return {"status": "available"}

    @router.post(
        "/webhook",
        operation_id=f"lark_webhook_{op_suffix}",
        name="lark_webhook",
        description="Receive Lark event subscription callbacks",
        response_model=LarkWebhookResponse,
        responses={
            200: {"description": "Event processed successfully"},
            403: {"description": "Invalid webhook signature or verification token"},
        },
    )
    async def webhook(request: Request, background_tasks: BackgroundTasks):
        raw_body = await request.body()

        try:
            body = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        # Decrypt the envelope if encrypt_key is set ({"encrypt": "..."} → plaintext dict).
        body = maybe_decrypt_body(config.encrypt_key, body)

        # challenge handled before signature verification (Lark may not sign it);
        # JSONResponse avoids response_model stripping the field.
        if body.get("type") == "url_verification":
            return JSONResponse(content={"challenge": body.get("challenge", "")})

        # Signature verification — only when encrypt_key is configured.
        if config.encrypt_key:
            timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
            nonce = request.headers.get("X-Lark-Request-Nonce", "")
            signature = request.headers.get("X-Lark-Signature", "")
            if not verify_lark_signature(timestamp, nonce, config.encrypt_key, raw_body, signature):
                log_warning("Invalid Lark webhook signature")
                raise HTTPException(status_code=403, detail="Invalid signature")

        header = body.get("header", {}) or {}

        # Verification token check (lightweight origin verification when no encrypt_key).
        if config.verification_token:
            token = header.get("token", "")
            if token != config.verification_token:
                log_warning("Invalid Lark verification token")
                raise HTTPException(status_code=403, detail="Invalid verification token")

        # Dedup by event_id — Lark retries if not ACKed within 3s.
        event_id = header.get("event_id", "")
        if event_id and bot_state.is_duplicate_event(event_id):
            return LarkWebhookResponse(status="duplicate")

        event_type = header.get("event_type", "")
        if event_type == "im.message.receive_v1":
            # ACK immediately; process the (potentially slow) agent run in the background.
            background_tasks.add_task(_process_message, body)

        return LarkWebhookResponse(status="processing")

    # ------------------------------------------------------------------ #
    # Message processing
    # ------------------------------------------------------------------ #

    async def _send_error(chat_id: str, message_id: Optional[str]) -> None:
        card = build_card_content(_ERROR_MESSAGE)
        try:
            if message_id:
                await client.reply_message(message_id, "interactive", card)
                return
        except Exception as e:
            log_warning(f"Reply with error card failed, falling back to send: {e}")
        try:
            await client.send_message(chat_id, "interactive", card)
        except Exception as e:
            log_error(f"Failed to send Lark error message: {e}")

    async def _process_message(event: dict) -> None:
        message = event.get("event", {}).get("message", {})
        chat_id = message.get("chat_id")
        if not chat_id:
            log_warning("Lark message without chat_id, skipping")
            return

        chat_type = message.get("chat_type", "p2p")
        is_group = chat_type in _LARK_GROUP_CHAT_TYPES
        message_id = message.get("message_id")

        try:
            payload = await extract_message_payload(event, client)
            if payload is None:
                # Unsupported message type — notify the user.
                await send_text_message(client, chat_id, "Sorry, this message type is not supported yet.")
                return

            # /new and /help are handled before mention filtering so they work
            # even when the bot isn't @mentioned in a group.
            text = payload.text.strip() if payload.text else ""
            command = text.split()[0].lower() if text else ""

            if command == "/new":
                await _handle_new_session(chat_id, payload.sender_open_id)
                return
            if command == "/help":
                await send_text_message(client, chat_id, _HELP_MESSAGE)
                return

            # Group mention gating — by default only respond when @mentioned.
            if is_group and reply_to_mentions_only:
                bot_open_id = await bot_state.get_bot_open_id()
                mentioned_open_ids = [m.get("id", {}).get("open_id") for m in (payload.mentions or [])]
                log_info(f"Lark mention check: bot_open_id={bot_open_id}, mentioned={mentioned_open_ids}")
                if not is_bot_mentioned(payload.mentions, bot_open_id):
                    log_info("Lark bot not mentioned, skipping message")
                    return

            # Strip @_user_N mention placeholders before sending text to the agent.
            if payload.text:
                payload.text = strip_mention_placeholders(payload.text)

            # Skip if there's nothing to process (no text and no media).
            if not payload.text and not any((payload.images, payload.audio, payload.videos, payload.files)):
                return

            user_id = payload.sender_open_id or payload.sender_user_id or chat_id
            session_scope = f"lark:{entity_id}:{chat_id}"
            session_id = session_scope
            if session_config.has_db:
                try:
                    found = await find_latest_session_id(session_config, user_id, bot_state.entity_id, session_scope)
                    if found:
                        session_id = found
                except Exception as e:
                    log_warning(f"Lark session lookup failed, using default: {e}")

            log_info(f"Processing Lark message from user {user_id} in chat {chat_id}")

            run_kwargs: dict = {"user_id": user_id, "session_id": session_id}
            if payload.images:
                run_kwargs["images"] = payload.images
            if payload.audio:
                run_kwargs["audio"] = payload.audio
            if payload.videos:
                run_kwargs["videos"] = payload.videos
            if payload.files:
                run_kwargs["files"] = payload.files

            if streaming:
                await _stream_response(payload.text, run_kwargs, chat_id, message_id, is_private=not is_group)
            else:
                await _sync_response(payload.text, run_kwargs, chat_id, message_id)

        except Exception as e:
            log_error(f"Error processing Lark message: {e}")
            try:
                await _send_error(chat_id, message_id)
            except Exception as send_error:
                log_error(f"Error sending Lark error message: {send_error}")

    async def _handle_new_session(chat_id: str, user_id: str) -> None:
        if not session_config.has_db:
            await send_text_message(client, chat_id, "Session reset requires storage to be configured.")
            return
        try:
            new_session_id = f"lark:{entity_id}:{chat_id}:{uuid4().hex[:8]}"
            now = int(time())
            new_session = session_config.session_cls(
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
            await send_text_message(client, chat_id, _SESSION_RESET_MESSAGE)
        except Exception as e:
            log_warning(f"Failed to persist /new Lark session: {e}")
            await send_text_message(client, chat_id, _ERROR_MESSAGE)

    # ------------------------------------------------------------------ #
    # Streaming response
    # ------------------------------------------------------------------ #

    async def _stream_response(
        message_text: str,
        run_kwargs: dict,
        chat_id: str,
        message_id: Optional[str],
        is_private: bool,
    ) -> None:
        is_workflow = entity_type == "workflow"
        stream_kwargs: dict = dict(stream=True, stream_events=True, **run_kwargs)
        if not is_workflow:
            stream_kwargs["yield_run_output"] = True

        state = StreamState(
            client=client,
            chat_id=chat_id,
            reply_to=message_id,
            entity_type=entity_type,
            error_message=_ERROR_MESSAGE,
        )

        try:
            async for event in entity.arun(message_text, **stream_kwargs):  # type: ignore[union-attr]
                # The final RunOutput/TeamRunOutput is yielded last (when yield_run_output=True).
                if isinstance(event, (RunOutput, TeamRunOutput)):
                    state.final_run_output = event
                    continue
                state.collect_media(event)
                ev_raw = getattr(event, "event", "")
                if ev_raw and await dispatch_stream_event(ev_raw, event, state):
                    break
        finally:
            await state.finalize()

        # Error handling after stream ends.
        if not is_workflow and state.final_run_output:
            if state.final_run_output.status == "ERROR":
                await _send_error(chat_id, message_id)
                return

        # Send any media collected during the stream.
        if state.images or state.videos or state.audio or state.files:
            media_target = state.final_run_output if state.final_run_output else state
            try:
                await send_response_media(client, media_target, chat_id)
            except Exception as e:
                log_warning(f"Failed to send Lark response media: {e}")

    # ------------------------------------------------------------------ #
    # Non-streaming response
    # ------------------------------------------------------------------ #

    async def _sync_response(
        message_text: str,
        run_kwargs: dict,
        chat_id: str,
        message_id: Optional[str],
    ) -> None:
        response = await entity.arun(message_text, **run_kwargs)  # type: ignore[union-attr]
        if not response or response.status == "ERROR":
            if response:
                log_error(response.content)
            await _send_error(chat_id, message_id)
            return

        # Optional reasoning block (sent as plain text before the answer).
        if show_reasoning:
            reasoning = getattr(response, "reasoning_content", None)
            if reasoning:
                await send_text_message(client, chat_id, f"Reasoning:\n{reasoning}")

        # Media first (so the text card lands last, as the primary response).
        try:
            await send_response_media(client, response, chat_id)
        except Exception as e:
            log_warning(f"Failed to send Lark response media: {e}")

        if response.content:
            card = build_card_content(response.content)
            try:
                if message_id and quoted_responses:
                    await client.reply_message(message_id, "interactive", card)
                else:
                    await client.send_message(chat_id, "interactive", card)
            except Exception as e:
                log_warning(f"Failed to send Lark card, falling back to text: {e}")
                await send_text_message(client, chat_id, response.content)

    return router
