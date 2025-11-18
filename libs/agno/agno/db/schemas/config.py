from dataclasses import dataclass
from datetime import datetime

from typing import Any, Dict, Optional

@dataclass
class EntityConfig:
    id: str
    entity_id: str
    entity_type: str
    config: Dict[str, Any]
    version: str
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "config": self.config,
            "version": self.version,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntityConfig":
        return cls(
            id=data["id"],
            entity_id=data["entity_id"],
            entity_type=data["entity_type"],
            config=data["config"],
            version=data["version"],
            metadata=data["metadata"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )