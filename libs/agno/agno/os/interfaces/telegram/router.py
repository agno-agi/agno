import os
import re
import time
from typing import List, Optional, Union
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.telegram.events import dispatch_stream_event
from agno.os.interfaces.telegram.helpers import (
    extract_message_payload,
    is_bot_mentioned,
    send_message,
    send_response_media,
)
from agno.os.interfaces.telegram.security import validate_webhook_secret_token
from agno.os.interfaces.telegram.state import BotState, StreamState, build_session_store_config, find_latest_session_id
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.team import RemoteTeam, Team
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow

try:
    from telebot.async_telebot import AsyncTeleBot
except ImportError as e:
    raise ImportError("`pyTelegramBotAPI` not installed. Please install using `pip install 'agno[telegram]'`") from e

# Session scope format (no-DB fallback uses these as literal session IDs):
#   tg:{entity_id}:{chat_id}                           — DMs, basic groups, forum General topic
#   tg:{entity_id}:{chat_id}:{message_thread_id}       — supergroup reply threads & forum topics
# With DB storage, sessions are filtered client-side by scope prefix

_TG_GROUP_CHAT_TYPES = {"group", "supergroup"}


class TelegramStatusResponse(BaseModel):
    status: str = Field(default="available")


class TelegramWebhookResponse(BaseModel):
    status: str = Field(description="Processing status")


DEFAULT_START_MESSAGE = "Hello! I'm ready to help. Send me a message to get started."
DEFAULT_HELP_MESSAGE = "Send me text, photos, voice notes, videos, or documents and I'll help you with them."
DEFAULT_ERROR_MESSAGE = "Sorry, there was an error processing your message. Send /new to start a fresh conversation."
DEFAULT_NEW_MESSAGE = "New conversation started. How can I help you?"


