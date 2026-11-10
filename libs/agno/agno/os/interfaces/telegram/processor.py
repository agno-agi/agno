"""
Shared message-processing logic for the Telegram interface.

Extracted from ``router.py`` so that long-polling mode (``polling.py``)
can reuse the same processing pipeline without duplicating code.

**Webhook mode** continues to use the closures inside ``attach_routes()``
unchanged — this module is only consumed by the polling transport.
"""

import re
import time
from typing import List, Optional, Union
from uuid import uuid4

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.telegram.events import dispatch_stream_event
from agno.os.interfaces.telegram.helpers import (
    extract_message_payload,
    is_bot_mentioned,
    send_message,
    send_response_media,
)
from agno.os.interfaces.telegram.state import (
    BotState,
    StreamState,
    build_session_store_config,
    find_latest_session_id,
)
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.team import RemoteTeam, Team
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow

try:
    from telebot.async_telebot import AsyncTeleBot
except ImportError as e:
    raise ImportError("`pyTelegramBotAPI` not installed. Please install using `pip install 'agno[telegram]'`") from e

_TG_GROUP_CHAT_TYPES = {"group", "supergroup"}


def _build_session_scope(
    entity_id: Optional[str],
    chat_id: int,
    message_thread_id: Optional[int],
) -> str:
    if message_thread_id:
        return f"tg:{entity_id}:{chat_id}:{message_thread_id}"
    return f"tg:{entity_id}:{chat_id}"


