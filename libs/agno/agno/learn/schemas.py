"""
LearningMachine Schemas
=======================
Dataclasses for each learning type.

Uses pure dataclasses to avoid runtime overhead.
All parsing is done via from_dict() which never raises.

Classes are designed to be extended - from_dict() and to_dict()
automatically handle subclass fields via dataclasses.fields().

Field Descriptions
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
- EntityMemory: Third-party entity facts
- Decision: Decision logs (Phase 2)
- Feedback: Behavioral feedback (Phase 2)
- InstructionUpdate: Self-improvement (Phase 3)
"""

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional

from agno.learn.utils import _parse_json, _safe_get
from agno.utils.log import log_debug

# =============================================================================
# Helper for debug logging
# =============================================================================


def _truncate_for_log(data: Any, max_len: int = 100) -> str:
    """Truncate data for logging to avoid massive log entries."""
    s = str(data)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


# =============================================================================
# User Profile Schema
# =============================================================================


@dataclass
class UserProfile:
    """Schema for User Profile learning type.

    Captures long-term structured profile information about a user that persists
    across sessions. Designed to be extended with custom fields.

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
        agent_id: Which agent created this profile.
        team_id: Which team created this profile.
        created_at: When the profile was created (ISO format).
        updated_at: When the profile was last updated (ISO format).
    """

    user_id: str
    name: Optional[str] = field(default=None, metadata={"description": "User's full name"})
    preferred_name: Optional[str] = field(
        default=None, metadata={"description": "How they prefer to be addressed (nickname, first name, etc)"}
    )
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
                log_debug(f"{cls.__name__}.from_dict: _parse_json returned None for data={_truncate_for_log(data)}")
                return None

            # user_id is required
            if not parsed.get("user_id"):
                log_debug(f"{cls.__name__}.from_dict: missing required field 'user_id'")
                return None

            # Get field names for this class (includes subclass fields)
            field_names = {f.name for f in fields(cls)}
            kwargs = {k: v for k, v in parsed.items() if k in field_names}

            return cls(**kwargs)
        except Exception as e:
            log_debug(f"{cls.__name__}.from_dict failed: {e}, data={_truncate_for_log(data)}")
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict. Works with subclasses."""
        try:
            return asdict(self)
        except Exception as e:
            log_debug(f"{self.__class__.__name__}.to_dict failed: {e}")
            return {}

    @classmethod
    def get_updateable_fields(cls) -> Dict[str, Dict[str, Any]]:
        """Get fields that can be updated via update_profile tool.

        Returns:
            Dict mapping field name to field info including description.
            Excludes internal fields (user_id, timestamps, etc).
        """
        skip = {"user_id", "created_at", "updated_at", "agent_id", "team_id"}

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

    def __repr__(self) -> str:
        return f"UserProfile(user_id={self.user_id})"


@dataclass
class Memories:
    """Schema for Memories learning type.

    Captures unstructured observations about a user that don't fit
    into structured profile fields. These are long-term memories
    that persist across sessions.

    Attributes:
        user_id: Required unique identifier for the user.
        memories: List of memory entries, each with 'id' and 'content'.
        agent_id: Which agent created these memories.
        team_id: Which team created these memories.
        created_at: When the memories were created (ISO format).
        updated_at: When the memories were last updated (ISO format).
    """

    user_id: str
    memories: List[Dict[str, Any]] = field(default_factory=list)
    agent_id: Optional[str] = field(default=None, metadata={"internal": True})
    team_id: Optional[str] = field(default=None, metadata={"internal": True})
    created_at: Optional[str] = field(default=None, metadata={"internal": True})
    updated_at: Optional[str] = field(default=None, metadata={"internal": True})

    @classmethod
    def from_dict(cls, data: Any) -> Optional["Memories"]:
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
                log_debug(f"{cls.__name__}.from_dict: _parse_json returned None for data={_truncate_for_log(data)}")
                return None

            # user_id is required
            if not parsed.get("user_id"):
                log_debug(f"{cls.__name__}.from_dict: missing required field 'user_id'")
                return None

            # Get field names for this class (includes subclass fields)
            field_names = {f.name for f in fields(cls)}
            kwargs = {k: v for k, v in parsed.items() if k in field_names}

            return cls(**kwargs)
        except Exception as e:
            log_debug(f"{cls.__name__}.from_dict failed: {e}, data={_truncate_for_log(data)}")
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict. Works with subclasses."""
        try:
            return asdict(self)
        except Exception as e:
            log_debug(f"{self.__class__.__name__}.to_dict failed: {e}")
            return {}

    def add_memory(self, content: str, **kwargs) -> str:
        """Add a new memory.

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

    def __repr__(self) -> str:
        return f"Memories(user_id={self.user_id})"


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
        default=None, metadata={"description": "Summary of what's been discussed in this session"}
    )
    goal: Optional[str] = field(default=None, metadata={"description": "What the user is trying to accomplish"})
    plan: Optional[List[str]] = field(default=None, metadata={"description": "Steps to achieve the goal"})
    progress: Optional[List[str]] = field(default=None, metadata={"description": "Which steps have been completed"})
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
                log_debug(f"{cls.__name__}.from_dict: _parse_json returned None for data={_truncate_for_log(data)}")
                return None

            # session_id is required
            if not parsed.get("session_id"):
                log_debug(f"{cls.__name__}.from_dict: missing required field 'session_id'")
                return None

            field_names = {f.name for f in fields(cls)}
            kwargs = {k: v for k, v in parsed.items() if k in field_names}

            return cls(**kwargs)
        except Exception as e:
            log_debug(f"{cls.__name__}.from_dict failed: {e}, data={_truncate_for_log(data)}")
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        try:
            return asdict(self)
        except Exception as e:
            log_debug(f"{self.__class__.__name__}.to_dict failed: {e}")
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

    def __repr__(self) -> str:
        return f"SessionContext(session_id={self.session_id})"


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
    - namespace: Sharing boundary for this learning.

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
    user_id: Optional[str] = field(default=None, metadata={"internal": True})
    namespace: Optional[str] = field(default=None, metadata={"internal": True})
    agent_id: Optional[str] = field(default=None, metadata={"internal": True})
    team_id: Optional[str] = field(default=None, metadata={"internal": True})
    created_at: Optional[str] = field(default=None, metadata={"internal": True})
    updated_at: Optional[str] = field(default=None, metadata={"internal": True})

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
                log_debug(f"{cls.__name__}.from_dict: _parse_json returned None for data={_truncate_for_log(data)}")
                return None

            # title and learning are required
            if not parsed.get("title") or not parsed.get("learning"):
                log_debug(f"{cls.__name__}.from_dict: missing required fields 'title' or 'learning'")
                return None

            field_names = {f.name for f in fields(cls)}
            kwargs = {k: v for k, v in parsed.items() if k in field_names}

            return cls(**kwargs)
        except Exception as e:
            log_debug(f"{cls.__name__}.from_dict failed: {e}, data={_truncate_for_log(data)}")
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        try:
            return asdict(self)
        except Exception as e:
            log_debug(f"{self.__class__.__name__}.to_dict failed: {e}")
            return {}

    def to_text(self) -> str:
        """Convert learning to searchable text format for vector storage."""
        parts = [f"Title: {self.title}", f"Learning: {self.learning}"]
        if self.context:
            parts.append(f"Context: {self.context}")
        if self.tags:
            parts.append(f"Tags: {', '.join(self.tags)}")
        return "\n".join(parts)

    def __repr__(self) -> str:
        return f"LearnedKnowledge(title={self.title})"


# =============================================================================
# Entity Memory Schema
# =============================================================================


@dataclass
class EntityMemory:
    """Schema for Entity Memory learning type.

    Captures facts about third-party entities: companies, projects,
    people, systems, products. Like UserProfile but for non-users.

    Structure:
    - **Core**: name, description, properties (key-value pairs)
    - **Facts**: Semantic memory ("Acme uses PostgreSQL")
    - **Events**: Episodic memory ("Acme launched v2 on Jan 15")
    - **Relationships**: Graph edges ("Bob is CEO of Acme")

    Common Entity Types:
    - "company", "project", "person", "system", "product"
    - Any string is valid.

    Example:
        EntityMemory(
            entity_id="acme_corp",
            entity_type="company",
            name="Acme Corporation",
            description="Enterprise software company",
            properties={"industry": "fintech", "size": "startup"},
            facts=[
                {"id": "f1", "content": "Uses PostgreSQL for main database"},
                {"id": "f2", "content": "API uses OAuth2 authentication"},
            ],
            events=[
                {"id": "e1", "content": "Launched v2.0", "date": "2024-01-15"},
            ],
            relationships=[
                {"entity_id": "bob_smith", "relation": "CEO"},
            ],
        )

    Attributes:
        entity_id: Unique identifier (lowercase, underscores: "acme_corp").
        entity_type: Type of entity ("company", "project", "person", etc).
        name: Display name for the entity.
        description: Brief description of what this entity is.
        properties: Key-value properties (industry, tech_stack, etc).
        facts: Semantic memories - timeless facts about the entity.
        events: Episodic memories - time-bound occurrences.
        relationships: Connections to other entities.
        namespace: Sharing boundary for this entity.
        user_id: Owner user (if namespace="user").
        agent_id: Which agent created this.
        team_id: Which team context.
        created_at: When first created.
        updated_at: When last modified.
    """

    entity_id: str
    entity_type: str = field(metadata={"description": "Type: company, project, person, system, product, etc"})

    # Core properties
    name: Optional[str] = field(default=None, metadata={"description": "Display name for the entity"})
    description: Optional[str] = field(
        default=None, metadata={"description": "Brief description of what this entity is"}
    )
    properties: Dict[str, str] = field(
        default_factory=dict, metadata={"description": "Key-value properties (industry, tech_stack, etc)"}
    )

    # Semantic memory (facts)
    facts: List[Dict[str, Any]] = field(default_factory=list)
    # [{"id": "abc", "content": "Uses PostgreSQL", "confidence": 0.9, "source": "..."}]

    # Episodic memory (events)
    events: List[Dict[str, Any]] = field(default_factory=list)
    # [{"id": "xyz", "content": "Had outage on 2024-01-15", "date": "2024-01-15"}]

    # Relationships (graph edges)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    # [{"entity_id": "bob", "relation": "CEO", "direction": "incoming"}]

    # Scope
    namespace: Optional[str] = field(default=None, metadata={"internal": True})
    user_id: Optional[str] = field(default=None, metadata={"internal": True})
    agent_id: Optional[str] = field(default=None, metadata={"internal": True})
    team_id: Optional[str] = field(default=None, metadata={"internal": True})
    created_at: Optional[str] = field(default=None, metadata={"internal": True})
    updated_at: Optional[str] = field(default=None, metadata={"internal": True})

    @classmethod
    def from_dict(cls, data: Any) -> Optional["EntityMemory"]:
        """Parse from dict/JSON, returning None on any failure."""
        if data is None:
            return None
        if isinstance(data, cls):
            return data

        try:
            parsed = _parse_json(data)
            if not parsed:
                log_debug(f"{cls.__name__}.from_dict: _parse_json returned None for data={_truncate_for_log(data)}")
                return None

            # entity_id and entity_type are required
            if not parsed.get("entity_id") or not parsed.get("entity_type"):
                log_debug(f"{cls.__name__}.from_dict: missing required fields 'entity_id' or 'entity_type'")
                return None

            field_names = {f.name for f in fields(cls)}
            kwargs = {k: v for k, v in parsed.items() if k in field_names}

            return cls(**kwargs)
        except Exception as e:
            log_debug(f"{cls.__name__}.from_dict failed: {e}, data={_truncate_for_log(data)}")
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        try:
            return asdict(self)
        except Exception as e:
            log_debug(f"{self.__class__.__name__}.to_dict failed: {e}")
            return {}

    def add_fact(self, content: str, **kwargs) -> str:
        """Add a new fact to the entity.

        Args:
            content: The fact text.
            **kwargs: Additional fields (confidence, source, etc).

        Returns:
            The generated fact ID.
        """
        import uuid

        fact_id = str(uuid.uuid4())[:8]

        if content and content.strip():
            self.facts.append({"id": fact_id, "content": content.strip(), **kwargs})

        return fact_id

    def add_event(self, content: str, date: Optional[str] = None, **kwargs) -> str:
        """Add a new event to the entity.

        Args:
            content: The event description.
            date: When the event occurred (ISO format or natural language).
            **kwargs: Additional fields.

        Returns:
            The generated event ID.
        """
        import uuid

        event_id = str(uuid.uuid4())[:8]

        if content and content.strip():
            event = {"id": event_id, "content": content.strip(), **kwargs}
            if date:
                event["date"] = date
            self.events.append(event)

        return event_id

    def add_relationship(self, related_entity_id: str, relation: str, direction: str = "outgoing", **kwargs) -> str:
        """Add a relationship to another entity.

        Args:
            related_entity_id: The other entity's ID.
            relation: The relationship type ("CEO", "owns", "part_of", etc).
            direction: "outgoing" (this → other) or "incoming" (other → this).
            **kwargs: Additional fields.

        Returns:
            The generated relationship ID.
        """
        import uuid

        rel_id = str(uuid.uuid4())[:8]

        self.relationships.append(
            {"id": rel_id, "entity_id": related_entity_id, "relation": relation, "direction": direction, **kwargs}
        )

        return rel_id

    def get_fact(self, fact_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific fact by ID."""
        for fact in self.facts:
            if isinstance(fact, dict) and fact.get("id") == fact_id:
                return fact
        return None

    def update_fact(self, fact_id: str, content: str, **kwargs) -> bool:
        """Update an existing fact.

        Returns:
            True if fact was found and updated, False otherwise.
        """
        for fact in self.facts:
            if isinstance(fact, dict) and fact.get("id") == fact_id:
                fact["content"] = content.strip()
                fact.update(kwargs)
                return True
        return False

    def delete_fact(self, fact_id: str) -> bool:
        """Delete a fact by ID.

        Returns:
            True if fact was found and deleted, False otherwise.
        """
        original_len = len(self.facts)
        self.facts = [f for f in self.facts if not (isinstance(f, dict) and f.get("id") == fact_id)]
        return len(self.facts) < original_len

    def get_context_text(self) -> str:
        """Get entity as formatted string for prompts."""
        parts = []

        if self.name:
            parts.append(f"**{self.name}** ({self.entity_type})")
        else:
            parts.append(f"**{self.entity_id}** ({self.entity_type})")

        if self.description:
            parts.append(self.description)

        if self.properties:
            props = ", ".join(f"{k}: {v}" for k, v in self.properties.items())
            parts.append(f"Properties: {props}")

        if self.facts:
            facts_text = "\n".join(f"  - {f.get('content', f)}" for f in self.facts)
            parts.append(f"Facts:\n{facts_text}")

        if self.events:
            events_text = "\n".join(
                f"  - {e.get('content', e)}" + (f" ({e.get('date')})" if e.get("date") else "") for e in self.events
            )
            parts.append(f"Events:\n{events_text}")

        if self.relationships:
            rels_text = "\n".join(f"  - {r.get('relation')}: {r.get('entity_id')}" for r in self.relationships)
            parts.append(f"Relationships:\n{rels_text}")

        return "\n\n".join(parts)

    @classmethod
    def get_updateable_fields(cls) -> Dict[str, Dict[str, Any]]:
        """Get fields that can be updated via update tools.

        Returns:
            Dict mapping field name to field info including description.
            Excludes internal fields and collections (facts, events, relationships).
        """
        skip = {
            "entity_id",
            "entity_type",
            "facts",
            "events",
            "relationships",
            "namespace",
            "user_id",
            "agent_id",
            "team_id",
            "created_at",
            "updated_at",
        }

        result = {}
        for f in fields(cls):
            if f.name in skip:
                continue
            if f.metadata.get("internal"):
                continue

            result[f.name] = {
                "type": f.type,
                "description": f.metadata.get("description", f"Entity's {f.name.replace('_', ' ')}"),
            }

        return result

    def __repr__(self) -> str:
        return f"EntityMemory(entity_id={self.entity_id})"


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
                log_debug(f"{cls.__name__}.from_dict: _parse_json returned None for data={_truncate_for_log(data)}")
                return None

            return cls(
                name=_safe_get(parsed, "name"),
                preferred_name=_safe_get(parsed, "preferred_name"),
                new_memories=_safe_get(parsed, "new_memories") or [],
            )
        except Exception as e:
            log_debug(f"{cls.__name__}.from_dict failed: {e}, data={_truncate_for_log(data)}")
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
                log_debug(f"{cls.__name__}.from_dict: _parse_json returned None for data={_truncate_for_log(data)}")
                return None

            return cls(summary=_safe_get(parsed, "summary") or "")
        except Exception as e:
            log_debug(f"{cls.__name__}.from_dict failed: {e}, data={_truncate_for_log(data)}")
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
                log_debug(f"{cls.__name__}.from_dict: _parse_json returned None for data={_truncate_for_log(data)}")
                return None

            return cls(
                summary=_safe_get(parsed, "summary") or "",
                goal=_safe_get(parsed, "goal"),
                plan=_safe_get(parsed, "plan"),
                progress=_safe_get(parsed, "progress"),
            )
        except Exception as e:
            log_debug(f"{cls.__name__}.from_dict failed: {e}, data={_truncate_for_log(data)}")
            return None


