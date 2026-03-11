import os
import re
import time
from typing import List, Optional, Union
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.telegram.events import process_event
from agno.os.interfaces.telegram.helpers import (
    TG_MAX_CAPTION_LENGTH,
    extract_message,
    is_bot_mentioned,
    send_message,
    send_response_media,
)
from agno.os.interfaces.telegram.security import validate_webhook_secret_token
from agno.os.interfaces.telegram.state import BotState, StreamState, find_latest_session, resolve_session_config
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.team import RemoteTeam, Team
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow

try:
    from telebot.async_telebot import AsyncTeleBot
except ImportError as e:
    raise ImportError("`pyTelegramBotAPI` not installed. Please install using `pip install 'agno[telegram]'`") from e

# Session IDs use a "tg:" prefix to namespace Telegram sessions.
# Format variants:
#   tg:{entity_id}:{chat_id}                              — DMs / private chats
#   tg:{entity_id}:{chat_id}:thread:{root_msg_id}         — Group chats (scoped by reply thread)
#   tg:{entity_id}:{chat_id}:topic:{message_thread_id}    — Forum topic chats (scoped by forum topic)

_TG_GROUP_CHAT_TYPES = {"group", "supergroup"}


class TelegramStatusResponse(BaseModel):
    status: str = Field(default="available")


class TelegramWebhookResponse(BaseModel):
    status: str = Field(description="Processing status")


DEFAULT_START_MESSAGE = "Hello! I'm ready to help. Send me a message to get started."
DEFAULT_HELP_MESSAGE = "Send me text, photos, voice notes, videos, or documents and I'll help you with them."
DEFAULT_ERROR_MESSAGE = "Sorry, there was an error processing your message. Send /new to start a fresh conversation."
DEFAULT_NEW_MESSAGE = "New conversation started. How can I help you?"


