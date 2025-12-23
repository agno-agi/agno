from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union


@dataclass
class OrganizationMemory:
    """Model for Organization Memory.

    Stores org-level memory including:
    - context: domain, terminology, product focus, org knowledge
    - policies: safety rules, behavior constraints, compliance rules
    """

    org_id: str
    memory_layers: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[int] = field(default=None)
    updated_at: Optional[int] = field(default=None)

    def __post_init__(self):
        if not self.org_id or not self.org_id.strip():
            raise ValueError("org_id must be a non-empty string")
        self.created_at = _now_epoch_s() if self.created_at is None else _to_epoch_s(self.created_at)
        self.updated_at = self.created_at if self.updated_at is None else _to_epoch_s(self.updated_at)

    def bump_updated_at(self) -> None:
        self.updated_at = _now_epoch_s()

    @property
    def context(self) -> Dict[str, Any]:
        return self.memory_layers.get("context", {})

    @property
    def policies(self) -> Dict[str, Any]:
        return self.memory_layers.get("policies", {})

    def to_dict(self) -> Dict[str, Any]:
        _dict = {
            "org_id": self.org_id,
            "memory_layers": self.memory_layers,
            "created_at": (_epoch_to_rfc3339_z(self.created_at) if self.created_at is not None else None),
            "updated_at": (_epoch_to_rfc3339_z(self.updated_at) if self.updated_at is not None else None),
        }
        return {k: v for k, v in _dict.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrganizationMemory":
        d = dict(data)
        if "created_at" in d and d["created_at"] is not None:
            d["created_at"] = _to_epoch_s(d["created_at"])
        if "updated_at" in d and d["updated_at"] is not None:
            d["updated_at"] = _to_epoch_s(d["updated_at"])
        return cls(**d)


def _now_epoch_s() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _to_epoch_s(value: Union[int, float, str, datetime]) -> int:
    if isinstance(value, (int, float)):
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