# =============================================================================
# Phase 2 Schemas (Placeholders)
# =============================================================================


@dataclass
class DecisionLog:
    """Schema for Decision Logs.

    Records decisions made by the agent with reasoning and context.
    Useful for:
    - Auditing agent behavior
    - Learning from past decisions
    - Debugging unexpected outcomes
    - Building feedback loops

    Example:
        DecisionLog(
            id="dec_abc123",
            decision="Used web search instead of knowledge base",
            reasoning="User asked about current events which require fresh data",
            decision_type="tool_selection",
            context="User query: 'What happened in the news today?'",
            alternatives=["search_knowledge_base", "ask_for_clarification"],
            confidence=0.85,
        )

    Attributes:
        id: Unique identifier for this decision.
        decision: What was decided (the choice made).
        reasoning: Why this decision was made.
        decision_type: Category of decision (tool_selection, response_style, etc).
        context: The situation that required a decision.
        alternatives: Other options that were considered.
        confidence: How confident the agent was (0.0 to 1.0).
        outcome: What happened as a result (can be updated later).
        outcome_quality: Was the outcome good/bad/neutral.
        tags: Categories for organization.
        session_id: Which session this decision was made in.
        user_id: Which user this decision was for.
        agent_id: Which agent made this decision.
        team_id: Which team context.
        created_at: When the decision was made.
        updated_at: When the outcome was recorded.
    """

    id: str
    decision: str
    reasoning: Optional[str] = field(default=None, metadata={"description": "Why this decision was made"})
    decision_type: Optional[str] = field(
        default=None,
        metadata={"description": "Category: tool_selection, response_style, clarification, escalation, etc"},
    )
    context: Optional[str] = field(default=None, metadata={"description": "The situation that required a decision"})
    alternatives: Optional[List[str]] = field(
        default=None, metadata={"description": "Other options that were considered"}
    )
    confidence: Optional[float] = field(default=None, metadata={"description": "Confidence level 0.0 to 1.0"})
    outcome: Optional[str] = field(default=None, metadata={"description": "What happened as a result"})
    outcome_quality: Optional[str] = field(default=None, metadata={"description": "Was outcome good/bad/neutral"})
    tags: Optional[List[str]] = field(default=None, metadata={"description": "Categories for organization"})

    # Scope
    session_id: Optional[str] = field(default=None, metadata={"internal": True})
    user_id: Optional[str] = field(default=None, metadata={"internal": True})
    agent_id: Optional[str] = field(default=None, metadata={"internal": True})
    team_id: Optional[str] = field(default=None, metadata={"internal": True})
    created_at: Optional[str] = field(default=None, metadata={"internal": True})
    updated_at: Optional[str] = field(default=None, metadata={"internal": True})

    @classmethod
    def from_dict(cls, data: Any) -> Optional["DecisionLog"]:
        """Parse from dict/JSON, returning None on any failure."""
        if data is None:
            return None
        if isinstance(data, cls):
            return data

        try:
            parsed = _parse_json(data)
            if not parsed:
                log_debug(f"{cls.__name__}.from_dict: _parse_json returned None for data={_truncate_for_log(data)}")
                return None

            # id and decision are required
            if not parsed.get("id") or not parsed.get("decision"):
                log_debug(f"{cls.__name__}.from_dict: missing required fields 'id' or 'decision'")
                return None

            field_names = {f.name for f in fields(cls)}
            kwargs = {k: v for k, v in parsed.items() if k in field_names}

            return cls(**kwargs)
        except Exception as e:
            log_debug(f"{cls.__name__}.from_dict failed: {e}, data={_truncate_for_log(data)}")
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        try:
            return asdict(self)
        except Exception as e:
            log_debug(f"{self.__class__.__name__}.to_dict failed: {e}")
            return {}

    def to_text(self) -> str:
        """Convert to searchable text format."""
        parts = [f"Decision: {self.decision}"]
        if self.reasoning:
            parts.append(f"Reasoning: {self.reasoning}")
        if self.context:
            parts.append(f"Context: {self.context}")
        if self.decision_type:
            parts.append(f"Type: {self.decision_type}")
        if self.outcome:
            parts.append(f"Outcome: {self.outcome}")
        return "\n".join(parts)

    def __repr__(self) -> str:
        return f"DecisionLog(id={self.id}, decision={self.decision[:50]}...)"


