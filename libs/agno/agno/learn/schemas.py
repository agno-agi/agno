"""
LearningMachine Schemas
=======================
Base dataclasses for each learning type.

Uses pure dataclasses to avoid runtime overhead.
All parsing is done via from_dict() which never raises.

Base classes are designed to be extended - from_dict() and to_dict()
automatically handle subclass fields via dataclasses.fields().
"""

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional


def safe_get(data: Any, key: str, default: Any = None) -> Any:
    """Safely get a key from dict-like data."""
    if isinstance(data, dict):
        return data.get(key, default)
    return getattr(data, key, default)


def parse_json(data: Any) -> Optional[Dict]:
    """Parse JSON string to dict, or return dict as-is."""
    if data is None:
        return None
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        import json

        try:
            return json.loads(data)
        except Exception:
            return None
    return None


# =============================================================================
# User Profile
# =============================================================================


@dataclass
class BaseUserProfile:
    """Base schema for User Profile learning type.

    Captures long-term information about a user that persists
    across sessions. Extend this class to add custom fields.

    Example:
        @dataclass
        class MyUserProfile(BaseUserProfile):
            company: Optional[str] = None
            role: Optional[str] = None
    """

    user_id: str
    name: Optional[str] = None
    preferred_name: Optional[str] = None
    memories: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Any) -> Optional["BaseUserProfile"]:
        """Parse from dict/JSON, returning None on any failure.

        Works with subclasses - automatically handles additional fields.
        """
        if data is None:
            return None
        if isinstance(data, cls):
            return data

        try:
            parsed = parse_json(data)
            if not parsed:
                return None

            if not parsed.get("user_id"):
                return None

            # Get field names for this class (includes subclass fields)
            field_names = {f.name for f in fields(cls)}
            kwargs = {k: v for k, v in parsed.items() if k in field_names}

            return cls(**kwargs)
        except Exception:
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict. Works with subclasses."""
        try:
            return asdict(self)
        except Exception:
            return {}

    def add_memory(self, content: str, **kwargs) -> None:
        """Add a new memory to the profile."""
        if content and content.strip():
            self.memories.append({"content": content.strip(), **kwargs})

    def get_memories_text(self) -> str:
        """Get all memories as a formatted string."""
        if not self.memories:
            return ""
        lines = []
        for m in self.memories:
            content = m.get("content") if isinstance(m, dict) else str(m)
            if content:
                lines.append(f"- {content}")
        return "\n".join(lines)


# =============================================================================
# Session Context
# =============================================================================


@dataclass
class BaseSessionContext:
    """Base schema for Session Context learning type.

    Captures state and summary for the current session.
    Extend this class to add custom fields.
    """

    session_id: str
    summary: Optional[str] = None
    goal: Optional[str] = None
    plan: Optional[List[str]] = None
    progress: Optional[List[str]] = None

    @classmethod
    def from_dict(cls, data: Any) -> Optional["BaseSessionContext"]:
        """Parse from dict/JSON, returning None on any failure."""
        if data is None:
            return None
        if isinstance(data, cls):
            return data

        try:
            parsed = parse_json(data)
            if not parsed:
                return None

            if not parsed.get("session_id"):
                return None

            field_names = {f.name for f in fields(cls)}
            kwargs = {k: v for k, v in parsed.items() if k in field_names}

            return cls(**kwargs)
        except Exception:
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        try:
            return asdict(self)
        except Exception:
            return {}

    def get_context_text(self) -> str:
        """Get session context as a formatted string."""
        parts = []

        if self.summary:
            parts.append(f"Summary: {self.summary}")

        if self.goal:
            parts.append(f"Goal: {self.goal}")

        if self.plan:
            plan_text = "\n".join(f"  {i + 1}. {step}" for i, step in enumerate(self.plan))
            parts.append(f"Plan:\n{plan_text}")

        if self.progress:
            progress_text = "\n".join(f"  ✓ {step}" for step in self.progress)
            parts.append(f"Progress:\n{progress_text}")

        return "\n".join(parts)


# =============================================================================
# Learned Knowledge
# =============================================================================


@dataclass
class BaseLearning:
    """Base schema for Learned Knowledge learning type.

    Captures reusable insights and patterns.
    Extend this class to add custom fields.
    """

    title: str
    learning: str
    context: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Any) -> Optional["BaseLearning"]:
        """Parse from dict/JSON, returning None on any failure."""
        if data is None:
            return None
        if isinstance(data, cls):
            return data

        try:
            parsed = parse_json(data)
            if not parsed:
                return None

            if not parsed.get("title") or not parsed.get("learning"):
                return None

            field_names = {f.name for f in fields(cls)}
            kwargs = {k: v for k, v in parsed.items() if k in field_names}

            return cls(**kwargs)
        except Exception:
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        try:
            return asdict(self)
        except Exception:
            return {}

    def to_text(self) -> str:
        """Convert learning to searchable text format."""
        parts = [f"Title: {self.title}", f"Learning: {self.learning}"]
        if self.context:
            parts.append(f"Context: {self.context}")
        if self.tags:
            parts.append(f"Tags: {', '.join(self.tags)}")
        return "\n".join(parts)


# =============================================================================
# Extraction Response Models (internal use by stores)
# =============================================================================


@dataclass
class UserProfileExtractionResponse:
    """Response model for user profile extraction from LLM."""

    name: Optional[str] = None
    preferred_name: Optional[str] = None
    new_memories: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Any) -> Optional["UserProfileExtractionResponse"]:
        """Parse from dict/JSON, returning None on any failure."""
        if data is None:
            return None
        if isinstance(data, cls):
            return data

        try:
            parsed = parse_json(data)
            if not parsed:
                return None

            return cls(
                name=safe_get(parsed, "name"),
                preferred_name=safe_get(parsed, "preferred_name"),
                new_memories=safe_get(parsed, "new_memories") or [],
            )
        except Exception:
            return None


@dataclass
class SessionSummaryExtractionResponse:
    """Response model for summary-only extraction from LLM."""

    summary: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> Optional["SessionSummaryExtractionResponse"]:
        """Parse from dict/JSON, returning None on any failure."""
        if data is None:
            return None
        if isinstance(data, cls):
            return data

        try:
            parsed = parse_json(data)
            if not parsed:
                return None

            return cls(summary=safe_get(parsed, "summary") or "")
        except Exception:
            return None


@dataclass
class SessionPlanningExtractionResponse:
    """Response model for full planning extraction from LLM."""

    summary: str = ""
    goal: Optional[str] = None
    plan: Optional[List[str]] = None
    progress: Optional[List[str]] = None

    @classmethod
    def from_dict(cls, data: Any) -> Optional["SessionPlanningExtractionResponse"]:
        """Parse from dict/JSON, returning None on any failure."""
        if data is None:
            return None
        if isinstance(data, cls):
            return data

        try:
            parsed = parse_json(data)
            if not parsed:
                return None

            return cls(
                summary=safe_get(parsed, "summary") or "",
                goal=safe_get(parsed, "goal"),
                plan=safe_get(parsed, "plan"),
                progress=safe_get(parsed, "progress"),
            )
        except Exception:
            return None


# =============================================================================
# Phase 2 Schemas
# =============================================================================


@dataclass
class BaseDecision:
    """Base schema for Decision Logs. (Phase 2)"""

    decision: str
    reasoning: Optional[str] = None
    context: Optional[str] = None
    outcome: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Any) -> Optional["BaseDecision"]:
        if data is None:
            return None
        if isinstance(data, cls):
            return data

        try:
            parsed = parse_json(data)
            if not parsed or not parsed.get("decision"):
                return None

            field_names = {f.name for f in fields(cls)}
            kwargs = {k: v for k, v in parsed.items() if k in field_names}

            return cls(**kwargs)
        except Exception:
            return None

    def to_dict(self) -> Dict[str, Any]:
        try:
            return asdict(self)
        except Exception:
            return {}


@dataclass
class BaseFeedback:
    """Base schema for Behavioral Feedback. (Phase 2)"""

    signal: str  # thumbs_up, thumbs_down, correction, regeneration
    learning: Optional[str] = None
    context: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Any) -> Optional["BaseFeedback"]:
        if data is None:
            return None
        if isinstance(data, cls):
            return data

        try:
            parsed = parse_json(data)
            if not parsed or not parsed.get("signal"):
                return None

            field_names = {f.name for f in fields(cls)}
            kwargs = {k: v for k, v in parsed.items() if k in field_names}

            return cls(**kwargs)
        except Exception:
            return None

    def to_dict(self) -> Dict[str, Any]:
        try:
            return asdict(self)
        except Exception:
            return {}


@dataclass
class BaseInstructionUpdate:
    """Base schema for Self-Improvement. (Phase 4)"""

    current_instruction: str
    proposed_instruction: str
    reasoning: str
    evidence: Optional[List[str]] = None

    @classmethod
    def from_dict(cls, data: Any) -> Optional["BaseInstructionUpdate"]:
        if data is None:
            return None
        if isinstance(data, cls):
            return data

        try:
            parsed = parse_json(data)
            if not parsed:
                return None

            required = ["current_instruction", "proposed_instruction", "reasoning"]
            if not all(parsed.get(k) for k in required):
                return None

            field_names = {f.name for f in fields(cls)}
            kwargs = {k: v for k, v in parsed.items() if k in field_names}

            return cls(**kwargs)
        except Exception:
            return None

    def to_dict(self) -> Dict[str, Any]:
        try:
            return asdict(self)
        except Exception:
            return {}
