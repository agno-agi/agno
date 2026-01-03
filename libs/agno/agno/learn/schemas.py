"""
LearningMachine Schemas
=======================
Dataclasses for each learning type.

Uses pure dataclasses to avoid runtime overhead.
All parsing is done via from_dict() which never raises.

Classes are designed to be extended - from_dict() and to_dict()
automatically handle subclass fields via dataclasses.fields().

## Field Descriptions

When extending schemas, use field metadata to provide descriptions
that will be shown to the LLM:

    @dataclass
    class MyUserProfile(UserProfile):
        company: Optional[str] = field(
            default=None,
            metadata={"description": "Where they work"}
        )

The LLM will see this description when deciding how to update fields.

Schemas:
- UserProfile: Long-term user memory
- SessionContext: Current session state
- LearnedKnowledge: Reusable knowledge/insights
- Decision: Decision logs (Phase 2)
- Feedback: Behavioral feedback (Phase 2)
- InstructionUpdate: Self-improvement (Phase 3)
"""

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional

from agno.learn.utils import _parse_json, _safe_get

# =============================================================================
# User Profile Schema
# =============================================================================


@dataclass
class UserProfile:
    """Schema for User Profile learning type.

    Captures long-term information about a user that persists
    across sessions. Designed to be extended with custom fields.

    ## Two Types of Data

    1. **Profile Fields** (structured): name, preferred_name, and any
       custom fields you add. Use `update_profile` tool to set these.

    2. **Memories** (unstructured): Observations that don't fit fields.
       Use `add_memory`, `update_memory`, `delete_memory` tools.

    ## Extending with Custom Fields

    Use field metadata to provide descriptions for the LLM:

        @dataclass
        class MyUserProfile(UserProfile):
            company: Optional[str] = field(
                default=None,
                metadata={"description": "Company or organization they work for"}
            )
            role: Optional[str] = field(
                default=None,
                metadata={"description": "Job title or role"}
            )
            timezone: Optional[str] = field(
                default=None,
                metadata={"description": "User's timezone (e.g., America/New_York)"}
            )

    Attributes:
        user_id: Required unique identifier for the user.
        name: User's full name.
        preferred_name: How they prefer to be addressed (nickname, first name, etc).
        memories: List of memory entries, each with 'id' and 'content'.
        agent_id: Which agent created this profile.
        team_id: Which team created this profile.
        created_at: When the profile was created (ISO format).
        updated_at: When the profile was last updated (ISO format).
    """

    user_id: str
    name: Optional[str] = field(
        default=None,
        metadata={"description": "User's full name"}
    )
    preferred_name: Optional[str] = field(
        default=None,
        metadata={"description": "How they prefer to be addressed (nickname, first name, etc)"}
    )
    memories: List[Dict[str, Any]] = field(default_factory=list)
    agent_id: Optional[str] = field(default=None, metadata={"internal": True})
    team_id: Optional[str] = field(default=None, metadata={"internal": True})
    created_at: Optional[str] = field(default=None, metadata={"internal": True})
    updated_at: Optional[str] = field(default=None, metadata={"internal": True})

    @classmethod
    def from_dict(cls, data: Any) -> Optional["UserProfile"]:
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

    @classmethod
    def get_updateable_fields(cls) -> Dict[str, Dict[str, Any]]:
        """Get fields that can be updated via update_profile tool.

        Returns:
            Dict mapping field name to field info including description.
            Excludes internal fields (user_id, memories, timestamps, etc).
        """
        skip = {'user_id', 'memories', 'created_at', 'updated_at', 'agent_id', 'team_id'}

        result = {}
        for f in fields(cls):
            if f.name in skip:
                continue
            # Skip fields marked as internal
            if f.metadata.get("internal"):
                continue

            result[f.name] = {
                "type": f.type,
                "description": f.metadata.get("description", f"User's {f.name.replace('_', ' ')}"),
            }

        return result


# =============================================================================
# Session Context Schema
# =============================================================================


