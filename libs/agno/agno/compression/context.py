from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Set


@dataclass
class CompressedContext:
    content: str
    message_ids: Set[str] = field(default_factory=set)
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "message_ids": list(self.message_ids),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompressedContext":
        updated_at = data.get("updated_at")
        return cls(
            content=data["content"],
            message_ids=set(data.get("message_ids", [])),
            updated_at=datetime.fromisoformat(updated_at) if updated_at else None,
        )
