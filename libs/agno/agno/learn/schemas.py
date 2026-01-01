"""
LearningMachine Schemas
=======================
Base dataclasses for each learning type.

Uses pure dataclasses to avoid runtime overhead.
All parsing is done via from_dict() which never raises.

Base classes are designed to be extended - from_dict() and to_dict()
automatically handle subclass fields via dataclasses.fields().

Schema Hierarchy:
- BaseUserProfile: Long-term user memory
- BaseSessionContext: Current session state
- BaseLearning: Reusable knowledge/insights
- BaseDecision: Decision logs (Phase 2)
- BaseFeedback: Behavioral feedback (Phase 2)
- BaseInstructionUpdate: Self-improvement (Phase 3)
"""

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional

# =============================================================================
# Internal Helpers
# =============================================================================


def _safe_get(data: Any, key: str, default: Any = None) -> Any:
    """Safely get a key from dict-like data."""
    if isinstance(data, dict):
        return data.get(key, default)
    return getattr(data, key, default)


def _parse_json(data: Any) -> Optional[Dict]:
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
# User Profile Schema
# =============================================================================


@dataclass
class BaseUserProfile:
    """Base schema for User Profile learning type.

    Captures long-term information about a user that persists
    across sessions. Designed to be extended with custom fields.

    Attributes:
        user_id: Required unique identifier for the user.
        name: User's name (if known).
        preferred_name: How they prefer to be addressed.
        memories: List of memory entries, each with 'id' and 'content'.

    Example - Extending with custom fields:
        @dataclass
        class MyUserProfile(BaseUserProfile):
            company: Optional[str] = None
            role: Optional[str] = None
            timezone: Optional[str] = None
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
            parsed = _parse_json(data)
            if not parsed:
                return None

            # user_id is required
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

    def add_memory(self, content: str, **kwargs) -> str:
        """Add a new memory to the profile.

        Args:
            content: The memory text to add.
            **kwargs: Additional fields (source, timestamp, etc.)

        Returns:
            The generated memory ID.
        """
        import uuid

        memory_id = str(uuid.uuid4())[:8]

        if content and content.strip():
            self.memories.append({"id": memory_id, "content": content.strip(), **kwargs})

        return memory_id

    def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific memory by ID."""
        for mem in self.memories:
            if isinstance(mem, dict) and mem.get("id") == memory_id:
                return mem
        return None

    def update_memory(self, memory_id: str, content: str, **kwargs) -> bool:
        """Update an existing memory.

        Returns:
            True if memory was found and updated, False otherwise.
        """
        for mem in self.memories:
            if isinstance(mem, dict) and mem.get("id") == memory_id:
                mem["content"] = content.strip()
                mem.update(kwargs)
                return True
        return False

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory by ID.

        Returns:
            True if memory was found and deleted, False otherwise.
        """
        original_len = len(self.memories)
        self.memories = [mem for mem in self.memories if not (isinstance(mem, dict) and mem.get("id") == memory_id)]
        return len(self.memories) < original_len

    def get_memories_text(self) -> str:
        """Get all memories as a formatted string for prompts."""
        if not self.memories:
            return ""

        lines = []
        for m in self.memories:
            content = m.get("content") if isinstance(m, dict) else str(m)
            if content:
                lines.append(f"- {content}")

        return "\n".join(lines)


# =============================================================================
# Session Context Schema
# =============================================================================


@dataclass
class BaseSessionContext:
    """Base schema for Session Context learning type.

    Captures state and summary for the current session.
    Unlike UserProfile which accumulates, this is REPLACED on each update.

    Attributes:
        session_id: Required unique identifier for the session.
        summary: What's happened in this session.
        goal: What the user is trying to accomplish.
        plan: Steps to achieve the goal.
        progress: Which steps have been completed.

    Example - Extending with custom fields:
        @dataclass
        class MySessionContext(BaseSessionContext):
            mood: Optional[str] = None
            blockers: List[str] = field(default_factory=list)
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
            parsed = _parse_json(data)
            if not parsed:
                return None

            # session_id is required
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
        """Get session context as a formatted string for prompts."""
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
            parts.append(f"Completed:\n{progress_text}")

        return "\n\n".join(parts)


# =============================================================================
# Learned Knowledge Schema
# =============================================================================


@dataclass
class BaseLearning:
    """Base schema for Learned Knowledge learning type.

    Captures reusable insights and patterns that can be shared
    across users and potentially across agents.

    Attributes:
        title: Short descriptive title.
        learning: The actual insight or knowledge.
        context: When/where this applies.
        tags: Categories for this learning.

    Example - Extending with custom fields:
        @dataclass
        class MyLearning(BaseLearning):
            confidence: float = 1.0
            source_conversation_id: Optional[str] = None
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
            parsed = _parse_json(data)
            if not parsed:
                return None

            # title and learning are required
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
        """Convert learning to searchable text format for vector storage."""
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
    """Response model for user profile extraction from LLM.

    Used internally by UserProfileStore during background extraction.
    """

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
            parsed = _parse_json(data)
            if not parsed:
                return None

            return cls(
                name=_safe_get(parsed, "name"),
                preferred_name=_safe_get(parsed, "preferred_name"),
                new_memories=_safe_get(parsed, "new_memories") or [],
            )
        except Exception:
            return None


@dataclass
class SessionSummaryExtractionResponse:
    """Response model for summary-only session extraction from LLM."""

    summary: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> Optional["SessionSummaryExtractionResponse"]:
        """Parse from dict/JSON, returning None on any failure."""
        if data is None:
            return None
        if isinstance(data, cls):
            return data

        try:
            parsed = _parse_json(data)
            if not parsed:
                return None

            return cls(summary=_safe_get(parsed, "summary") or "")
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
            parsed = _parse_json(data)
            if not parsed:
                return None

            return cls(
                summary=_safe_get(parsed, "summary") or "",
                goal=_safe_get(parsed, "goal"),
                plan=_safe_get(parsed, "plan"),
                progress=_safe_get(parsed, "progress"),
            )
        except Exception:
            return None


# =============================================================================
# Phase 2 Schemas (Placeholders)
# =============================================================================


@dataclass
class BaseDecision:
    """Base schema for Decision Logs. (Phase 2)

    Records decisions made by the agent with reasoning and context.
    """

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
            parsed = _parse_json(data)
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
    """Base schema for Behavioral Feedback. (Phase 2)

    Captures signals about what worked and what didn't.
    """

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
            parsed = _parse_json(data)
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
    """Base schema for Self-Improvement. (Phase 3)

    Proposes updates to agent instructions based on feedback patterns.
    """

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
            parsed = _parse_json(data)
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