class TelegramMessageProcessor:
    """Encapsulates all Telegram message-processing logic.

    This is a self-contained processor that mirrors the logic inside
    ``router.attach_routes()`` but as a reusable class. Used by
    the long-polling transport.
    """

    def __init__(
        self,
        entity: Union[Agent, RemoteAgent, Team, RemoteTeam, Workflow, RemoteWorkflow],
        entity_type: str,
        token: str,
        reply_to_mentions_only: bool = True,
        reply_to_bot_messages: bool = True,
        start_message: str = "Hello! I'm ready to help. Send me a message to get started.",
        help_message: str = "Send me text, photos, voice notes, videos, or documents and I'll help you with them.",
        error_message: str = "Sorry, there was an error processing your message. Send /new to start a fresh conversation.",
        streaming: bool = True,
        show_reasoning: bool = False,
        commands: Optional[List[dict]] = None,
        register_commands: bool = True,
        new_message: str = "New conversation started. How can I help you?",
        quoted_responses: bool = False,
    ):
        if entity_type not in ("agent", "team", "workflow"):
            raise ValueError(f"entity_type must be one of 'agent', 'team', 'workflow', got '{entity_type}'")

        self.entity = entity
        self.entity_type = entity_type
        self.streaming = streaming
        self.show_reasoning = show_reasoning
        self.reply_to_mentions_only = reply_to_mentions_only
        self.reply_to_bot_messages = reply_to_bot_messages
        self.start_message = start_message
        self.help_message = help_message
        self.error_message = error_message
        self.new_message = new_message
        self.commands = commands
        self.register_commands = register_commands
        self.quoted_responses = quoted_responses

        entity_id = getattr(entity, "id", None) or getattr(entity, "name", None) or entity_type
        session_config = build_session_store_config(entity, entity_type)

        self.bot = AsyncTeleBot(token)
        self.bot_state = BotState(
            bot=self.bot,
            session_config=session_config,
            entity_id=entity_id,
        )

    # ------------------------------------------------------------------
    # Command handling
    # ------------------------------------------------------------------

    async def _handle_command(
        self,
        command: str,
        chat_id: int,
        message_thread_id: Optional[int],
        session_scope: str,
        user_id: Optional[str] = None,
    ) -> bool:
        if command == "/start":
            await send_message(self.bot, chat_id, self.start_message, message_thread_id=message_thread_id)
            return True
        if command == "/help":
            await send_message(self.bot, chat_id, self.help_message, message_thread_id=message_thread_id)
            return True
        if command == "/new":
            cfg = self.bot_state.session_config
            if not cfg.has_db:
                await send_message(
                    self.bot,
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
                    **{cfg.id_field: self.bot_state.entity_id},
                )
                if cfg.is_async_db:
                    await cfg.db.upsert_session(session)
                else:
                    cfg.db.upsert_session(session)
                await send_message(self.bot, chat_id, self.new_message, message_thread_id=message_thread_id)
            except Exception as e:
                log_warning(f"Failed to persist new session to DB: {e}")
                await send_message(
                    self.bot,
                    chat_id,
                    "Failed to create new session. Please try again.",
                    message_thread_id=message_thread_id,
                )
            return True
        return False

    # ------------------------------------------------------------------
    # Response delivery
    # ------------------------------------------------------------------

    async def _send_error(self, chat_id: int, reply_to: Optional[int], message_thread_id: Optional[int]) -> None:
        await send_message(
            self.bot, chat_id, self.error_message, reply_to_message_id=reply_to, message_thread_id=message_thread_id
        )

    async def _stream_response(
        self,
        message_text: str,
        run_kwargs: dict,
        chat_id: int,
        reply_to: Optional[int],
        message_thread_id: Optional[int],
    ) -> None:
        is_workflow = self.entity_type == "workflow"
        stream_kwargs: dict = dict(stream=True, stream_events=True, **run_kwargs)
        if not is_workflow:
            stream_kwargs["yield_run_output"] = True

        state = StreamState(
            bot=self.bot,
            chat_id=chat_id,
            reply_to=reply_to,
            message_thread_id=message_thread_id,
            entity_type=self.entity_type,  # type: ignore[arg-type]
            error_message=self.error_message,
        )

        try:
            async for event in self.entity.arun(message_text, **stream_kwargs):  # type: ignore[union-attr]
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
                await self._send_error(chat_id, reply_to, message_thread_id)
            else:
                await send_response_media(
                    self.bot,
                    state.final_run_output,
                    chat_id,
                    reply_to_message_id=reply_to,
                    message_thread_id=message_thread_id,
                )

        if is_workflow and (state.images or state.videos or state.audio or state.files):
            await send_response_media(
                self.bot,
                state,
                chat_id,
                reply_to_message_id=reply_to,
                message_thread_id=message_thread_id,
            )

    async def _sync_response(
        self,
        message_text: str,
        run_kwargs: dict,
        chat_id: int,
        reply_to: Optional[int],
        message_thread_id: Optional[int],
    ) -> None:
        response = await self.entity.arun(message_text, **run_kwargs)  # type: ignore[union-attr]
        if not response or response.status == "ERROR":
            if response:
                log_error(response.content)
            await self._send_error(chat_id, reply_to, message_thread_id)
            return

        if self.show_reasoning:
            reasoning = getattr(response, "reasoning_content", None)
            if reasoning:
                await send_message(
                    self.bot,
                    chat_id,
                    f"Reasoning:\n{reasoning}",
                    reply_to_message_id=reply_to,
                    message_thread_id=message_thread_id,
                )

        await send_response_media(
            self.bot, response, chat_id, reply_to_message_id=reply_to, message_thread_id=message_thread_id
        )
        if response.content:
            await send_message(
                self.bot,
                chat_id,
                response.content,
                reply_to_message_id=reply_to,
                message_thread_id=message_thread_id,
            )

    # ------------------------------------------------------------------
    # Main message processing
    # ------------------------------------------------------------------

    async def process_message(self, message: dict) -> None:
        """Process a single Telegram message dict."""
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

            entity_id = self.bot_state.entity_id
            session_scope = _build_session_scope(entity_id, chat_id, message_thread_id)

            await self.bot_state.ensure_commands_registered(self.commands, self.register_commands)

            text = message.get("text", "")
            cmd_token = text.split()[0] if text.strip() else ""
            command = cmd_token.split("@")[0]

            bot_username: Optional[str] = None
            bot_id: Optional[int] = None
            if is_group:
                bot_username, bot_id = await self.bot_state.get_bot_info()
                if "@" in cmd_token and cmd_token.split("@", 1)[1].lower() != bot_username.lower():
                    return

            user_id_raw = message.get("from", {}).get("id")
            if not user_id_raw:
                log_warning("Message missing user ID, skipping")
                return
            user_id = str(user_id_raw)

            if await self._handle_command(command, chat_id, message_thread_id, session_scope, user_id=user_id):
                return

            if is_group and self.reply_to_mentions_only:
                is_mentioned = is_bot_mentioned(message, bot_username)  # type: ignore[arg-type]
                is_reply = self.reply_to_bot_messages and bool(
                    message.get("reply_to_message", {}).get("from", {}).get("id") == bot_id
                )
                if not is_mentioned and not is_reply:
                    return

            await self.bot.send_chat_action(chat_id, "typing", message_thread_id=message_thread_id)

            extracted = await extract_message_payload(self.bot, message)
            if extracted is None:
                return
            message_text = extracted.pop("message", "")
            warning = extracted.pop("warning", None)
            if warning:
                await send_message(self.bot, chat_id, warning, message_thread_id=message_thread_id)

            if is_group and message_text and bot_username:
                message_text = re.sub(rf"@{re.escape(bot_username)}\b", "", message_text, flags=re.IGNORECASE).strip()

            if not message_text and not any(extracted.get(k) for k in ("images", "audio", "videos", "files")):
                return

            session_id = session_scope
            cfg = self.bot_state.session_config
            if cfg.has_db:
                try:
                    found = await find_latest_session_id(cfg, user_id, self.bot_state.entity_id, session_scope)
                    if found:
                        session_id = found
                except Exception as e:
                    log_warning(f"Session lookup failed, using default: {e}")

            log_info(f"Processing message from user {user_id}")
            log_debug(f"Message content: {message_text}")

            reply_to = incoming_message_id if (is_group or self.quoted_responses) else None
            run_kwargs = dict(user_id=user_id, session_id=session_id, **extracted)

            if self.streaming:
                await self._stream_response(message_text, run_kwargs, chat_id, reply_to, message_thread_id)
            else:
                await self._sync_response(message_text, run_kwargs, chat_id, reply_to, message_thread_id)

        except Exception as e:
            log_error(f"Error processing message: {e}", exc_info=True)
            try:
                await send_message(self.bot, chat_id, self.error_message, message_thread_id=message_thread_id)
            except Exception as send_error:
                log_error(f"Error sending error message: {send_error}")
