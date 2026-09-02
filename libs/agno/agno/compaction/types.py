"""Result types for conversation compaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any, Dict, Optional

# The namespace prefix every compaction archive lives under. Sibling to the
# "tool-results" prefix result offloading uses, so one database backs both
# without either being able to read the other's files.
ARCHIVE_NAMESPACE_PREFIX = "history"


@dataclass
class CompactionRecord:
    """What one compaction did: the summary, and where the originals went.

    Persisted as a row in ``agno_compactions`` so a later run replays the fold rather than paying
    for it again. ``archived`` is False when the transcript could not be stored - a database that
    does not implement the optional contract, or a write that failed. The summary still stands; it
    is simply no longer recoverable in full, which is why the two are separate.
    """

    # Number of history messages this compaction replaced.
    messages_compacted: int
    # The generated summary that stands in for them.
    summary: str
    # Id of the first message kept verbatim - the boundary anchor.
    #
    # An id, not an index: history is rebuilt from stored runs on every run, so a positional
    # boundary means something different each time the list grows and the cut silently crawls.
    # An id resolves to the same message forever, or fails to resolve at all - in which case the
    # view falls open to the full list rather than cutting in the wrong place.
    first_kept_message_id: Optional[str] = None
    # Id of the first message whose tool results are kept in full. Tool results *before* it
    # render as a short placeholder in the view - a cheap, no-inference tier that reclaims the
    # bulk of a tool-heavy transcript without paying a summarizer for it. The transcript itself
    # is untouched; only the view elides.
    elision_watermark_message_id: Optional[str] = None
    # Row id of this record, and the run that produced it. Together they make the record a fact
    # about one run rather than a value shared by the session.
    id: Optional[str] = None
    run_id: Optional[str] = None
    # Whether the folded transcript was stored alongside this record.
    archived: bool = False
    tokens_before: Optional[int] = None
    tokens_after: Optional[int] = None
    # Stamped at construction: the row requires it, and a record without a time cannot be
    # ordered in the chain that resolves which fold is in force.
    created_at: int = field(default_factory=lambda: int(time()))

    def to_dict(self) -> Dict[str, Any]:
        _dict = {
            "messages_compacted": self.messages_compacted,
            "summary": self.summary,
            "first_kept_message_id": self.first_kept_message_id,
            "elision_watermark_message_id": self.elision_watermark_message_id,
            "id": self.id,
            "run_id": self.run_id,
            "archived": self.archived,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "created_at": self.created_at,
        }
        return {k: v for k, v in _dict.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompactionRecord":
        return cls(
            messages_compacted=data.get("messages_compacted", 0),
            summary=data.get("summary", ""),
            first_kept_message_id=data.get("first_kept_message_id"),
            elision_watermark_message_id=data.get("elision_watermark_message_id"),
            id=data.get("id") or data.get("compaction_id"),
            run_id=data.get("run_id"),
            archived=bool(data.get("archived") or data.get("archived_messages")),
            tokens_before=data.get("tokens_before"),
            tokens_after=data.get("tokens_after"),
            created_at=data.get("created_at") or int(time()),
        )


@dataclass
class CompactionStats:
    """Running totals for one agent, rendered after a run."""

    compactions: int = 0
    messages_compacted: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    def record(self, record: CompactionRecord) -> None:
        self.compactions += 1
        self.messages_compacted += record.messages_compacted
        self.tokens_before += record.tokens_before or 0
        self.tokens_after += record.tokens_after or 0

    def clear(self) -> None:
        self.compactions = 0
        self.messages_compacted = 0
        self.tokens_before = 0
        self.tokens_after = 0
        self.extra.clear()


__all__ = ["ARCHIVE_NAMESPACE_PREFIX", "CompactionRecord", "CompactionStats"]
