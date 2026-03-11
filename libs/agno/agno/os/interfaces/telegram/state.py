from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, List, NamedTuple, Optional, Type, Union

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.os.interfaces.telegram.formatting import escape_html, markdown_to_telegram_html
from agno.os.interfaces.telegram.helpers import (
    TG_MAX_MESSAGE_LENGTH,
    send_message,
)
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession
from agno.utils.log import log_info, log_warning

if TYPE_CHECKING:
    from telebot.async_telebot import AsyncTeleBot

    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput

# Regular message edits hit Telegram's 1 msg/sec per-chat rate limit
TG_STREAM_EDIT_INTERVAL = 1.0

# Typing previews are client-side (DM-only) and tolerate faster updates
TG_TYPING_PREVIEW_INTERVAL = 0.3


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


async def find_latest_session(cfg: _SessionConfig, user_id: Optional[str], entity_id: Optional[str]) -> Optional[str]:
    query = dict(
        session_type=cfg.session_type,
        user_id=user_id,
        component_id=entity_id,
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


@dataclass
class BotState:
    bot: "AsyncTeleBot"
    session_config: _SessionConfig
    entity_type: str = "agent"
    entity_id: Optional[str] = None
    bot_username: Optional[str] = None
    bot_id: Optional[int] = None
    processed_updates: dict[int, float] = field(default_factory=dict)
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


class StreamState:
    def __init__(
        self,
        bot: "AsyncTeleBot",
        chat_id: int,
        reply_to: Optional[int],
        message_thread_id: Optional[int],
        is_team: bool,
        is_workflow: bool,
        error_message: str,
        # Typing previews: native animated text display (Telegram DM feature).
        # Faster updates than message edits, auto-disappears on finalize
        use_typing_preview: bool = False,
    ):
        self.bot = bot
        self.chat_id = chat_id
        self.reply_to = reply_to
        self.message_thread_id = message_thread_id
        # When True, tool call status shows "[AgentName] Using tool..." for clarity
        self.is_team = is_team
        self.is_workflow = is_workflow
        self.error_message = error_message
        self.use_typing_preview = use_typing_preview
        self.typing_preview_id: int = 0

        self.sent_message_id: Optional[int] = None
        # Built by event handlers in events.py; rendered by build_display_html()
        self.accumulated_content: str = ""
        self.status_lines: list[str] = []
        self.last_edit_time: float = 0.0
        # Set by _stream_response in router.py; used post-stream for error/media handling
        self.final_run_output: Optional[Union["RunOutput", "TeamRunOutput"]] = None
        # Set by _on_step_output in events.py; fallback if workflow omits final RunContent
        self.workflow_final_content: Optional[str] = None

    # -- Status line management --

    def add_status(self, line: str) -> None:
        self.status_lines.append(line)

    def update_status(self, find: str, replace: str) -> None:
        for i, line in enumerate(self.status_lines):
            if find in line:
                self.status_lines[i] = replace
                return

    def resolve_all_pending(self) -> None:
        for i, line in enumerate(self.status_lines):
            if line.endswith("..."):
                self.status_lines[i] = line.removesuffix("...")

    def build_display_html(self) -> str:
        parts: list[str] = []
        if self.status_lines:
            escaped_status = escape_html("\n".join(self.status_lines))
            parts.append(f"<blockquote expandable>{escaped_status}</blockquote>")
        if self.accumulated_content:
            parts.append(markdown_to_telegram_html(self.accumulated_content))
        return "\n".join(parts)

    # -- Telegram API helpers --

    async def _send_new(self, html: str) -> Any:
        return await self.bot.send_message(
            self.chat_id,
            html,
            parse_mode="HTML",
            reply_to_message_id=self.reply_to,
            message_thread_id=self.message_thread_id,
        )

    async def _edit(self, html: str) -> None:
        try:
            await self.bot.edit_message_text(html, self.chat_id, self.sent_message_id, parse_mode="HTML")
        except Exception as e:
            # "message is not modified" is expected when consecutive chunks produce identical content
            if "message is not modified" not in str(e):
                log_warning(f"Failed to edit message: {e}")

    async def _send_typing_preview(self, html: str) -> None:
        if self.typing_preview_id == 0:
            self.typing_preview_id = random.randint(1, 2**31 - 1)
        try:
            await self.bot.send_message_draft(
                chat_id=self.chat_id,
                draft_id=self.typing_preview_id,
                text=html,
                parse_mode="HTML",
                message_thread_id=self.message_thread_id,
            )
        except Exception as e:
            log_warning(f"Failed to send typing preview: {e}")

    async def _send_chunks(self, content: str) -> None:
        await send_message(
            self.bot,
            self.chat_id,
            content,
            reply_to_message_id=self.reply_to,
            message_thread_id=self.message_thread_id,
        )

    # -- Public streaming interface --

    # First call sends a new message, subsequent calls edit it.
    # Typing preview mode always sends new (no edit needed — preview updates in-place)
    async def send_or_edit(self, html: str) -> None:
        if not html or not html.strip():
            return
        display = html[:TG_MAX_MESSAGE_LENGTH]
        if self.use_typing_preview:
            await self._send_typing_preview(display)
        elif self.sent_message_id is None:
            msg = await self._send_new(display)
            self.sent_message_id = msg.message_id
        else:
            await self._edit(display)
        self.last_edit_time = time.monotonic()

    async def update_display(self) -> None:
        try:
            await self.send_or_edit(self.build_display_html())
        except Exception as e:
            log_warning(f"Stream display update failed: {e}")

    # Final flush after stream ends.
    # Typing preview: send as real message (preview auto-disappears).
    # Regular: edit existing message, or chunk if overflow
    async def finalize(self) -> None:
        self.resolve_all_pending()
        final_html = self.build_display_html()
        if not final_html:
            return

        # Typing preview: send final content as a real message (preview disappears on its own)
        if self.use_typing_preview:
            if len(final_html) <= TG_MAX_MESSAGE_LENGTH:
                msg = await self._send_new(final_html)
                self.sent_message_id = msg.message_id
            else:
                await self._send_chunks(self.accumulated_content)
            return

        if not self.sent_message_id:
            await self._send_chunks(self.accumulated_content or final_html)
            return

        if len(final_html) <= TG_MAX_MESSAGE_LENGTH:
            await self._edit(final_html)
        else:
            # Overflow — delete the live-edited message, re-send as chunks
            try:
                await self.bot.delete_message(self.chat_id, self.sent_message_id)
            except Exception:
                pass
            await self._send_chunks(self.accumulated_content)
