from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from agno.utils.dttm import now_epoch_s, to_epoch_s


@dataclass
class UserMemory:
    """Model for User Memories"""

    memory: str
    memory_id: Optional[str] = None
    topics: Optional[List[str]] = None
    user_id: Optional[str] = None
    input: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None
    feedback: Optional[str] = None

    agent_id: Optional[str] = None
    team_id: Optional[str] = None

    def __post_init__(self) -> None:
        """Automatically set/normalize created_at and updated_at."""
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)
        if self.updated_at is not None:
            self.updated_at = to_epoch_s(self.updated_at)

    def to_dict(self) -> Dict[str, Any]:
        created_at = datetime.fromtimestamp(self.created_at).isoformat() if self.created_at is not None else None
        updated_at = datetime.fromtimestamp(self.updated_at).isoformat() if self.updated_at is not None else created_at
        _dict = {
            "memory_id": self.memory_id,
            "memory": self.memory,
            "topics": self.topics,
            "created_at": created_at,
            "updated_at": updated_at,
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

        # Preserve 0 and None explicitly; only process if key exists
        if "created_at" in data and data["created_at"] is not None:
            data["created_at"] = to_epoch_s(data["created_at"])
        if "updated_at" in data and data["updated_at"] is not None:
            data["updated_at"] = to_epoch_s(data["updated_at"])

        return cls(**data)
