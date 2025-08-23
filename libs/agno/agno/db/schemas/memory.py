from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class UserMemory:
    """Model for User Memories"""

    memory: str
    memory_id: Optional[str] = None
    topics: Optional[List[str]] = None
    user_id: Optional[str] = None
    input: Optional[str] = None
    updated_at: Optional[datetime] = None
    feedback: Optional[str] = None

    agent_id: Optional[str] = None
    team_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        _dict = {
            "memory_id": self.memory_id,
            "memory": self.memory,
            "topics": self.topics,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "input": self.input,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "team_id": self.team_id,
            "feedback": self.feedback,
        }
        return {k: v for k, v in _dict.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserMemory":
        data = dict(data)

        # Convert updated_at to datetime
        if updated_at := data.get("updated_at"):
            if isinstance(updated_at, (int, float)):
                data["updated_at"] = datetime.fromtimestamp(updated_at, tz=timezone.utc)
            else:
                data["updated_at"] = datetime.fromisoformat(updated_at)

        return cls(**data)
