from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, List, NamedTuple, Optional, Type, Union
from uuid import uuid4

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.os.interfaces.telegram.helpers import (
    TG_MAX_MESSAGE_LENGTH,
    _escape_html,
    markdown_to_telegram_html,
    send_chunked,
)
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession
from agno.utils.log import log_debug, log_info, log_warning

if TYPE_CHECKING:
    from telebot.async_telebot import AsyncTeleBot

    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput

# Minimum seconds between Telegram message edits to avoid 429 rate limits
TG_STREAM_EDIT_INTERVAL = 1.0

# Draft mode uses a dedicated streaming API with less aggressive rate limits.
TG_DRAFT_EDIT_INTERVAL = 0.3


def _generate_draft_id() -> int:
    """Generate a unique non-zero draft_id for sendMessageDraft."""
    return random.randint(1, 2**31 - 1)


# Resolved once at startup — maps entity_type to session constructor args
_SESSION_DISPATCH = {
    "agent": (SessionType.AGENT, AgentSession, "agent_id"),
    "team": (SessionType.TEAM, TeamSession, "team_id"),
    "workflow": (SessionType.WORKFLOW, WorkflowSession, "workflow_id"),
}


class _SessionConfig(NamedTuple):
    session_type: SessionType
    session_cls: Type[Any]
    id_field: str  # "agent_id" | "team_id" | "workflow_id"
    db: Any  # Optional[BaseDb | AsyncBaseDb], typed as Any to avoid union complexity
    has_db: bool
    is_async_db: bool


def resolve_session_config(entity: object, entity_type: str) -> _SessionConfig:
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


# =============================================================================
# Bot State (persistent — shared across all messages)
# =============================================================================


@dataclass
class BotState:
    """Persistent state for the bot instance (shared across all webhook calls).

    Handles bot identity caching, command registration, webhook dedup,
    and session management (in-memory cache + DB recovery on cold start).
    Session config is resolved once at startup via ``resolve_session_config``.
    """

    bot: "AsyncTeleBot"
    session_config: _SessionConfig
    entity_type: str = "agent"
    entity_id: Optional[str] = None
    bot_username: Optional[str] = None
    bot_id: Optional[int] = None
    processed_updates: dict[int, float] = field(default_factory=dict)
    # Maps base_key → active session_id; survives across messages, lost on restart
    active_sessions: dict[str, str] = field(default_factory=dict)
    commands_registered: bool = False

    DEDUP_TTL: ClassVar[float] = 60.0

    async def get_bot_info(self) -> tuple[str, int]:
        if self.bot_username is None or self.bot_id is None:
            me = await self.bot.get_me()
            self.bot_username = me.username
            self.bot_id = me.id
        assert self.bot_username is not None and self.bot_id is not None
        return self.bot_username, self.bot_id

    async def register_commands(self, commands: Optional[List[dict]], register: bool) -> None:
        if self.commands_registered or not register or not commands:
            return
        try:
            from telebot.types import BotCommand

            bot_commands = [BotCommand(cmd["command"], cmd["description"]) for cmd in commands]
            await self.bot.set_my_commands(bot_commands)
            self.commands_registered = True
            log_info("Bot commands registered successfully")
        except Exception as e:
            log_warning(f"Failed to register bot commands: {e}")

    def check_dedup(self, update_id: int) -> bool:
        now = time.monotonic()
        expired = [uid for uid, ts in self.processed_updates.items() if now - ts > self.DEDUP_TTL]
        for uid in expired:
            del self.processed_updates[uid]
        if update_id in self.processed_updates:
            return True
        self.processed_updates[update_id] = now
        return False

    # -- Session management ---------------------------------------------------

    async def _db_find_latest(self, user_id: Optional[str]) -> Optional[str]:
        cfg = self.session_config
        query = dict(
            session_type=cfg.session_type,
            user_id=user_id,
            component_id=self.entity_id,
            sort_by="created_at",
            sort_order="desc",
            limit=1,
            deserialize=False,
        )
        if cfg.is_async_db:
            results = await cfg.db.get_sessions(**query)  # type: ignore[arg-type, misc]
        else:
            results = cfg.db.get_sessions(**query)  # type: ignore[arg-type]
        # get_sessions returns List[row] or Tuple[List[row], count]
        rows = results[0] if isinstance(results, tuple) else results
        if not rows:
            return None
        row = rows[0]
        return row.get("session_id", "") if isinstance(row, dict) else getattr(row, "session_id", "")

    async def new_session(self, base_key: str, user_id: Optional[str] = None) -> str:
        cfg = self.session_config
        new_id = f"{base_key}:{uuid4().hex[:8]}"
        self.active_sessions[base_key] = new_id
        if cfg.has_db:
            try:
                session = cfg.session_cls(
                    session_id=new_id,
                    user_id=user_id,
                    created_at=int(time.time()),
                    **{cfg.id_field: self.entity_id},
                )
                if cfg.is_async_db:
                    await cfg.db.upsert_session(session)
                else:
                    cfg.db.upsert_session(session)
            except Exception as e:
                log_warning(f"Failed to persist new session to DB: {e}")
        return new_id

    async def get_session_id(self, base_key: str, user_id: Optional[str] = None) -> str:
        if base_key in self.active_sessions:
            return self.active_sessions[base_key]

        # Cold start — recover latest session from DB
        if self.session_config.has_db:
            try:
                sid = await self._db_find_latest(user_id)
                if sid:
                    self.active_sessions[base_key] = sid
                    log_debug(f"Recovered session from DB: {sid}")
                    return sid
            except Exception as e:
                log_warning(f"Session lookup failed, using default: {e}")

        self.active_sessions[base_key] = base_key
        return base_key

    async def invalidate_session(self, base_key: str, user_id: Optional[str] = None) -> None:
        new_id = await self.new_session(base_key, user_id)
        log_debug(f"Session invalidated, new session: {new_id}")


