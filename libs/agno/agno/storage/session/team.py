"""V1 team session storage compatibility stub."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class TeamSession:
    """V1-compatible team session stub."""

    session_id: str
    team_id: str
    user_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "team_id": self.team_id,
            "user_id": self.user_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TeamSession":
        """Create from dictionary."""
        return cls(
            session_id=data["session_id"],
            team_id=data["team_id"],
            user_id=data["user_id"],
            metadata=data.get("metadata", {}),
        )
