from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union


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
    metadata: Optional[Dict[str, Any]] = None
    variables: Optional[List[str]] = None  # Extracted from content
    # Optimization tracking
    version: int = 1
    parent_id: Optional[str] = None  # Track optimization lineage
    optimization_notes: Optional[str] = None

    # Timestamps
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    def __post_init__(self):
        """Automatically set timestamps if not provided."""
        self.created_at = _now_epoch_s() if self.created_at is None else _to_epoch_s(self.created_at)
        self.updated_at = self.created_at if self.updated_at is None else _to_epoch_s(self.updated_at)

    def bump_updated_at(self) -> None:
        """Bump updated_at to now (UTC)."""
        self.updated_at = _now_epoch_s()

    def to_dict(self) -> Dict[str, Any]:
        _dict = {
            "id": self.id,
            "name": self.name,
            "content": self.content,
            "description": self.description,
            "metadata": self.metadata,
            "variables": self.variables,
            "version": self.version,
            "parent_id": self.parent_id,
            "optimization_notes": self.optimization_notes,
            "created_at": _epoch_to_rfc3339_z(self.created_at) if self.created_at is not None else None,
            "updated_at": _epoch_to_rfc3339_z(self.updated_at) if self.updated_at is not None else None,
        }
        return {k: v for k, v in _dict.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextItem":
        d = dict(data)

        # Preserve 0 and None explicitly; only process if key exists
        if "created_at" in d and d["created_at"] is not None:
            d["created_at"] = _to_epoch_s(d["created_at"])
        if "updated_at" in d and d["updated_at"] is not None:
            d["updated_at"] = _to_epoch_s(d["updated_at"])

        return cls(**d)


def _now_epoch_s() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _to_epoch_s(value: Union[int, float, str, datetime]) -> int:
    """Normalize various datetime representations to epoch seconds (UTC)."""
    if isinstance(value, (int, float)):
        # assume value is already in seconds
        return int(value)

    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())

    if isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())

    raise ValueError(f"Cannot convert {type(value).__name__} to epoch seconds")


def _epoch_to_rfc3339_z(epoch_s: int) -> str:
    return datetime.fromtimestamp(epoch_s, tz=timezone.utc).isoformat().replace("+00:00", "Z")
