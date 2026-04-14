from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, List, Literal, NamedTuple, Optional, Type, Union

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.media import Audio, File, Image, Video
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

import re as _re

# Matches any HTML tag (opening, closing, self-closing)
_TAG_RE = _re.compile(r"<[^>]+>")

TG_STREAM_EDIT_INTERVAL = 1.0

EntityType = Literal["agent", "team", "workflow"]

_SESSION_DISPATCH = {
    "agent": (SessionType.AGENT, AgentSession, "agent_id"),
    "team": (SessionType.TEAM, TeamSession, "team_id"),
    "workflow": (SessionType.WORKFLOW, WorkflowSession, "workflow_id"),
}


class _SessionStoreConfig(NamedTuple):
    session_type: SessionType
    session_cls: Type[Any]
    id_field: str
    db: Any
    has_db: bool
    is_async_db: bool


def build_session_store_config(entity: object, entity_type: str) -> _SessionStoreConfig:
    session_type, session_cls, id_field = _SESSION_DISPATCH[entity_type]
    db = getattr(entity, "db", None)
    return _SessionStoreConfig(
        session_type=session_type,
        session_cls=session_cls,
        id_field=id_field,
        db=db,
        has_db=isinstance(db, (BaseDb, AsyncBaseDb)),
        is_async_db=isinstance(db, AsyncBaseDb),
    )


async def find_latest_session_id(
    cfg: _SessionStoreConfig, user_id: Optional[str], entity_id: Optional[str], session_scope: Optional[str] = None
) -> Optional[str]:
    # TODO: Implement this
    # DB API has no session_id prefix filter, so we fetch recent sessions
    # and filter client-side to match the chat/thread/topic scope
    query = dict(
        session_type=cfg.session_type,
        user_id=user_id,
        component_id=entity_id,
        sort_by="created_at",
        sort_order="desc",
        # DB has no session_id prefix filter; fetch enough to find scope match client-side
        limit=50,
        deserialize=False,
    )
    if cfg.is_async_db:
        results = await cfg.db.get_sessions(**query)  # type: ignore[arg-type, misc]
    else:
        # Sync DB would block the event loop; offload to a thread
        results = await asyncio.to_thread(cfg.db.get_sessions, **query)  # type: ignore[arg-type]
    rows = results[0] if isinstance(results, tuple) else results
    if not rows:
        return None
    for row in rows:
        sid = row.get("session_id", "") if isinstance(row, dict) else getattr(row, "session_id", "")
        # Match sessions belonging to this specific chat/thread/topic scope
        if session_scope and sid and sid.startswith(session_scope):
            return sid
    return None