def _build_session_scope(
    entity_id: Optional[str],
    chat_id: int,
    message_thread_id: Optional[int],
) -> str:
    # Supergroup replies and forum topics set message_thread_id;
    # DMs, basic groups, and forum General topic do not
    if message_thread_id:
        return f"tg:{entity_id}:{chat_id}:{message_thread_id}"
    return f"tg:{entity_id}:{chat_id}"


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    token: Optional[str] = None,
    reply_to_mentions_only: bool = True,
    reply_to_bot_messages: bool = True,
    start_message: str = DEFAULT_START_MESSAGE,
    help_message: str = DEFAULT_HELP_MESSAGE,
    error_message: str = DEFAULT_ERROR_MESSAGE,
    streaming: bool = True,
    show_reasoning: bool = False,
    commands: Optional[List[dict]] = None,
    register_commands: bool = True,
    new_message: str = DEFAULT_NEW_MESSAGE,
    quoted_responses: bool = False,
) -> APIRouter:
    if agent is None and team is None and workflow is None:
        raise ValueError("Either agent, team, or workflow must be provided.")

    entity = agent or team or workflow
    entity_type = "agent" if agent else "team" if team else "workflow"

    token = token or os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_TOKEN environment variable is not set and no token was provided")

    entity_id = getattr(entity, "id", None) or getattr(entity, "name", None) or entity_type
    session_config = build_session_store_config(entity, entity_type)

    bot = AsyncTeleBot(token)
    bot_state = BotState(
        bot=bot,
        session_config=session_config,
        entity_id=entity_id,
    )

    @router.get(
        "/status",
        operation_id=f"telegram_status_{entity_id}",
        name="telegram_status",
        response_model=TelegramStatusResponse,
    )
    async def status():
        return TelegramStatusResponse()

    @router.post(
        "/webhook",
        operation_id=f"telegram_webhook_{entity_id}",
        name="telegram_webhook",
        response_model=TelegramWebhookResponse,
        responses={
            200: {"description": "Event processed successfully"},
            403: {"description": "Invalid webhook secret token"},
        },
    )
    async def webhook(request: Request, background_tasks: BackgroundTasks):
        try:
            secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if not validate_webhook_secret_token(secret_token):
                log_warning("Invalid webhook secret token")
                raise HTTPException(status_code=403, detail="Invalid secret token")

            body = await request.json()

            update_id = body.get("update_id")
            if update_id is not None and bot_state.is_duplicate_update(update_id):
                return TelegramWebhookResponse(status="duplicate")

            message = body.get("message") or body.get("edited_message")
            if not message:
                return TelegramWebhookResponse(status="ignored")

            background_tasks.add_task(_process_message, message)
            return TelegramWebhookResponse(status="processing")

        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error processing webhook: {str(e)}")
            raise HTTPException(status_code=500, detail="Internal server error")

    async def _handle_command(
        command: str,
        chat_id: int,
        message_thread_id: Optional[int],
        session_scope: str,
        user_id: Optional[str] = None,
    ) -> bool:
        if command == "/start":
            await send_message(bot, chat_id, start_message, message_thread_id=message_thread_id)
            return True
        if command == "/help":
            await send_message(bot, chat_id, help_message, message_thread_id=message_thread_id)
            return True
        if command == "/new":
            cfg = bot_state.session_config
            if not cfg.has_db:
                await send_message(
                    bot,
                    chat_id,
                    "Session management requires storage. Add a database to enable /new.",
                    message_thread_id=message_thread_id,
                )
                return True
            new_id = f"{session_scope}:{uuid4().hex[:8]}"
            try:
                session = cfg.session_cls(
                    session_id=new_id,
                    user_id=user_id,
                    created_at=int(time.time()),
                    **{cfg.id_field: bot_state.entity_id},
                )
                if cfg.is_async_db:
                    await cfg.db.upsert_session(session)
                else:
                    cfg.db.upsert_session(session)
                await send_message(bot, chat_id, new_message, message_thread_id=message_thread_id)
            except Exception as e:
                log_warning(f"Failed to persist new session to DB: {str(e)}")
                await send_message(
                    bot,
                    chat_id,
                    "Failed to create new session. Please try again.",
                    message_thread_id=message_thread_id,
                )
            return True
        return False

    async def _send_error(chat_id: int, reply_to: Optional[int], message_thread_id: Optional[int]) -> None:
        await send_message(
            bot, chat_id, error_message, reply_to_message_id=reply_to, message_thread_id=message_thread_id
        )

    async def _stream_response(
        message_text: str,
        run_kwargs: dict,
        chat_id: int,
        reply_to: Optional[int],
        message_thread_id: Optional[int],
        is_private: bool = False,
    ) -> None:
        is_workflow = entity_type == "workflow"
        stream_kwargs: dict = dict(stream=True, stream_events=True, **run_kwargs)
        if not is_workflow:
            stream_kwargs["yield_run_output"] = True

        state = StreamState(
            bot=bot,
            chat_id=chat_id,
            reply_to=reply_to,
            message_thread_id=message_thread_id,
            entity_type=entity_type,  # type: ignore[arg-type]
            error_message=error_message,
        )

        try:
            async for event in entity.arun(message_text, **stream_kwargs):  # type: ignore[union-attr]
                if isinstance(event, (RunOutput, TeamRunOutput)):
                    state.final_run_output = event
                    continue
                state.collect_media(event)
                ev_raw = getattr(event, "event", "")
                if ev_raw and await dispatch_stream_event(ev_raw, event, state):
                    break
        finally:
            await state.finalize()

        if not is_workflow and state.final_run_output:
            if state.final_run_output.status == "ERROR":
                await _send_error(chat_id, reply_to, message_thread_id)
            else:
                await send_response_media(
                    bot,
                    state.final_run_output,
                    chat_id,
                    reply_to_message_id=reply_to,
                    message_thread_id=message_thread_id,
                )

        # Workflows don't yield RunOutput, so media is only available via
        # streaming events collected in state. Agent/team media is already
        # sent above from final_run_output.
        if is_workflow and (state.images or state.videos or state.audio or state.files):
            await send_response_media(
                bot,
                state,
                chat_id,
                reply_to_message_id=reply_to,
                message_thread_id=message_thread_id,
            )

    async def _sync_response(
        message_text: str,
        run_kwargs: dict,
        chat_id: int,
        reply_to: Optional[int],
        message_thread_id: Optional[int],
    ) -> None:
        response = await entity.arun(message_text, **run_kwargs)  # type: ignore[union-attr]
        if not response or response.status == "ERROR":
            if response:
                log_error(response.content)
            await _send_error(chat_id, reply_to, message_thread_id)
            return

        if show_reasoning:
            reasoning = getattr(response, "reasoning_content", None)
            if reasoning:
                await send_message(
                    bot,
                    chat_id,
                    f"Reasoning:\n{reasoning}",
                    reply_to_message_id=reply_to,
                    message_thread_id=message_thread_id,
                )

        await send_response_media(
            bot, response, chat_id, reply_to_message_id=reply_to, message_thread_id=message_thread_id
        )
        if response.content:
            await send_message(
                bot,
                chat_id,
                response.content,
                reply_to_message_id=reply_to,
                message_thread_id=message_thread_id,
            )

    async def _process_message(message: dict) -> None:
        chat_id = message.get("chat", {}).get("id")
        if not chat_id:
            log_warning("Received message without chat_id")
            return

        message_thread_id: Optional[int] = None

        try:
            if message.get("from", {}).get("is_bot"):
                return

            chat_type = message.get("chat", {}).get("type", "private")
            is_group = chat_type in _TG_GROUP_CHAT_TYPES
            incoming_message_id = message.get("message_id")
            message_thread_id = message.get("message_thread_id")

            session_scope = _build_session_scope(entity_id, chat_id, message_thread_id)

            await bot_state.ensure_commands_registered(commands, register_commands)

            text = message.get("text", "")
            cmd_token = text.split()[0] if text.strip() else ""
            command = cmd_token.split("@")[0]

            bot_username: Optional[str] = None
            bot_id: Optional[int] = None
            if is_group:
                bot_username, bot_id = await bot_state.get_bot_info()
                if "@" in cmd_token and cmd_token.split("@", 1)[1].lower() != bot_username.lower():
                    return

            user_id_raw = message.get("from", {}).get("id")
            if not user_id_raw:
                log_warning("Message missing user ID, skipping")
                return
            user_id = str(user_id_raw)

            if await _handle_command(command, chat_id, message_thread_id, session_scope, user_id=user_id):
                return

            if is_group and reply_to_mentions_only:
                is_mentioned = is_bot_mentioned(message, bot_username)  # type: ignore[arg-type]
                is_reply = reply_to_bot_messages and bool(
                    message.get("reply_to_message", {}).get("from", {}).get("id") == bot_id
                )
                if not is_mentioned and not is_reply:
                    return

            await bot.send_chat_action(chat_id, "typing", message_thread_id=message_thread_id)

            extracted = await extract_message_payload(bot, message)
            if extracted is None:
                return
            message_text = extracted.pop("message", "")
            warning = extracted.pop("warning", None)
            if warning:
                await send_message(bot, chat_id, warning, message_thread_id=message_thread_id)

            if is_group and message_text and bot_username:
                message_text = re.sub(rf"@{re.escape(bot_username)}\b", "", message_text, flags=re.IGNORECASE).strip()

            # Skip model invocation if there's nothing to process
            if not message_text and not any(extracted.get(k) for k in ("images", "audio", "videos", "files")):
                return

            session_id = session_scope
            cfg = bot_state.session_config
            if cfg.has_db:
                try:
                    found = await find_latest_session_id(cfg, user_id, bot_state.entity_id, session_scope)
                    if found:
                        session_id = found
                except Exception as e:
                    log_warning(f"Session lookup failed, using default: {str(e)}")

            log_info(f"Processing message from user {user_id}")
            log_debug(f"Message content: {message_text}")

            reply_to = incoming_message_id if (is_group or quoted_responses) else None
            run_kwargs = dict(user_id=user_id, session_id=session_id, **extracted)

            if streaming:
                await _stream_response(
                    message_text, run_kwargs, chat_id, reply_to, message_thread_id, is_private=not is_group
                )
            else:
                await _sync_response(message_text, run_kwargs, chat_id, reply_to, message_thread_id)

        except Exception as e:
            log_error(f"Error processing message: {str(e)}")
            try:
                await send_message(bot, chat_id, error_message, message_thread_id=message_thread_id)
            except Exception as send_error:
                log_error(f"Error sending error message: {send_error}")

    return router
