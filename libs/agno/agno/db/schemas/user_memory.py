from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agno.utils.dttm import now_epoch_s, to_epoch_s


@dataclass
class UserMemoryV2:
    """Model for User Memory (v2)

    Stores user-specific memory including:
    - profile: WHO the user is (name, company, role, tone preferences)
    - layers: Policies, knowledge, and feedback
    """

    # Primary key - unique user identifier
    user_id: str

    # User profile information (name, company, role, tone preferences, etc.)
    profile: Dict[str, Any] = field(default_factory=dict)

    # Memory layers (policies, knowledge, feedback)
    layers: Dict[str, Any] = field(default_factory=dict)

    # Optional metadata
    metadata: Optional[Dict[str, Any]] = None

    # Timestamps (epoch seconds)
    created_at: Optional[int] = field(default=None)
    updated_at: Optional[int] = field(default=None)

    def __post_init__(self):
        if not self.user_id or not self.user_id.strip():
            raise ValueError("user_id must be a non-empty string")
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)
        self.updated_at = self.created_at if self.updated_at is None else to_epoch_s(self.updated_at)

    def bump_updated_at(self) -> None:
        """Bump updated_at to now (UTC)."""
        self.updated_at = now_epoch_s()

    def preview(self) -> Dict[str, Any]:
        """Return a preview of the user memory."""
        _preview: Dict[str, Any] = {
            "user_id": self.user_id,
        }
        if self.profile:
            for key in ["name", "company", "role"]:
                if key in self.profile:
                    _preview[key] = self.profile[key]
        policies = self.layers.get("policies", {})
        knowledge = self.layers.get("knowledge", {})
        feedback = self.layers.get("feedback", {})
        if policies:
            _preview["has_policies"] = True
        if knowledge:
            _preview["knowledge_count"] = len(knowledge.keys())
        if feedback:
            feedback_count = len(feedback.get("positive", [])) + len(feedback.get("negative", []))
            _preview["feedback_count"] = feedback_count
        return _preview

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        _dict = {
            "user_id": self.user_id,
            "profile": self.profile,
            "layers": self.layers,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return {k: v for k, v in _dict.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserMemoryV2":
        """Create from dictionary."""
        d = dict(data)

        # Preserve 0 and None explicitly; only process if key exists
        if "created_at" in d and d["created_at"] is not None:
            d["created_at"] = to_epoch_s(d["created_at"])
        if "updated_at" in d and d["updated_at"] is not None:
            d["updated_at"] = to_epoch_s(d["updated_at"])

        return cls(**d)
