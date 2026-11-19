"""Stateful helpers for the Lark interface: dedup, streaming, and session lookup.

This module mirrors the Telegram interface's ``state.py`` structure but adapts
the streaming display to Lark's *interactive card* model:

  * Telegram edits a text message in place (``edit_message_text``).
  * Lark PATCHes an interactive card (``PATCH /im/v1/messages/:id``).

The :class:`StreamState` therefore sends a card first (as a reply to the user's
message) and patches its content as tokens arrive — the same send-then-edit
lifecycle, different transport.

Session bookkeeping (``build_session_store_config`` / ``find_latest_session_id``)
is platform-agnostic and reused verbatim from the Telegram implementation.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, List, Literal, NamedTuple, Optional, Type, Union

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.media import Audio, File, Image, Video
from agno.os.interfaces.lark.formatting import build_card_content, truncate_markdown
from agno.os.interfaces.lark.helpers import LarkClient
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput

# Throttle card PATCHes to this interval (seconds). Lark allows 5 QPS per
# message; 1 edit/sec is well within budget and reads naturally in the client.
LARK_STREAM_EDIT_INTERVAL = 1.0

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
    """Resolve the session class + DB for the given entity type."""
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
    cfg: _SessionStoreConfig,
    user_id: Optional[str],
    entity_id: Optional[str],
    session_scope: Optional[str] = None,
) -> Optional[str]:
    """Find the most recent session matching the chat scope.

    Lark (like Telegram) derives ``session_id`` from the chat id, but the DB
    has no prefix filter — so we fetch recent sessions and match the scope
    client-side.
    """
    query = dict(
        session_type=cfg.session_type,
        user_id=user_id,
        component_id=entity_id,
        sort_by="created_at",
        sort_order="desc",
        limit=50,
        deserialize=False,
    )
    if cfg.is_async_db:
        results = await cfg.db.get_sessions(**query)  # type: ignore[arg-type, misc]
    else:
        # Sync DB would block the event loop; offload to a thread.
        results = await asyncio.to_thread(cfg.db.get_sessions, **query)  # type: ignore[arg-type]
    rows = results[0] if isinstance(results, tuple) else results
    if not rows:
        return None
    for row in rows:
        sid = row.get("session_id", "") if isinstance(row, dict) else getattr(row, "session_id", "")
        if session_scope and sid and sid.startswith(session_scope):
            return sid
    return None


@dataclass
class BotState:
    """Per-interface runtime state: bot identity + event dedup.

    Lark retries webhook delivery if not ACKed within 3s, so we dedup by
    ``event_id`` (in ``header.event_id``) with a short TTL.
    """

    client: LarkClient
    session_config: _SessionStoreConfig
    entity_id: Optional[str] = None
    bot_open_id: Optional[str] = None
    # event_id -> monotonic timestamp of first sighting
    processed_events: dict[str, float] = field(default_factory=dict)

    # Seconds before a seen event_id is forgotten (memory cleanup).
    DEDUP_TTL_SECONDS: ClassVar[float] = 120.0

    async def get_bot_open_id(self) -> Optional[str]:
        if self.bot_open_id is None:
            self.bot_open_id = await self.client.get_bot_open_id()
        return self.bot_open_id

    def is_duplicate_event(self, event_id: str) -> bool:
        now = time.monotonic()
        expired = [eid for eid, ts in self.processed_events.items() if now - ts > self.DEDUP_TTL_SECONDS]
        for eid in expired:
            del self.processed_events[eid]
        if event_id in self.processed_events:
            return True
        self.processed_events[event_id] = now
        return False


class StreamState:
    """Progressive card-update state machine for streaming responses.

    Lifecycle:
      1. On the first content chunk, send an interactive card as a *reply* to
         the user's message — capture the returned ``message_id``.
      2. As subsequent chunks arrive (throttled to ``LARK_STREAM_EDIT_INTERVAL``),
         PATCH the card with accumulated content + a status note block.
      3. On stream end, :meth:`finalize` PATCHes the final card once more.

    If the accumulated content exceeds Lark's 30 KB card limit, it is truncated
    in-place (the head is preserved) with a truncation marker.
    """

    def __init__(
        self,
        client: LarkClient,
        chat_id: str,
        reply_to: Optional[str],
        entity_type: EntityType,
        error_message: str,
    ):
        self.client = client
        self.chat_id = chat_id
        self.reply_to = reply_to  # incoming message_id, for threading the reply
        self.entity_type: EntityType = entity_type
        self.error_message = error_message

        self.sent_message_id: Optional[str] = None
        self.accumulated_content: str = ""
        self.status_lines: List[str] = []
        self.last_edit_time: float = 0.0
        # Set by router after stream ends; used for error/media handling.
        self.final_run_output: Optional[Union["RunOutput", "TeamRunOutput"]] = None
        # Set by step_output handler; fallback if workflow omits final content.
        self.workflow_final_content: Optional[str] = None
        # Media collected from streaming events (workflow steps, agent runs).
        self.images: List[Image] = []
        self.videos: List[Video] = []
        self.audio: List[Audio] = []
        self.files: List[File] = []

    # ------------------------------------------------------------------ #
    # Status-line bookkeeping (mirrors Telegram StreamState)
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    # Card rendering
    # ------------------------------------------------------------------ #

    def _has_display(self) -> bool:
        return bool(self.accumulated_content.strip()) or bool(self.status_lines)

    def build_display_card(self) -> Optional[str]:
        """Build the card JSON for the current state, or ``None`` if empty."""
        if not self._has_display():
            return None
        content = truncate_markdown(self.accumulated_content) if self.accumulated_content else ""
        return build_card_content(content, self.status_lines or None)

    # ------------------------------------------------------------------ #
    # Send / edit
    # ------------------------------------------------------------------ #

    async def _send_new(self, card_content: str) -> Optional[str]:
        """Send the initial card as a reply (or fresh message). Returns message_id."""
        if self.reply_to:
            try:
                msg_id = await self.client.reply_message(self.reply_to, "interactive", card_content)
                if msg_id:
                    return msg_id
            except Exception as e:
                log_warning(f"Lark reply failed, falling back to plain send: {e}")
        # Fallback: send a standalone message to the chat.
        return await self.client.send_message(self.chat_id, "interactive", card_content)

    async def _edit(self, card_content: str) -> None:
        if not self.sent_message_id:
            return
        try:
            await self.client.patch_card(self.sent_message_id, card_content)
        except Exception as e:
            # "message is not modified" or transient failures — skip silently
            # rather than break the stream; the next chunk will retry.
            log_debug(f"Lark card PATCH skipped: {e}")

    async def send_or_edit(self, card_content: Optional[str]) -> None:
        if not card_content:
            return
        if self.sent_message_id is None:
            try:
                msg_id = await self._send_new(card_content)
                if msg_id:
                    self.sent_message_id = msg_id
            except Exception as e:
                log_warning(f"Failed to send initial Lark card: {e}")
        else:
            await self._edit(card_content)
        self.last_edit_time = time.monotonic()

    async def update_display(self) -> None:
        try:
            await self.send_or_edit(self.build_display_card())
        except Exception as e:
            log_warning(f"Lark stream display update failed: {e}")

    # ------------------------------------------------------------------ #
    # Finalize
    # ------------------------------------------------------------------ #

    async def finalize(self) -> None:
        self.close_pending_statuses()
        final_card = self.build_display_card()

        if not final_card:
            # Nothing was ever sent and there is nothing to show.
            return

        try:
            if self.sent_message_id:
                await self._edit(final_card)
            else:
                # Stream produced content but no chunk triggered a send (e.g.
                # only a run_completed event with content). Send now.
                msg_id = await self._send_new(final_card)
                if msg_id:
                    self.sent_message_id = msg_id
        except Exception as e:
            log_warning(f"Lark finalize failed, falling back to plain text: {e}")
            await self._finalize_plaintext()

    async def _finalize_plaintext(self) -> None:
        """Last-resort: send the accumulated content as chunked plain text."""
        text = self.accumulated_content or ""
        if not text.strip():
            return
        # Import locally to avoid a circular import at module load.
        from agno.os.interfaces.lark.helpers import send_text_message

        try:
            await send_text_message(self.client, self.chat_id, text)
        except Exception as e:
            log_warning(f"Lark plain text fallback also failed: {e}")
