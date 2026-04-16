from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Literal, Optional, Union

from agno.media import Audio, File, Image, Video
from agno.os.interfaces.discord.formatting import normalize_discord_markdown, normalize_for_streaming
from agno.os.interfaces.discord.helpers import (
    _FOLLOWUP_CHUNK_SIZE,
    _MAX_EMBED_DESCRIPTION,
    DiscordWebhook,
    build_status_embed,
)
from agno.os.interfaces.sessions import SessionStoreConfig
from agno.os.interfaces.streaming import chunk_text, collect_media_from_chunk
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput

# Discord rate-limits webhook edits to ~5 req/5s per token; 1.5s gives headroom
_STREAM_EDIT_INTERVAL_SECONDS = 1.5

EntityType = Literal["agent", "team", "workflow"]
TaskStatus = Literal["in_progress", "complete", "error"]

# Discord caps embed fields at 25
_MAX_EMBED_FIELDS = 25

# Discord channel type integers
# https://discord.com/developers/docs/resources/channel#channel-object-channel-types
_ANNOUNCEMENT_THREAD_TYPE = 10
_PUBLIC_THREAD_TYPE = 11
_PRIVATE_THREAD_TYPE = 12
_THREAD_CHANNEL_TYPES = frozenset((_ANNOUNCEMENT_THREAD_TYPE, _PUBLIC_THREAD_TYPE, _PRIVATE_THREAD_TYPE))


# Returns one of:
#   dc:{entity_id}:dm:{channel_id}                      — DM or group DM
#   dc:{entity_id}:thread:{channel_id}                   — thread
#   dc:{entity_id}:channel:{channel_id}:user:{user_id}   — guild channel
def _build_session_scope(
    entity_id: Optional[str],
    channel_id: str,
    user_id: str,
    *,
    guild_id: Optional[str] = None,
    channel_type: Optional[int] = None,
) -> str:
    if not guild_id:
        return f"dc:{entity_id}:dm:{channel_id}"
    if channel_type in _THREAD_CHANNEL_TYPES:
        return f"dc:{entity_id}:thread:{channel_id}"
    return f"dc:{entity_id}:channel:{channel_id}:user:{user_id}"


@dataclass
class TaskCard:
    title: str
    status: TaskStatus = "in_progress"
    error_msg: str = ""

    def to_embed_field(self) -> Dict[str, Any]:
        if self.status == "in_progress":
            name = f"\u23f3 {self.title}..."
        elif self.status == "complete":
            name = f"\u2705 {self.title}"
        else:
            name = f"\u274c {self.title}"
        # Discord requires non-empty field values
        value = self.error_msg[:200] if self.error_msg else "\u200b"
        return {"name": name, "value": value, "inline": True}


@dataclass
class InstanceState:
    """Per-interface-instance state, shared across all concurrent interactions."""

    session_config: SessionStoreConfig
    entity_id: Optional[str] = None
    processed_interactions: Dict[str, float] = field(default_factory=dict)

    # Must match the signature replay window in security._REPLAY_WINDOW_SECONDS —
    # a shorter dedup window would let a replayed signature (still within the
    # signature window) be processed twice
    DEDUP_TTL_SECONDS: ClassVar[float] = 300.0

    def is_duplicate_interaction(self, interaction_id: str) -> bool:
        now = time.monotonic()
        # Dict is insertion-ordered by arrival time (monotonically increasing);
        # once we hit a fresh entry, all later ones are also fresh
        to_delete = []
        for iid, ts in self.processed_interactions.items():
            if now - ts > self.DEDUP_TTL_SECONDS:
                to_delete.append(iid)
            else:
                break
        for iid in to_delete:
            del self.processed_interactions[iid]
        if interaction_id in self.processed_interactions:
            return True
        self.processed_interactions[interaction_id] = now
        return False