def _build_session_key(
    entity_id: Optional[str],
    chat_id: int,
    is_group: bool,
    forum_thread_id: Optional[int],
    message: dict,
) -> str:
    if forum_thread_id:
        scope = f"{chat_id}:topic:{forum_thread_id}"
    elif is_group:
        reply_msg = message.get("reply_to_message")
        root = reply_msg.get("message_id", message.get("message_id")) if reply_msg else message.get("message_id")
        scope = f"{chat_id}:thread:{root}"
    else:
        scope = str(chat_id)
    return f"tg:{entity_id}:{scope}"


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
    stream: bool = True,
    show_reasoning: bool = False,
    commands: Optional[List[dict]] = None,
    register_commands: bool = True,
    new_message: str = DEFAULT_NEW_MESSAGE,
) -> APIRouter:
    if agent is None and team is None and workflow is None:
        raise ValueError("Either agent, team, or workflow must be provided.")

    entity = agent or team or workflow
    entity_type = "agent" if agent else "team" if team else "workflow"

    token = token or os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_TOKEN environment variable is not set and no token was provided")

    entity_id = getattr(entity, "id", None) or getattr(entity, "name", None) or entity_type
    session_config = resolve_session_config(entity, entity_type)

    bot_state = BotState(
        bot=AsyncTeleBot(token),
        session_config=session_config,
        entity_type=entity_type,
        entity_id=entity_id,
    )

    # -- Routes --

    @router.get(
        "/status",
        operation_id=f"telegram_status_{entity_type}",
        name="telegram_status",
        description="Check Telegram interface status",
        response_model=TelegramStatusResponse,
    )
    async def status():
        return TelegramStatusResponse()

    @router.post(
        "/webhook",
        operation_id=f"telegram_webhook_{entity_type}",
        name="telegram_webhook",
        description="Process incoming Telegram webhook events",
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
            if update_id is not None and bot_state.check_dedup(update_id):
                return TelegramWebhookResponse(status="duplicate")

            # Only process new messages; edited_message, channel_post, callback_query ignored
            message = body.get("message")
            if not message:
                return TelegramWebhookResponse(status="ignored")

            background_tasks.add_task(_process_message, message)
            return TelegramWebhookResponse(status="processing")

        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error processing webhook: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    # -- Inner functions --

    async def _handle_command(
        cmd: str, chat_id: int, forum_thread_id: Optional[int], base_key: str, user_id: Optional[str] = None
    ) -> bool:
        if cmd == "/start":
            await send_message(bot_state.bot, chat_id, start_message, message_thread_id=forum_thread_id)
            return True
        if cmd == "/help":
            await send_message(bot_state.bot, chat_id, help_message, message_thread_id=forum_thread_id)
            return True
        if cmd == "/new":
            cfg = bot_state.session_config
            if not cfg.has_db:
                await send_message(
                    bot_state.bot,
                    chat_id,
                    "Session management requires storage. Add a database to enable /new.",
                    message_thread_id=forum_thread_id,
                )
                return True
            new_id = f"{base_key}:{uuid4().hex[:8]}"
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
                await send_message(bot_state.bot, chat_id, new_message, message_thread_id=forum_thread_id)
            except Exception as e:
                log_warning(f"Failed to persist new session to DB: {e}")
                await send_message(
                    bot_state.bot,
                    chat_id,
                    "Failed to create new session. Please try again.",
                    message_thread_id=forum_thread_id,
                )
            return True
        return False

    async def _deliver_response(
        response: Optional[Union[RunOutput, TeamRunOutput]],
        chat_id: int,
        reply_to: Optional[int],
        forum_thread_id: Optional[int],
    ) -> None:
        if not response:
            await send_message(
                bot_state.bot, chat_id, error_message, reply_to_message_id=reply_to, message_thread_id=forum_thread_id
            )
            return
        if response.status == "ERROR":
            log_error(response.content)
            await send_message(
                bot_state.bot, chat_id, error_message, reply_to_message_id=reply_to, message_thread_id=forum_thread_id
            )
            return

        if show_reasoning:
            reasoning = getattr(response, "reasoning_content", None)
            if reasoning:
                await send_message(
                    bot_state.bot,
                    chat_id,
                    f"Reasoning:\n{reasoning}",
                    reply_to_message_id=reply_to,
                    message_thread_id=forum_thread_id,
                )

        any_media_sent = await send_response_media(
            bot_state.bot, response, chat_id, reply_to=reply_to, message_thread_id=forum_thread_id
        )

        # Media captions are capped at 1024 chars. If text overflows the caption,
        # send the full text as a follow-up message so nothing is lost.
        if response.content:
            if any_media_sent and len(response.content) > TG_MAX_CAPTION_LENGTH:
                await send_message(bot_state.bot, chat_id, response.content, message_thread_id=forum_thread_id)
            elif not any_media_sent:
                await send_message(
                    bot_state.bot,
                    chat_id,
                    response.content,
                    reply_to_message_id=reply_to,
                    message_thread_id=forum_thread_id,
                )

    async def _stream_response(
        message_text: str,
        run_kwargs: dict,
        chat_id: int,
        reply_to: Optional[int],
        forum_thread_id: Optional[int],
        is_private: bool = False,
    ) -> None:
        is_wf = entity_type == "workflow"
        stream_kwargs: dict = dict(stream=True, stream_events=True, **run_kwargs)
        if not is_wf:
            stream_kwargs["yield_run_output"] = True

        state = StreamState(
            bot=bot_state.bot,
            chat_id=chat_id,
            reply_to=reply_to,
            message_thread_id=forum_thread_id,
            is_team=entity_type == "team",
            is_workflow=is_wf,
            error_message=error_message,
            use_draft=is_private,
        )

        async for event in entity.arun(message_text, **stream_kwargs):  # type: ignore[union-attr]
            if isinstance(event, (RunOutput, TeamRunOutput)):
                state.final_run_output = event
                continue
            ev_raw = getattr(event, "event", "")
            if ev_raw and await process_event(ev_raw, event, state):
                break

        await state.finalize()

        if not is_wf:
            await _deliver_response(state.final_run_output, chat_id, reply_to, forum_thread_id)

    async def _sync_response(
        message_text: str,
        run_kwargs: dict,
        chat_id: int,
        reply_to: Optional[int],
        forum_thread_id: Optional[int],
    ) -> None:
        response = await entity.arun(message_text, **run_kwargs)  # type: ignore[union-attr]
        await _deliver_response(response, chat_id, reply_to, forum_thread_id)

    async def _process_message(message: dict) -> None:
        chat_id = message.get("chat", {}).get("id")
        if not chat_id:
            log_warning("Received message without chat_id")
            return

        forum_thread_id: Optional[int] = None

        try:
            if message.get("from", {}).get("is_bot"):
                return

            chat_type = message.get("chat", {}).get("type", "private")
            is_group = chat_type in _TG_GROUP_CHAT_TYPES
            incoming_message_id = message.get("message_id")
            # forum_thread_id identifies which forum topic a message belongs to
            # in supergroups with Topics enabled
            forum_thread_id = message.get("message_thread_id")

            base_key = _build_session_key(entity_id, chat_id, is_group, forum_thread_id, message)

            await bot_state.register_commands(commands, register_commands)

            text = message.get("text", "")
            cmd_token = text.split()[0] if text.strip() else ""
            cmd = cmd_token.split("@")[0]

            # Fetch bot info once for all group checks
            bot_username: Optional[str] = None
            bot_id: Optional[int] = None
            if is_group:
                bot_username, bot_id = await bot_state.get_bot_info()
                # Skip commands addressed to other bots
                if "@" in cmd_token and cmd_token.split("@", 1)[1].lower() != bot_username.lower():
                    return

            user_id_raw = message.get("from", {}).get("id")
            if not user_id_raw:
                log_warning("Message missing user ID, skipping")
                return
            user_id = str(user_id_raw)

            if await _handle_command(cmd, chat_id, forum_thread_id, base_key, user_id=user_id):
                return

            # Group mention/reply filter — after commands, before processing
            if is_group and reply_to_mentions_only:
                is_mentioned = is_bot_mentioned(message, bot_username)  # type: ignore[arg-type]
                is_reply = reply_to_bot_messages and bool(
                    message.get("reply_to_message", {}).get("from", {}).get("id") == bot_id
                )
                if not is_mentioned and not is_reply:
                    return

            await bot_state.bot.send_chat_action(chat_id, "typing", message_thread_id=forum_thread_id)

            extracted = await extract_message(bot_state.bot, message)
            if extracted is None:
                return
            message_text = extracted.pop("message", "")
            warning = extracted.pop("warning", None)
            if warning:
                await send_message(bot_state.bot, chat_id, warning, message_thread_id=forum_thread_id)

            if is_group and message_text and bot_username:
                message_text = re.sub(rf"@{re.escape(bot_username)}\b", "", message_text, flags=re.IGNORECASE).strip()

            # Resolve session ID: DB lookup with deterministic fallback
            session_id = base_key
            cfg = bot_state.session_config
            if cfg.has_db:
                try:
                    found = await find_latest_session(cfg, user_id, bot_state.entity_id)
                    if found:
                        session_id = found
                except Exception as e:
                    log_warning(f"Session lookup failed, using default: {e}")

            log_info(f"Processing message from user {user_id}")
            log_debug(f"Message content: {message_text}")

            reply_to = incoming_message_id if is_group else None
            # extracted now has only media keys (images, audio, videos, files)
            run_kwargs = dict(user_id=user_id, session_id=session_id, **extracted)

            if stream:
                await _stream_response(
                    message_text, run_kwargs, chat_id, reply_to, forum_thread_id, is_private=not is_group
                )
            else:
                await _sync_response(message_text, run_kwargs, chat_id, reply_to, forum_thread_id)

        except Exception as e:
            log_error(f"Error processing message: {e}", exc_info=True)
            try:
                await send_message(bot_state.bot, chat_id, error_message, message_thread_id=forum_thread_id)
            except Exception as send_error:
                log_error(f"Error sending error message: {send_error}")

    return router
