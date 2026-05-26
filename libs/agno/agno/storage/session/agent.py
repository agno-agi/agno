"""V1 agent session storage compatibility stub."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class AgentSession:
    """V1-compatible agent session stub."""

    session_id: str
    agent_id: str
    user_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentSession":
        """Create from dictionary."""
        return cls(
            session_id=data["session_id"],
            agent_id=data["agent_id"],
            user_id=data["user_id"],
            metadata=data.get("metadata", {}),
        )