# =============================================================================
# Stream State (per-stream — created for each streaming response)
# =============================================================================


class StreamState:
    """Mutable state for a single streaming response.

    Combines data tracking (like Slack's StreamState) with Telegram API
    interaction (like Slack's AsyncChatStream) since Telegram requires
    manual message editing for live updates.
    """

    def __init__(
        self,
        bot: "AsyncTeleBot",
        chat_id: int,
        reply_to: Optional[int],
        message_thread_id: Optional[int],
        is_team: bool,
        is_workflow: bool,
        error_message: str,
        use_draft: bool = False,
    ):
        self.bot = bot
        self.chat_id = chat_id
        self.reply_to = reply_to
        self.message_thread_id = message_thread_id
        # is_team controls agent-name prefixing on tool status lines.
        # When True, tool call status shows "[AgentName] Using tool..." for clarity.
        self.is_team = is_team
        self.is_workflow = is_workflow
        self.error_message = error_message
        # Draft mode: use sendMessageDraft for native animated streaming (DMs only).
        self.use_draft = use_draft
        self.draft_id: int = 0

        self.sent_message_id: Optional[int] = None
        self.accumulated_content: str = ""
        self.status_lines: list[str] = []
        self.last_edit_time: float = 0.0
        self.final_run_output: Optional[Union["RunOutput", "TeamRunOutput"]] = None
        self.workflow_final_content: Optional[str] = None
        self.terminal: bool = False

    # -- Status helpers -------------------------------------------------------

    def add_status(self, line: str) -> None:
        self.status_lines.append(line)

    def update_status(self, find: str, replace: str) -> None:
        for i, line in enumerate(self.status_lines):
            if find in line:
                self.status_lines[i] = replace
                return

    def resolve_all_pending(self) -> None:
        """Mark any in-progress status lines as done.

        Called at stream end to clean up orphaned "Using X..." lines
        when a tool call started but the stream ended before completion.
        """
        for i, line in enumerate(self.status_lines):
            if line.endswith("..."):
                self.status_lines[i] = line[:-3]

    # -- Display helpers ------------------------------------------------------

    def build_display_html(self) -> str:
        parts: list[str] = []
        if self.status_lines:
            escaped_status = _escape_html("\n".join(self.status_lines))
            parts.append(f"<blockquote expandable>{escaped_status}</blockquote>")
        if self.accumulated_content:
            parts.append(markdown_to_telegram_html(self.accumulated_content))
        return "\n".join(parts)

    async def send_or_edit(self, html: str) -> None:
        if not html or not html.strip():
            return
        if self.use_draft:
            await self._send_draft(html)
            return
        display = html[:TG_MAX_MESSAGE_LENGTH]
        if self.sent_message_id is None:
            try:
                msg = await self.bot.send_message(
                    self.chat_id,
                    display,
                    parse_mode="HTML",
                    reply_to_message_id=self.reply_to,
                    message_thread_id=self.message_thread_id,
                )
            except Exception:
                msg = await self.bot.send_message(
                    self.chat_id,
                    display,
                    reply_to_message_id=self.reply_to,
                    message_thread_id=self.message_thread_id,
                )
            self.sent_message_id = msg.message_id
        else:
            try:
                await self.bot.edit_message_text(display, self.chat_id, self.sent_message_id, parse_mode="HTML")
            except Exception as e:
                if "message is not modified" not in str(e):
                    try:
                        await self.bot.edit_message_text(display, self.chat_id, self.sent_message_id)
                    except Exception:
                        pass
        self.last_edit_time = time.monotonic()

    async def _send_draft(self, html: str) -> None:
        """Stream a partial message via sendMessageDraft (private chats only)."""
        display = html[:TG_MAX_MESSAGE_LENGTH]
        if self.draft_id == 0:
            self.draft_id = _generate_draft_id()
        try:
            await self.bot.send_message_draft(
                chat_id=self.chat_id,
                draft_id=self.draft_id,
                text=display,
                parse_mode="HTML",
                message_thread_id=self.message_thread_id,
            )
        except Exception:
            try:
                await self.bot.send_message_draft(
                    chat_id=self.chat_id,
                    draft_id=self.draft_id,
                    text=display,
                    message_thread_id=self.message_thread_id,
                )
            except Exception:
                pass
        self.last_edit_time = time.monotonic()

    async def flush(self) -> None:
        try:
            await self.send_or_edit(self.build_display_html())
        except Exception as e:
            log_warning(f"Stream display update failed: {e}")

    async def finalize(self) -> None:
        """Send the final display after the stream ends.

        Resolves pending status lines, then either edits the existing
        message or sends a new chunked message if content overflows.
        In draft mode, sends a real message to replace the draft bubble.
        """
        self.resolve_all_pending()
        final_html = self.build_display_html()

        if not final_html:
            return

        if self.use_draft:
            await self._finalize_draft(final_html)
            return

        if self.sent_message_id:
            if len(final_html) <= TG_MAX_MESSAGE_LENGTH:
                try:
                    await self.bot.edit_message_text(final_html, self.chat_id, self.sent_message_id, parse_mode="HTML")
                except Exception as e:
                    if "message is not modified" not in str(e):
                        try:
                            await self.bot.edit_message_text(final_html, self.chat_id, self.sent_message_id)
                        except Exception:
                            pass
            else:
                # Content overflows a single message — delete the live-edited
                # message and re-send as chunked plain messages.
                try:
                    await self.bot.delete_message(self.chat_id, self.sent_message_id)
                except Exception:
                    pass
                await send_chunked(
                    self.bot,
                    self.chat_id,
                    self.accumulated_content,
                    reply_to_message_id=self.reply_to,
                    message_thread_id=self.message_thread_id,
                )
        else:
            await send_chunked(
                self.bot,
                self.chat_id,
                self.accumulated_content or final_html,
                reply_to_message_id=self.reply_to,
                message_thread_id=self.message_thread_id,
            )

    async def _finalize_draft(self, final_html: str) -> None:
        """Finalize a draft-mode stream by sending the real message.

        Sending a real message replaces the draft bubble in the client.
        For overflow content, fall through to chunked plain messages.
        """
        if len(final_html) <= TG_MAX_MESSAGE_LENGTH:
            try:
                msg = await self.bot.send_message(
                    self.chat_id,
                    final_html,
                    parse_mode="HTML",
                    reply_to_message_id=self.reply_to,
                    message_thread_id=self.message_thread_id,
                )
            except Exception:
                msg = await self.bot.send_message(
                    self.chat_id,
                    final_html,
                    reply_to_message_id=self.reply_to,
                    message_thread_id=self.message_thread_id,
                )
            self.sent_message_id = msg.message_id
        else:
            await send_chunked(
                self.bot,
                self.chat_id,
                self.accumulated_content,
                reply_to_message_id=self.reply_to,
                message_thread_id=self.message_thread_id,
            )
