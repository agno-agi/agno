from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class CompactionState:
    """Tracks context compaction state for a session."""

    # The accumulated summary of compacted messages
    summary: str
    # Total number of messages that have been compacted
    compacted_count: int = 0
    # Number of compaction operations performed
    total_compactions: int = 0
    # When the state was last updated
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "compacted_count": self.compacted_count,
            "total_compactions": self.total_compactions,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompactionState":
        updated_at = data.get("updated_at")
        if updated_at and isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        return cls(
            summary=data.get("summary", ""),
            compacted_count=data.get("compacted_count", 0),
            total_compactions=data.get("total_compactions", 0),
            updated_at=updated_at,
        )
