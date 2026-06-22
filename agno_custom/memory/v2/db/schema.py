"""V1 memory row schema compatibility stub.

V1 had: agno.memory.v2.db.schema.MemoryRow
V2 uses: Different data structures

This stub provides a V1-compatible interface for MemoryRow.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class MemoryRow:
    """V1-compatible memory row dataclass.

    This is a stub providing the V1 interface that agno_custom expects.
    """

    id: str
    user_id: str
    memory_type: str
    content: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "memory_type": self.memory_type,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
            "embedding": self.embedding,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryRow":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            memory_type=data["memory_type"],
            content=data["content"],
            created_at=datetime.fromisoformat(data["created_at"])
            if isinstance(data["created_at"], str)
            else data["created_at"],
            updated_at=datetime.fromisoformat(data["updated_at"])
            if isinstance(data["updated_at"], str)
            else data["updated_at"],
            metadata=data.get("metadata", {}),
            embedding=data.get("embedding"),
        )
