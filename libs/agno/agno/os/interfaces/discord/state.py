from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Literal, Optional, Union

from agno.media import Audio, File, Image, Video
from agno.os.interfaces.discord.formatting import normalize_discord_markdown, normalize_for_streaming
from agno.os.interfaces.discord.helpers import (
    DC_CHUNK_SIZE,
    DC_MAX_EMBED_DESC,
    EMBED_COLOR_COMPLETE,
    EMBED_COLOR_ERROR,
    EMBED_COLOR_PROCESSING,
    build_status_embed,
    patch_webhook_message,
    post_followup_message,
)
from agno.os.interfaces.shared import (
    SessionStoreConfig,
    chunk_text,
    collect_media_from_chunk,
)
from agno.utils.log import log_warning

if TYPE_CHECKING:
    import aiohttp

    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput

# Rate limit for Discord webhook edits during streaming
DC_STREAM_EDIT_INTERVAL = 1.5

EntityType = Literal["agent", "team", "workflow"]
TaskStatus = Literal["in_progress", "complete", "error"]

# Discord caps embed fields at 25
_MAX_EMBED_FIELDS = 25


# Session scope builder


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
    # Thread types: PUBLIC_THREAD=11, PRIVATE_THREAD=12, ANNOUNCEMENT_THREAD=10
    if channel_type in (10, 11, 12):
        return f"dc:{entity_id}:thread:{channel_id}"
    return f"dc:{entity_id}:channel:{channel_id}:user:{user_id}"


# Task card — one embed field per tool call or reasoning step


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


# Bot-level state — shared across all interactions


@dataclass
class BotState:
    session_config: SessionStoreConfig
    entity_id: Optional[str] = None
    processed_interactions: Dict[str, float] = field(default_factory=dict)

    DEDUP_TTL_SECONDS: ClassVar[float] = 60.0

    def is_duplicate_interaction(self, interaction_id: str) -> bool:
        now = time.monotonic()
        # Insertion-ordered dict — break on first fresh entry
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


# Stream state — one per interaction response lifecycle


class StreamState:
    def __init__(
        self,
        http_session: "aiohttp.ClientSession",
        application_id: str,
        interaction_token: str,
        entity_type: EntityType,
        entity_name: str,
        error_message: str,
    ):
        self.http_session = http_session
        self.application_id = application_id
        self.interaction_token = interaction_token
        self.entity_type: EntityType = entity_type
        self.entity_name = entity_name
        self.error_message = error_message

        self._content_parts: List[str] = []
        self.task_cards: Dict[str, TaskCard] = {}
        self.last_edit_time: float = 0.0
        self.reasoning_round: int = 0
        self.error_count: int = 0
        self.terminal_status: Optional[TaskStatus] = None
        self.final_run_output: Optional[Union["RunOutput", "TeamRunOutput"]] = None
        self.workflow_final_content: Optional[str] = None
        self.images: List[Image] = []
        self.videos: List[Video] = []
        self.audio: List[Audio] = []
        self.files: List[File] = []

    # Content accumulation — list + join avoids O(n^2)

    @property
    def accumulated_content(self) -> str:
        return "".join(self._content_parts)

    @accumulated_content.setter
    def accumulated_content(self, value: str) -> None:
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

    def error_task(self, key: str, error_msg: str = "") -> None:
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

    def _build_embed(self, *, title: str, color: int, is_final: bool = False) -> Dict[str, Any]:
        description = ""
        if self._content_parts:
            content = self.accumulated_content
            # Full normalization only at finalize; streaming uses lightweight version
            normalized = normalize_discord_markdown(content) if is_final else normalize_for_streaming(content)
            description = normalized[:DC_MAX_EMBED_DESC]
        return build_status_embed(title=title, description=description, fields=self._build_fields(), color=color)

    # Display updates — rate-limited to avoid 429s

    async def update_display(self) -> None:
        now = time.monotonic()
        if now - self.last_edit_time < DC_STREAM_EDIT_INTERVAL:
            return
        embed = self._build_embed(title="Processing...", color=EMBED_COLOR_PROCESSING)
        try:
            await patch_webhook_message(self.http_session, self.application_id, self.interaction_token, embeds=[embed])
            self.last_edit_time = time.monotonic()
        except Exception as e:
            log_warning(f"Stream display update failed: {str(e)}")

    # Finalization

    async def finalize(self) -> None:
        self.resolve_all_pending()
        # terminal_status is authoritative; task card scan is fallback
        is_error = self.terminal_status == "error" or any(c.status == "error" for c in self.task_cards.values())
        title = "Error" if is_error else "Complete"
        color = EMBED_COLOR_ERROR if is_error else EMBED_COLOR_COMPLETE

        content = self.accumulated_content
        if not content and not self.task_cards:
            return

        normalized = normalize_discord_markdown(content) if content else ""
        try:
            await self._finalize_inner(normalized, title, color)
        except Exception as e:
            log_warning(f"Finalize failed, falling back to plain text: {str(e)}")
            await self._finalize_plaintext(normalized)

    async def _finalize_inner(self, normalized: str, title: str, color: int) -> None:
        fields = self._build_fields()
        if len(normalized) <= DC_MAX_EMBED_DESC:
            embed = build_status_embed(title=title, description=normalized, fields=fields, color=color)
            await patch_webhook_message(self.http_session, self.application_id, self.interaction_token, embeds=[embed])
            return
        # Content exceeds embed limit — truncated embed + overflow as follow-ups
        embed = build_status_embed(title=title, description=normalized[:DC_MAX_EMBED_DESC], fields=fields, color=color)
        await patch_webhook_message(self.http_session, self.application_id, self.interaction_token, embeds=[embed])
        for part in chunk_text(normalized[DC_MAX_EMBED_DESC:], DC_CHUNK_SIZE):
            await post_followup_message(self.http_session, self.application_id, self.interaction_token, content=part)

    async def _finalize_plaintext(self, normalized: str) -> None:
        if not normalized.strip():
            return
        try:
            for part in chunk_text(normalized, DC_CHUNK_SIZE):
                await post_followup_message(
                    self.http_session, self.application_id, self.interaction_token, content=part
                )
        except Exception as e:
            log_warning(f"Plain text fallback also failed: {str(e)}")
