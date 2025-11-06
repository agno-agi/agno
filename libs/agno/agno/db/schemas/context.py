from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class ContextItem:
    """Model for Context Item (Prompt/Instruction)

    **Context is an experimental feature**
    """

    # Required fields
    name: str  # Unique identifier for this context item
    content: str  # The prompt content

    # Optional fields
    id: Optional[str] = None  # Auto-generated if not provided
    description: Optional[str] = None
    label: Optional[str] = None  # e.g., "production", "development", "optimized"
    variables: Optional[List[str]] = None  # Extracted from content
    # Optimization tracking
    version: int = 1
    parent_id: Optional[str] = None  # Track optimization lineage
    optimization_notes: Optional[str] = None

    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        _dict = {
            "id": self.id,
            "name": self.name,
            "content": self.content,
            "description": self.description,
            "label": self.label,
            "variables": self.variables,
            "version": self.version,
            "parent_id": self.parent_id,
            "optimization_notes": self.optimization_notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        return {k: v for k, v in _dict.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextItem":
        data = dict(data)

        # Convert timestamps to datetime
        if created_at := data.get("created_at"):
            if isinstance(created_at, (int, float)):
                data["created_at"] = datetime.fromtimestamp(created_at, tz=timezone.utc)
            else:
                data["created_at"] = datetime.fromisoformat(created_at)

        if updated_at := data.get("updated_at"):
            if isinstance(updated_at, (int, float)):
                data["updated_at"] = datetime.fromtimestamp(updated_at, tz=timezone.utc)
            else:
                data["updated_at"] = datetime.fromisoformat(updated_at)

        return cls(**data)