@dataclass
class BotState:
    bot: "AsyncTeleBot"
    session_config: _SessionStoreConfig
    entity_id: Optional[str] = None
    bot_username: Optional[str] = None
    bot_id: Optional[int] = None
    # Tracks seen update_ids to ignore Telegram webhook retries
    processed_updates: dict[int, float] = field(default_factory=dict)
    commands_registered: bool = False

    # Seconds before a seen update_id is forgotten (memory cleanup)
    DEDUP_TTL_SECONDS: ClassVar[float] = 60.0

    async def get_bot_info(self) -> tuple[str, int]:
        if self.bot_username is None or self.bot_id is None:
            me = await self.bot.get_me()
            self.bot_username = me.username
            self.bot_id = me.id
        if self.bot_username is None or self.bot_id is None:
            raise RuntimeError("Failed to retrieve bot info from Telegram API")
        return self.bot_username, self.bot_id

    async def ensure_commands_registered(self, commands: Optional[List[dict]], register: bool) -> None:
        if self.commands_registered or not register or not commands:
            return
        try:
            from telebot.types import BotCommand

            bot_commands = [BotCommand(cmd["command"], cmd["description"]) for cmd in commands]
            await self.bot.set_my_commands(bot_commands)
            self.commands_registered = True
            log_info("Bot commands registered successfully")
        except Exception as e:
            log_warning(f"Failed to register bot commands: {str(e)}")

    def is_duplicate_update(self, update_id: int) -> bool:
        now = time.monotonic()
        expired = [uid for uid, ts in self.processed_updates.items() if now - ts > self.DEDUP_TTL_SECONDS]
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
        entity_type: EntityType,
        error_message: str,
    ):
        self.bot = bot
        self.chat_id = chat_id
        self.reply_to = reply_to
        self.message_thread_id = message_thread_id
        self.entity_type: EntityType = entity_type
        self.error_message = error_message

        self.sent_message_id: Optional[int] = None
        self.accumulated_content: str = ""
        self.status_lines: list[str] = []
        self.last_edit_time: float = 0.0
        # Set by router after stream ends; used for error/media handling
        self.final_run_output: Optional[Union["RunOutput", "TeamRunOutput"]] = None
        # Set by step_output handler; fallback if workflow omits final content
        self.workflow_final_content: Optional[str] = None
        # Media collected from streaming events (workflow steps, agent runs)
        self.images: list[Image] = []
        self.videos: list[Video] = []
        self.audio: list[Audio] = []
        self.files: list[File] = []

    def add_status(self, line: str) -> None:
        self.status_lines.append(line)

    def replace_status(self, find: str, replace: str) -> bool:
        for i, line in enumerate(self.status_lines):
            if line == find:
                self.status_lines[i] = replace
                return True
        return False

    def close_pending_statuses(self) -> None:
        for i, line in enumerate(self.status_lines):
            if line.endswith("..."):
                self.status_lines[i] = line.removesuffix("...")

    def collect_media(self, chunk: Any) -> None:
        # Collect media from streaming events so it can be sent after finalize.
        # Follows the same pattern as Slack StreamState.collect_media()
        for img in getattr(chunk, "images", None) or []:
            if img not in self.images:
                self.images.append(img)
        for vid in getattr(chunk, "videos", None) or []:
            if vid not in self.videos:
                self.videos.append(vid)
        for aud in getattr(chunk, "audio", None) or []:
            if aud not in self.audio:
                self.audio.append(aud)
        for f in getattr(chunk, "files", None) or []:
            if f not in self.files:
                self.files.append(f)

    def build_display_html(self) -> str:
        parts: list[str] = []
        if self.status_lines:
            escaped_status = escape_html("\n".join(self.status_lines))
            parts.append(f"<blockquote>{escaped_status}</blockquote>")
        if self.accumulated_content:
            parts.append(markdown_to_telegram_html(self.accumulated_content))
        return "\n".join(parts)

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
            if "message is not modified" not in str(e):
                log_warning(f"Failed to edit message: {str(e)}")

    async def _send_chunks(self, content: str) -> None:
        await send_message(
            self.bot,
            self.chat_id,
            content,
            reply_to_message_id=self.reply_to,
            message_thread_id=self.message_thread_id,
        )

    @staticmethod
    def _truncate_html(html: str, max_len: int = TG_MAX_MESSAGE_LENGTH) -> str:
        # Find the last safe cut point that doesn't split inside a tag
        if len(html) <= max_len:
            return html
        cut = max_len
        for m in _TAG_RE.finditer(html):
            if m.start() < max_len <= m.end():
                # Cut right before this tag instead of inside it
                cut = m.start()
                break
        return html[:cut]

    async def send_or_edit(self, html: str) -> None:
        if not html or not html.strip():
            return
        display = self._truncate_html(html)
        if self.sent_message_id is None:
            msg = await self._send_new(display)
            self.sent_message_id = msg.message_id
        else:
            await self._edit(display)
        self.last_edit_time = time.monotonic()

    async def update_display(self) -> None:
        try:
            await self.send_or_edit(self.build_display_html())
        except Exception as e:
            log_warning(f"Stream display update failed: {str(e)}")

    async def finalize(self) -> None:
        self.close_pending_statuses()
        final_html = self.build_display_html()
        if not final_html:
            return

        try:
            await self._finalize_inner(final_html)
        except Exception as e:
            log_warning(f"Finalize failed (), falling back to plain text: {str(e)}")
            await self._finalize_plaintext()

    async def _finalize_inner(self, final_html: str) -> None:
        if not self.sent_message_id:
            await self._send_chunks(self.accumulated_content or final_html)
            return

        if len(final_html) <= TG_MAX_MESSAGE_LENGTH:
            await self._edit(final_html)
        else:
            # Content too long for one message — send blockquote header + chunked content
            try:
                await self.bot.delete_message(self.chat_id, self.sent_message_id)
            except Exception:
                pass
            # Preserve the status blockquote as a separate message
            if self.status_lines:
                status_html = f"<blockquote>{escape_html(chr(10).join(self.status_lines))}</blockquote>"
                await self._send_new(status_html)
            await self._send_chunks(self.accumulated_content)

    async def _finalize_plaintext(self) -> None:
        text = self.accumulated_content or ""
        if not text.strip():
            return
        try:
            # Delete the partial streaming message before sending chunked plaintext
            if self.sent_message_id:
                try:
                    await self.bot.delete_message(self.chat_id, self.sent_message_id)
                except Exception:
                    pass
            # Use send_message which handles chunking
            await send_message(
                self.bot,
                self.chat_id,
                text,
                reply_to_message_id=self.reply_to,
                message_thread_id=self.message_thread_id,
            )
        except Exception as e:
            log_warning(f"Plain text fallback also failed: {str(e)}")
