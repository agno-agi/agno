"""V1 memory schema compatibility stubs."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from agno.memory.manager import UserMemory as V2UserMemory


@dataclass
class SessionSummary:
    """V1-compatible session summary dataclass."""

    session_id: str
    user_id: str
    summary: str
    key_points: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "summary": self.summary,
            "key_points": self.key_points,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionSummary":
        """Create from dictionary."""
        return cls(
            session_id=data["session_id"],
            user_id=data["user_id"],
            summary=data["summary"],
            key_points=data.get("key_points", []),
            created_at=datetime.fromisoformat(data["created_at"])
            if isinstance(data["created_at"], str)
            else data["created_at"],
            updated_at=datetime.fromisoformat(data["updated_at"])
            if isinstance(data["updated_at"], str)
            else data["updated_at"],
            metadata=data.get("metadata", {}),
        )


# UserMemory: Re-export V2 version for compatibility
UserMemory = V2UserMemory

__all__ = ["SessionSummary", "UserMemory"]