class StreamState:
    """Per-interaction streaming lifecycle. One instance per background task."""

    def __init__(
        self,
        webhook: DiscordWebhook,
        entity_type: EntityType,
        entity_name: str,
        error_message: str,
    ):
        self.webhook = webhook
        self.entity_type: EntityType = entity_type
        self.entity_name = entity_name
        self.error_message = error_message

        self._content_parts: List[str] = []
        self.task_cards: Dict[str, TaskCard] = {}
        self.last_edit_time: float = 0.0
        self.reasoning_round: int = 0
        self.error_count: int = 0
        self.error_status: Optional[TaskStatus] = None
        self.final_run_output: Optional[Union["RunOutput", "TeamRunOutput"]] = None
        self.workflow_final_content: Optional[str] = None
        self.images: List[Image] = []
        self.videos: List[Video] = []
        self.audio: List[Audio] = []
        self.files: List[File] = []

    # Content accumulation — list + join avoids O(n^2) string concatenation

    @property
    def accumulated_content(self) -> str:
        return "".join(self._content_parts)

    @accumulated_content.setter
    def accumulated_content(self, value: str) -> None:
        # Replaces all buffered content — used for final output override (workflow/run_completed)
        self._content_parts = [value]

    def append_content(self, text: str) -> None:
        self._content_parts.append(text)

    def has_content(self) -> bool:
        return bool(self._content_parts)

    # Task card operations

    def track_task(self, key: str, title: str) -> None:
        if key not in self.task_cards:
            self.task_cards[key] = TaskCard(title=title)

    def complete_task(self, key: str) -> None:
        card = self.task_cards.get(key)
        if card:
            card.status = "complete"

    def fail_task(self, key: str, error_msg: str = "") -> None:
        card = self.task_cards.get(key)
        if card:
            card.status = "error"
            card.error_msg = error_msg

    def resolve_all_pending(self, status: TaskStatus = "complete") -> None:
        for card in self.task_cards.values():
            if card.status == "in_progress":
                card.status = status

    # Media collection

    def collect_media(self, chunk: Any) -> None:
        collect_media_from_chunk(self, chunk)

    # Embed construction

    def _build_fields(self) -> List[Dict[str, Any]]:
        cards = list(self.task_cards.values())[:_MAX_EMBED_FIELDS]
        return [card.to_embed_field() for card in cards]

    def _build_embed(self, *, title: str, is_final: bool = False) -> Dict[str, Any]:
        description = ""
        if self._content_parts:
            content = self.accumulated_content
            # Full normalization only at finalize; streaming uses lightweight version
            normalized = normalize_discord_markdown(content) if is_final else normalize_for_streaming(content)
            description = normalized[:_MAX_EMBED_DESCRIPTION]
        return build_status_embed(title=title, description=description, fields=self._build_fields())

    # Display updates — rate-limited to avoid 429s

    async def update_display(self) -> None:
        now = time.monotonic()
        if now - self.last_edit_time < _STREAM_EDIT_INTERVAL_SECONDS:
            return
        embed = self._build_embed(title="Processing...")
        try:
            await self.webhook.edit_original(embeds=[embed])
            self.last_edit_time = time.monotonic()
        except Exception as e:
            log_warning(f"Stream display update failed: {str(e)}")

    # Finalization

    async def finalize(self) -> None:
        self.resolve_all_pending()
        # error_status is authoritative; task card scan is fallback
        is_error = self.error_status == "error" or any(c.status == "error" for c in self.task_cards.values())
        title = "Error" if is_error else "Complete"

        content = self.accumulated_content
        if not content and not self.task_cards:
            # Always update the deferred response — silence leaves the user on an infinite spinner
            try:
                await self.webhook.edit_original(content="(no response)")
            except Exception as e:
                log_warning(f"Failed to send empty-response fallback: {str(e)}")
            return

        normalized = normalize_discord_markdown(content) if content else ""
        try:
            await self._finalize_inner(normalized, title)
        except Exception as e:
            log_warning(f"Finalize failed, falling back to plain text: {str(e)}")
            await self._finalize_plaintext(normalized)

    async def _finalize_inner(self, normalized: str, title: str) -> None:
        fields = self._build_fields()
        if len(normalized) <= _MAX_EMBED_DESCRIPTION:
            embed = build_status_embed(title=title, description=normalized, fields=fields)
            await self.webhook.edit_original(embeds=[embed])
            return
        # Content exceeds embed limit — truncated embed + overflow as follow-ups
        embed = build_status_embed(title=title, description=normalized[:_MAX_EMBED_DESCRIPTION], fields=fields)
        await self.webhook.edit_original(embeds=[embed])
        for part in chunk_text(normalized[_MAX_EMBED_DESCRIPTION:], _FOLLOWUP_CHUNK_SIZE):
            await self.webhook.send_followup(content=part)

    async def _finalize_plaintext(self, normalized: str) -> None:
        if not normalized.strip():
            return
        try:
            for part in chunk_text(normalized, _FOLLOWUP_CHUNK_SIZE):
                await self.webhook.send_followup(content=part)
        except Exception as e:
            log_warning(f"Plain text fallback also failed: {str(e)}")


async def insert_sentinel_session(
    cfg: SessionStoreConfig,
    session_id: str,
    user_id: Optional[str],
    entity_id: Optional[str],
) -> None:
    now = int(time.time())
    kwargs: Dict[str, Any] = {
        "session_id": session_id,
        "user_id": user_id,
        "created_at": now,
        "updated_at": now,
    }
    if entity_id:
        kwargs[cfg.id_field] = entity_id
    session = cfg.session_cls(**kwargs)
    if cfg.is_async_db:
        await cfg.db.upsert_session(session, deserialize=False)
    else:
        await asyncio.to_thread(cfg.db.upsert_session, session, deserialize=False)
