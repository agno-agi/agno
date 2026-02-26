import os
import re
from typing import List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.telegram.events import stream_to_telegram
from agno.os.interfaces.telegram.helpers import (
    TG_GROUP_CHAT_TYPES,
    TG_MAX_CAPTION_LENGTH,
    download_inbound_media,
    message_mentions_bot,
    parse_inbound_message,
    send_chunked,
    send_html,
    send_response_media,
)
from agno.os.interfaces.telegram.security import validate_webhook_secret_token
from agno.os.interfaces.telegram.state import BotState
from agno.team import RemoteTeam, Team
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow

try:
    from telebot.async_telebot import AsyncTeleBot
except ImportError as e:
    raise ImportError("`pyTelegramBotAPI` not installed. Please install using `pip install 'agno[telegram]'`") from e

# Re-export for backward compatibility (tests and external code may import from here)
from agno.os.interfaces.telegram.helpers import markdown_to_telegram_html as markdown_to_telegram_html  # noqa: F401

# Session IDs use a "tg:" prefix to namespace Telegram sessions.
# Format variants:
#   tg:{chat_id}                                  — DMs / private chats (one session per chat)
#   tg:{chat_id}:thread:{root_msg_id}             — Group chats (scoped by reply thread)
#   tg:{chat_id}:topic:{message_thread_id}        — Forum topic chats (scoped by forum topic)


class TelegramStatusResponse(BaseModel):
    status: str = Field(default="available")


class TelegramWebhookResponse(BaseModel):
    status: str = Field(description="Processing status")