# Backwards compatibility alias
Decision = DecisionLog


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
        """Parse from dict/JSON, returning None on any failure."""
        if data is None:
            return None
        if isinstance(data, cls):
            return data

        try:
            parsed = _parse_json(data)
            if not parsed:
                log_debug(f"{cls.__name__}.from_dict: _parse_json returned None for data={_truncate_for_log(data)}")
                return None

            if not parsed.get("signal"):
                log_debug(f"{cls.__name__}.from_dict: missing required field 'signal'")
                return None

            field_names = {f.name for f in fields(cls)}
            kwargs = {k: v for k, v in parsed.items() if k in field_names}

            return cls(**kwargs)
        except Exception as e:
            log_debug(f"{cls.__name__}.from_dict failed: {e}, data={_truncate_for_log(data)}")
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        try:
            return asdict(self)
        except Exception as e:
            log_debug(f"{self.__class__.__name__}.to_dict failed: {e}")
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
        """Parse from dict/JSON, returning None on any failure."""
        if data is None:
            return None
        if isinstance(data, cls):
            return data

        try:
            parsed = _parse_json(data)
            if not parsed:
                log_debug(f"{cls.__name__}.from_dict: _parse_json returned None for data={_truncate_for_log(data)}")
                return None

            required = ["current_instruction", "proposed_instruction", "reasoning"]
            missing = [k for k in required if not parsed.get(k)]
            if missing:
                log_debug(f"{cls.__name__}.from_dict: missing required fields {missing}")
                return None

            field_names = {f.name for f in fields(cls)}
            kwargs = {k: v for k, v in parsed.items() if k in field_names}

            return cls(**kwargs)
        except Exception as e:
            log_debug(f"{cls.__name__}.from_dict failed: {e}, data={_truncate_for_log(data)}")
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        try:
            return asdict(self)
        except Exception as e:
            log_debug(f"{self.__class__.__name__}.to_dict failed: {e}")
            return {}
