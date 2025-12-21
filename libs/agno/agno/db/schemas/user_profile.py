from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union


@dataclass
class UserProfile:
    """Model for User Profile with Memory Layers

    Stores user-specific memory including:
    - user_profile: WHO the user is (name, company, role, tone preferences)
    - memory_layers: Policies, knowledge, and feedback
    """

    # Primary key - unique user identifier
    user_id: str

    # User profile information (name, company, role, tone preferences, etc.)
    user_profile: Dict[str, Any] = field(default_factory=dict)

    # Memory layers (policies, knowledge, feedback)
    memory_layers: Dict[str, Any] = field(default_factory=dict)

    # Optional metadata
    metadata: Optional[Dict[str, Any]] = None

    # Timestamps
    created_at: Optional[int] = field(default=None)
    updated_at: Optional[int] = field(default=None)

    def __post_init__(self):
        if not self.user_id or not self.user_id.strip():
            raise ValueError("user_id must be a non-empty string")
        self.created_at = _now_epoch_s() if self.created_at is None else _to_epoch_s(self.created_at)
        self.updated_at = self.created_at if self.updated_at is None else _to_epoch_s(self.updated_at)

    def bump_updated_at(self) -> None:
        """Bump updated_at to now (UTC)."""
        self.updated_at = _now_epoch_s()

    # Properties for convenient access to memory_layers
    @property
    def policies(self) -> Dict[str, Any]:
        """Get user policies from memory_layers."""
        return self.memory_layers.get("policies", {})

    @property
    def knowledge(self) -> List[Dict[str, Any]]:
        """Get user knowledge from memory_layers."""
        return self.memory_layers.get("knowledge", [])

    @property
    def feedback(self) -> Dict[str, Any]:
        """Get user feedback from memory_layers (dict with 'positive' and 'negative' lists)."""
        return self.memory_layers.get("feedback", {})

    def preview(self) -> Dict[str, Any]:
        """Return a preview of the user profile."""
        _preview: Dict[str, Any] = {
            "user_id": self.user_id,
        }
        if self.user_profile:
            for key in ["name", "company", "role"]:
                if key in self.user_profile:
                    _preview[key] = self.user_profile[key]
        if self.policies:
            _preview["has_policies"] = True
        if self.knowledge:
            _preview["knowledge_count"] = len(self.knowledge)
        if self.feedback:
            feedback_count = 0
            if isinstance(self.feedback, dict):
                feedback_count = len(self.feedback.get("positive", [])) + len(self.feedback.get("negative", []))
            _preview["feedback_count"] = feedback_count
        return _preview

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        _dict = {
            "user_id": self.user_id,
            "user_profile": self.user_profile,
            "memory_layers": self.memory_layers,
            "metadata": self.metadata,
            "created_at": (_epoch_to_rfc3339_z(self.created_at) if self.created_at is not None else None),
            "updated_at": (_epoch_to_rfc3339_z(self.updated_at) if self.updated_at is not None else None),
        }
        return {k: v for k, v in _dict.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfile":
        """Create from dictionary."""
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