DEFAULT_START_MESSAGE = "Hello! I'm ready to help. Send me a message to get started."
DEFAULT_HELP_MESSAGE = "Send me text, photos, voice notes, videos, or documents and I'll help you with them."
DEFAULT_ERROR_MESSAGE = "Sorry, there was an error processing your message. Send /new to start a fresh conversation."
DEFAULT_NEW_MESSAGE = "New conversation started. How can I help you?"


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
    stream: bool = False,
    show_reasoning: bool = False,
    commands: Optional[List[dict]] = None,
    register_commands: bool = True,
    new_message: str = DEFAULT_NEW_MESSAGE,
) -> APIRouter:
    if agent is None and team is None and workflow is None:
        raise ValueError("Either agent, team, or workflow must be provided.")

    entity_type = "agent" if agent else "team" if team else "workflow"

    token = token or os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_TOKEN environment variable is not set and no token was provided")

    bot_state = BotState(bot=AsyncTeleBot(token))

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

            # Dedup webhook retries via update_id TTL cache
            update_id = body.get("update_id")
            if update_id is not None:
                if bot_state.check_dedup(update_id):
                    return TelegramWebhookResponse(status="duplicate")

            # Only process new messages. edited_message, channel_post, and
            # callback_query are intentionally ignored for now.
            message = body.get("message")
            if not message:
                return TelegramWebhookResponse(status="ignored")

            background_tasks.add_task(_process_message, message, agent, team, workflow)
            return TelegramWebhookResponse(status="processing")

        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error processing webhook: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    async def _process_message(
        message: dict,
        agent: Optional[Union[Agent, RemoteAgent]],
        team: Optional[Union[Team, RemoteTeam]],
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    ) -> None:
        chat_id = message.get("chat", {}).get("id")
        if not chat_id:
            log_warning("Received message without chat_id")
            return

        bot = bot_state.bot
        forum_thread_id: Optional[int] = None
        base_key: Optional[str] = None

        try:
            if message.get("from", {}).get("is_bot"):
                return

            chat_type = message.get("chat", {}).get("type", "private")
            is_group = chat_type in TG_GROUP_CHAT_TYPES
            incoming_message_id = message.get("message_id")
            # Forum topic ID — present in supergroups with Topics enabled
            forum_thread_id = message.get("message_thread_id")

            # Register bot commands lazily on first webhook
            await bot_state.register_commands(commands, register_commands)

            text = message.get("text", "")
            cmd_token = text.split()[0] if text else ""
            cmd = cmd_token.split("@")[0]

            # In groups, ignore commands addressed to other bots
            if is_group and "@" in cmd_token:
                bot_username, _ = await bot_state.get_bot_info()
                cmd_target = cmd_token.split("@", 1)[1].lower()
                if cmd_target != bot_username.lower():
                    return

            if cmd == "/start":
                await send_html(bot, chat_id, start_message, message_thread_id=forum_thread_id)
                return
            if cmd == "/help":
                await send_html(bot, chat_id, help_message, message_thread_id=forum_thread_id)
                return
            if cmd == "/new":
                # Build the base key the same way session_id is built below
                if forum_thread_id:
                    base_key = f"tg:{chat_id}:topic:{forum_thread_id}"
                elif is_group:
                    base_key = f"tg:{chat_id}:group"
                else:
                    base_key = f"tg:{chat_id}"
                bot_state.bump_session_generation(base_key)
                await send_html(bot, chat_id, new_message, message_thread_id=forum_thread_id)
                return

            if is_group:
                bot_username, bot_id = await bot_state.get_bot_info()
                if reply_to_mentions_only:
                    is_mentioned = message_mentions_bot(message, bot_username)
                    reply_msg = message.get("reply_to_message")
                    is_reply = reply_to_bot_messages and bool(
                        reply_msg and reply_msg.get("from", {}).get("id") == bot_id
                    )
                    if not is_mentioned and not is_reply:
                        return

            await bot.send_chat_action(chat_id, "typing", message_thread_id=forum_thread_id)

            parsed = parse_inbound_message(message)
            if parsed.text is None:
                return
            message_text = parsed.text

            if is_group and message_text:
                message_text = re.sub(rf"@{re.escape(bot_username)}\b", "", message_text, flags=re.IGNORECASE).strip()

            user_id = str(message.get("from", {}).get("id", chat_id))
            # Session ID strategy:
            #   - Forum topics: scoped by topic (message_thread_id) for stable per-topic sessions
            #   - Groups without topics: scoped by reply thread (may drift across bot messages)
            #   - DMs: one session per chat
            # Generation suffix rotated by /new to force a clean session
            if forum_thread_id:
                base_key = f"tg:{chat_id}:topic:{forum_thread_id}"
            elif is_group:
                reply_msg = message.get("reply_to_message")
                root_msg_id = reply_msg.get("message_id", incoming_message_id) if reply_msg else incoming_message_id
                base_key = f"tg:{chat_id}:thread:{root_msg_id}"
            else:
                base_key = f"tg:{chat_id}"

            session_id = bot_state.get_session_id(base_key)

            log_info(f"Processing message from user {user_id}")
            log_debug(f"Message content: {message_text}")

            reply_to = incoming_message_id if is_group else None

            images, audio, videos, files, file_warning = await download_inbound_media(
                bot, parsed.image_file_id, parsed.audio_file_id, parsed.video_file_id, parsed.document_meta
            )

            if file_warning:
                await send_html(bot, chat_id, file_warning, message_thread_id=forum_thread_id)

            # Text-based files (CSV, TXT, JSON, etc.) are inlined into the
            # message so every model provider can process them.  Only true
            # binary formats (PDF, DOCX) stay as File attachments.
            _BINARY_MIME_TYPES = {
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }
            if files:
                kept_files = []
                for f in files:
                    if f.mime_type and f.mime_type in _BINARY_MIME_TYPES:
                        kept_files.append(f)
                    elif f.content:
                        try:
                            text = (
                                f.content.decode("utf-8", errors="replace")
                                if isinstance(f.content, bytes)
                                else str(f.content)
                            )
                            label = f.filename or "file"
                            message_text += f"\n\n--- {label} ---\n{text}"
                        except Exception:
                            kept_files.append(f)
                    else:
                        kept_files.append(f)
                files = kept_files or None

            run_kwargs: dict = dict(
                user_id=user_id,
                session_id=session_id,
                images=images,
                audio=audio,
                videos=videos,
                files=files,
            )

            if stream:
                if workflow:
                    event_stream = workflow.arun(message_text, stream=True, stream_events=True, **run_kwargs)  # type: ignore[union-attr]
                    await stream_to_telegram(
                        bot,
                        event_stream,
                        chat_id,
                        reply_to,
                        message_thread_id=forum_thread_id,
                        error_message=error_message,
                    )
                    return

                if agent:
                    agent_team_stream = agent.arun(
                        message_text, stream=True, stream_events=True, yield_run_output=True, **run_kwargs
                    )  # type: ignore[union-attr]
                else:
                    agent_team_stream = team.arun(  # type: ignore[union-attr, assignment]
                        message_text, stream=True, stream_events=True, yield_run_output=True, **run_kwargs
                    )

                response = await stream_to_telegram(
                    bot,
                    agent_team_stream,
                    chat_id,
                    reply_to,
                    message_thread_id=forum_thread_id,
                    is_team=bool(team),
                    error_message=error_message,
                )

                if response:
                    if response.status == "ERROR":
                        log_error(response.content)
                        await send_chunked(
                            bot,
                            chat_id,
                            error_message,
                            reply_to_message_id=reply_to,
                            message_thread_id=forum_thread_id,
                        )
                        if base_key:
                            bot_state.bump_session_generation(base_key)
                        return
                else:
                    # Stream returned no RunOutput — error was handled inside
                    # stream_to_telegram. Bump session so next message gets a
                    # clean session instead of replaying the failed context.
                    if base_key:
                        bot_state.bump_session_generation(base_key)

                    if show_reasoning:
                        reasoning = getattr(response, "reasoning_content", None)
                        if reasoning:
                            await send_chunked(
                                bot,
                                chat_id,
                                f"Reasoning:\n{reasoning}",
                                reply_to_message_id=reply_to,
                                message_thread_id=forum_thread_id,
                            )

                    await send_response_media(bot, response, chat_id, reply_to=None, message_thread_id=forum_thread_id)
            else:
                response = None
                if agent:
                    response = await agent.arun(message_text, **run_kwargs)
                elif team:
                    response = await team.arun(message_text, **run_kwargs)  # type: ignore
                elif workflow:
                    response = await workflow.arun(message_text, **run_kwargs)  # type: ignore

                if not response:
                    await send_chunked(
                        bot, chat_id, error_message, reply_to_message_id=reply_to, message_thread_id=forum_thread_id
                    )
                    if base_key:
                        bot_state.bump_session_generation(base_key)
                    return

                if response.status == "ERROR":
                    await send_chunked(
                        bot,
                        chat_id,
                        error_message,
                        reply_to_message_id=reply_to,
                        message_thread_id=forum_thread_id,
                    )
                    log_error(response.content)
                    if base_key:
                        bot_state.bump_session_generation(base_key)
                    return

                if show_reasoning:
                    reasoning = getattr(response, "reasoning_content", None)
                    if reasoning:
                        await send_chunked(
                            bot,
                            chat_id,
                            f"Reasoning:\n{reasoning}",
                            reply_to_message_id=reply_to,
                            message_thread_id=forum_thread_id,
                        )

                any_media_sent = await send_response_media(
                    bot, response, chat_id, reply_to, message_thread_id=forum_thread_id
                )

                # Media captions are capped at 1024 chars. If text overflows the caption,
                # send the full text as a follow-up message so nothing is lost.
                if response.content:
                    if any_media_sent and len(response.content) > TG_MAX_CAPTION_LENGTH:
                        await send_chunked(bot, chat_id, response.content, message_thread_id=forum_thread_id)
                    elif not any_media_sent:
                        await send_chunked(
                            bot,
                            chat_id,
                            response.content,
                            reply_to_message_id=reply_to,
                            message_thread_id=forum_thread_id,
                        )

        except Exception as e:
            log_error(f"Error processing message: {e}")
            if base_key:
                bot_state.bump_session_generation(base_key)
            try:
                await send_chunked(bot, chat_id, error_message, message_thread_id=forum_thread_id)
            except Exception as send_error:
                log_error(f"Error sending error message: {send_error}")

    return router