@dataclass
class SessionContext:
    """Schema for Session Context learning type.

    Captures state and summary for the current session.
    Unlike UserProfile which accumulates, this is REPLACED on each update.

    Key behavior: Extraction receives the previous context and updates it,
    ensuring continuity even when message history is truncated.

    Attributes:
        session_id: Required unique identifier for the session.
        user_id: Which user this session belongs to.
        summary: What's happened in this session.
        goal: What the user is trying to accomplish.
        plan: Steps to achieve the goal.
        progress: Which steps have been completed.
        agent_id: Which agent is running this session.
        team_id: Which team is running this session.
        created_at: When the session started (ISO format).
        updated_at: When the context was last updated (ISO format).

    Example - Extending with custom fields:
        @dataclass
        class MySessionContext(SessionContext):
            mood: Optional[str] = field(
                default=None,
                metadata={"description": "User's current mood or emotional state"}
            )
            blockers: List[str] = field(
                default_factory=list,
                metadata={"description": "Current blockers or obstacles"}
            )
    """

    session_id: str
    user_id: Optional[str] = None
    summary: Optional[str] = field(
        default=None,
        metadata={"description": "Summary of what's been discussed in this session"}
    )
    goal: Optional[str] = field(
        default=None,
        metadata={"description": "What the user is trying to accomplish"}
    )
    plan: Optional[List[str]] = field(
        default=None,
        metadata={"description": "Steps to achieve the goal"}
    )
    progress: Optional[List[str]] = field(
        default=None,
        metadata={"description": "Which steps have been completed"}
    )
    agent_id: Optional[str] = field(default=None, metadata={"internal": True})
    team_id: Optional[str] = field(default=None, metadata={"internal": True})
    created_at: Optional[str] = field(default=None, metadata={"internal": True})
    updated_at: Optional[str] = field(default=None, metadata={"internal": True})

    @classmethod
    def from_dict(cls, data: Any) -> Optional["SessionContext"]:
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
class LearnedKnowledge:
    """Schema for Learned Knowledge learning type.

    Captures reusable insights that apply across users and agents.

    - title: Short, descriptive title for the learning.
    - learning: The actual insight or pattern.
    - context: When/where this learning applies.
    - tags: Categories for organization.

    Example:
        LearnedKnowledge(
            title="Python async best practices",
            learning="Always use asyncio.gather() for concurrent I/O tasks",
            context="When optimizing I/O-bound Python applications",
            tags=["python", "async", "performance"]
        )
    """

    title: str
    learning: str
    context: Optional[str] = None
    tags: Optional[List[str]] = None
    agent_id: Optional[str] = field(default=None, metadata={"internal": True})
    team_id: Optional[str] = field(default=None, metadata={"internal": True})
    created_at: Optional[str] = field(default=None, metadata={"internal": True})

    @classmethod
    def from_dict(cls, data: Any) -> Optional["LearnedKnowledge"]:
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
class Decision:
    """Schema for Decision Logs. (Phase 2)

    Records decisions made by the agent with reasoning and context.
    """

    decision: str
    reasoning: Optional[str] = None
    context: Optional[str] = None
    outcome: Optional[str] = None
    agent_id: Optional[str] = None
    team_id: Optional[str] = None
    created_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Any) -> Optional["Decision"]:
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
class Feedback:
    """Schema for Behavioral Feedback. (Phase 2)

    Captures signals about what worked and what didn't.
    """

    signal: str  # thumbs_up, thumbs_down, correction, regeneration
    learning: Optional[str] = None
    context: Optional[str] = None
    agent_id: Optional[str] = None
    team_id: Optional[str] = None
    created_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Any) -> Optional["Feedback"]:
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
class InstructionUpdate:
    """Schema for Self-Improvement. (Phase 3)

    Proposes updates to agent instructions based on feedback patterns.
    """

    current_instruction: str
    proposed_instruction: str
    reasoning: str
    evidence: Optional[List[str]] = None
    agent_id: Optional[str] = None
    team_id: Optional[str] = None
    created_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Any) -> Optional["InstructionUpdate"]:
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
