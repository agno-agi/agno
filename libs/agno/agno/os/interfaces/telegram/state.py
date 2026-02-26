from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, List, Optional, Union

from agno.os.interfaces.telegram.helpers import (
    TG_MAX_MESSAGE_LENGTH,
    _escape_html,
    markdown_to_telegram_html,
    send_chunked,
)
from agno.utils.log import log_debug, log_info, log_warning

if TYPE_CHECKING:
    from telebot.async_telebot import AsyncTeleBot

    from agno.db.base import AsyncBaseDb, BaseDb
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput

# Minimum seconds between Telegram message edits to avoid 429 rate limits
TG_STREAM_EDIT_INTERVAL = 1.0


# =============================================================================
# Bot State (persistent — shared across all messages)
# =============================================================================


@dataclass
class BotState:
    """Persistent state for the bot instance (shared across all webhook calls).

    Session management:
        Unlike Slack (where each thread has a unique thread_ts that naturally
        maps to a session), Telegram DMs have a single chat_id for all messages.
        The /new command creates a fresh session by generating a timestamp-based
        session ID (e.g. ``tg:12345:1709012345``).

        An in-memory cache (``active_sessions``) provides O(1) lookups for the
        hot path. On cold start (after server restart), a single DB query per
        chat recovers the latest session ID, which is then cached.
    """

    bot: "AsyncTeleBot"
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    entity_type: str = "agent"
    entity_id: Optional[str] = None
    bot_username: Optional[str] = None
    bot_id: Optional[int] = None
    processed_updates: dict[int, float] = field(default_factory=dict)
    # Maps base_key → active session_id.  Replaces the old integer generation
    # counter so that session identity survives server restarts (backed by DB).
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
        """Check if an update_id has already been processed (deduplication).

        Telegram may retry webhook deliveries if it doesn't receive a timely
        response. This TTL-based cache (60s) prevents duplicate processing
        while keeping memory bounded by evicting expired entries on each call.

        Returns True if the update was already seen (duplicate).
        """
        now = time.monotonic()
        expired = [uid for uid, ts in self.processed_updates.items() if now - ts > self.DEDUP_TTL]
        for uid in expired:
            del self.processed_updates[uid]
        if update_id in self.processed_updates:
            return True
        self.processed_updates[update_id] = now
        return False

    # -- Session management ---------------------------------------------------

    async def new_session(self, base_key: str, user_id: Optional[str] = None) -> str:
        """Create a new session for ``/new``.  Returns the new session_id.

        Generates a timestamp-based ID (``base_key:{unix_ts_ms}``) and persists
        an empty session to the DB so that the mapping survives server restarts.
        Uses millisecond precision to avoid collisions from rapid /new calls.
        """
        new_id = f"{base_key}:{int(time.time() * 1000)}"
        self.active_sessions[base_key] = new_id

        if self.db is not None:
            try:
                await self._persist_empty_session(new_id, user_id)
            except Exception as e:
                log_warning(f"Failed to persist new session to DB: {e}")
        return new_id

    async def get_session_id(self, base_key: str, user_id: Optional[str] = None) -> str:
        """Return the active session_id for *base_key*.

        Hot path (cache hit): O(1) dict lookup, zero DB calls.
        Cold path (after restart): one DB query, then cached.
        """
        # 1. In-memory cache hit
        if base_key in self.active_sessions:
            return self.active_sessions[base_key]

        # 2. Cache miss — try to recover latest session from DB
        if self.db is not None:
            latest = await self._find_latest_session(base_key, user_id)
            if latest:
                self.active_sessions[base_key] = latest
                log_debug(f"Recovered session from DB: {latest}")
                return latest

        # 3. No DB or no existing sessions — use base_key as the first session
        self.active_sessions[base_key] = base_key
        return base_key

    async def invalidate_session(self, base_key: str, user_id: Optional[str] = None) -> None:
        """Invalidate the current session on error (forces a new session next time)."""
        new_id = await self.new_session(base_key, user_id)
        log_debug(f"Session invalidated, new session: {new_id}")

    # -- DB helpers (private) -------------------------------------------------

    def _is_async_db(self) -> bool:
        """Check if the DB is an async implementation."""
        from agno.db.base import AsyncBaseDb

        return isinstance(self.db, AsyncBaseDb)

    async def _persist_empty_session(self, session_id: str, user_id: Optional[str] = None) -> None:
        """Write an empty session record to the DB.

        This ensures the session_id exists in the database before any agent run,
        so that a server restart can discover it via ``_find_latest_session``.
        """
        from agno.db.base import SessionType
        from agno.session.agent import AgentSession
        from agno.session.team import TeamSession
        from agno.session.workflow import WorkflowSession

        now = int(time.time())
        session_type = SessionType(self.entity_type)

        if session_type == SessionType.AGENT:
            session: Union[AgentSession, TeamSession, WorkflowSession] = AgentSession(
                session_id=session_id,
                agent_id=self.entity_id,
                user_id=user_id,
                session_data={},
                created_at=now,
            )
        elif session_type == SessionType.TEAM:
            session = TeamSession(
                session_id=session_id,
                team_id=self.entity_id,
                user_id=user_id,
                session_data={},
                created_at=now,
            )
        else:
            session = WorkflowSession(
                session_id=session_id,
                workflow_id=self.entity_id,
                user_id=user_id,
                session_data={},
                created_at=now,
            )

        if self._is_async_db():
            await self.db.upsert_session(session=session)  # type: ignore[misc, union-attr]
        else:
            # Sync DB — call in the current thread (acceptable for infrequent /new)
            self.db.upsert_session(session=session)  # type: ignore[union-attr]

    async def _find_latest_session(self, base_key: str, user_id: Optional[str] = None) -> Optional[str]:
        """Query the DB for the most recently created session matching *base_key*.

        Uses ``get_sessions`` with ``sort_by=created_at desc, limit=…`` and
        filters results by session_id prefix in Python.  The query hits
        existing indexes (``created_at``, ``session_type``, ``user_id``).
        """
        from agno.db.base import SessionType

        session_type = SessionType(self.entity_type)
        component_id = self.entity_id
        query_kwargs = dict(
            session_type=session_type,
            user_id=user_id,
            component_id=component_id,
            sort_by="created_at",
            sort_order="desc",
            limit=20,
            deserialize=False,
        )

        try:
            # Fetch recent sessions for this user+component, sorted newest-first.
            # We fetch a small page (limit=20) to keep the query fast; the prefix
            # filter in Python narrows it down.  In practice a user rarely has
            # more than a handful of sessions per agent per chat.
            if self._is_async_db():
                results = await self.db.get_sessions(**query_kwargs)  # type: ignore[arg-type, misc, union-attr]
            else:
                results = self.db.get_sessions(**query_kwargs)  # type: ignore[arg-type, union-attr]

            # get_sessions returns List[Session] (deserialize=True) or
            # Tuple[List[Dict], int] (deserialize=False).
            rows: list
            if isinstance(results, tuple):
                rows, _ = results
            else:
                rows = results  # type: ignore[assignment]

            # Find the latest session whose ID starts with our base_key.
            # Multiple sessions may share the same created_at (second-level
            # granularity) when /new is called rapidly, so we collect all
            # matches and pick the lexicographically greatest session_id
            # (the embedded millisecond timestamp breaks the tie).
            best: Optional[str] = None
            for row in rows:
                sid = row.get("session_id", "") if isinstance(row, dict) else getattr(row, "session_id", "")
                if sid and sid.startswith(base_key):
                    if best is None or sid > best:
                        best = sid
            if best:
                return best

        except Exception as e:
            log_warning(f"Failed to query DB for latest session: {e}")

        return None


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

    async def flush(self) -> None:
        try:
            await self.send_or_edit(self.build_display_html())
        except Exception as e:
            log_warning(f"Stream display update failed: {e}")

    async def finalize(self) -> None:
        """Send the final display after the stream ends.

        Resolves pending status lines, then either edits the existing
        message or sends a new chunked message if content overflows.
        """
        self.resolve_all_pending()
        final_html = self.build_display_html()

        if not final_html:
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
