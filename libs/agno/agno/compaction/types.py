"""Result types for conversation compaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# The namespace prefix every compaction archive lives under. Sibling to the
# "tool-results" prefix result offloading uses, so one database backs both
# without either being able to read the other's files.
ARCHIVE_NAMESPACE_PREFIX = "history"


@dataclass
class CompactionRecord:
    """What one compaction did: the summary, and where the originals went.

    Persisted in ``AgentSession.session_data`` so a later run reuses the
    summary instead of paying for it again. ``archive_path`` is None when the
    archive could not be written (a db that cannot back AgentFS, or a quota
    refusal); the summary still stands, it is simply no longer recoverable in
    full, which is why the two fields are separate.
    """

    # Number of history messages this compaction replaced.
    messages_compacted: int
    # The generated summary that stands in for them.
    summary: str
    # Index into the history list where the kept (verbatim) tail begins.
    boundary: int
    # Archive file holding the replaced messages verbatim, if one was written.
    archive_path: Optional[str] = None
    tokens_before: Optional[int] = None
    tokens_after: Optional[int] = None
    created_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        _dict = {
            "messages_compacted": self.messages_compacted,
            "summary": self.summary,
            "boundary": self.boundary,
            "archive_path": self.archive_path,
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
            boundary=data.get("boundary", 0),
            archive_path=data.get("archive_path"),
            tokens_before=data.get("tokens_before"),
            tokens_after=data.get("tokens_after"),
            created_at=data.get("created_at"),
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
