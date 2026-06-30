from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from typing_extensions import List


@dataclass
class CulturalKnowledge:
    """Model for Cultural Knowledge

    Notice: Culture is an experimental feature and is subject to change.
    """

    # The id of the cultural knowledge, auto-generated if not provided
    id: Optional[str] = None
    name: Optional[str] = None

    content: Optional[str] = None
    categories: Optional[List[str]] = None
    notes: Optional[List[str]] = None

    summary: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    input: Optional[str] = None

    created_at: Optional[int] = field(default=None)
    updated_at: Optional[int] = field(default=None)

    agent_id: Optional[str] = None
    team_id: Optional[str] = None

    def __post_init__(self):
        if self.name is not None and not self.name.strip():
            raise ValueError("name must be a non-empty string")
        self.created_at = _now_epoch_s() if self.created_at is None else _to_epoch_s(self.created_at)
        self.updated_at = self.created_at if self.updated_at is None else _to_epoch_s(self.updated_at)

    def bump_updated_at(self) -> None:
        """Bump updated_at to now (UTC)."""
        self.updated_at = _now_epoch_s()

    def preview(self) -> Dict[str, Any]:
        """Return a preview of the cultural knowledge"""
        _preview: Dict[str, Any] = {
            "name": self.name,
        }
        if self.categories is not None:
            _preview["categories"] = self.categories
        if self.summary is not None:
            _preview["summary"] = self.summary[:100] + "..." if len(self.summary) > 100 else self.summary
        if self.content is not None:
            _preview["content"] = self.content[:100] + "..." if len(self.content) > 100 else self.content
        if self.notes is not None:
            _preview["notes"] = [note[:100] + "..." if len(note) > 100 else note for note in self.notes]
        return _preview

    def to_dict(self) -> Dict[str, Any]:
        _dict = {
            "id": self.id,
            "name": self.name,
            "summary": self.summary,
            "content": self.content,
            "categories": self.categories,
            "metadata": self.metadata,
            "notes": self.notes,
            "input": self.input,
            "created_at": (_epoch_to_rfc3339_z(self.created_at) if self.created_at is not None else None),
            "updated_at": (_epoch_to_rfc3339_z(self.updated_at) if self.updated_at is not None else None),
            "agent_id": self.agent_id,
            "team_id": self.team_id,
        }
        return {k: v for k, v in _dict.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CulturalKnowledge":
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
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError as e:
            raise ValueError(f"Unsupported datetime string: {value!r}") from e
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())

    raise TypeError(f"Unsupported datetime value: {type(value)}")


def _epoch_to_rfc3339_z(ts: Union[int, float]) -> str:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat().replace("+00:00", "Z")
