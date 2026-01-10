"""
LearningMachine Configuration
=============================
Enums and configuration classes for the unified learning system.

Uses dataclasses instead of Pydantic BaseModels to avoid runtime
overhead and validation errors that could break agents mid-run.

Configurations:
- LearningMode: How learning is extracted (ALWAYS, AGENTIC, PROPOSE, HITL)
- UserProfileConfig: Config for user profile learning
- MemoriesConfig: Config for memories learning
- SessionContextConfig: Config for session context learning
- LearnedKnowledgeConfig: Config for learned knowledge
- EntityMemoryConfig: Config for entity memory
"""

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional, Type, Union

if TYPE_CHECKING:
    from agno.db.base import AsyncBaseDb, BaseDb
    from agno.models.base import Model


# =============================================================================
# Enums
# =============================================================================


class LearningMode(Enum):
    """How learning is extracted and saved.

    ALWAYS: Automatic extraction after each response.
    AGENTIC: Agent decides when to learn via tools.
    PROPOSE: Agent proposes, human confirms.
    HITL (Human-in-the-Loop): Reserved for future use.
    """

    ALWAYS = "always"
    AGENTIC = "agentic"
    PROPOSE = "propose"
    HITL = "hitl"


# =============================================================================
# Learning Type Configurations
# =============================================================================


@dataclass
class UserProfileConfig:
    """Configuration for User Profile learning type.

    UserProfile stores long-term structured profile fields about users:
    name, preferred_name, and custom fields from extended schemas.
    Updated via `update_profile` tool.

    Note: For unstructured memories, use UserMemoryConfig instead.

    Scope: USER (fixed) - Retrieved and stored by user_id.

    Attributes:
        db: Database backend for storage.
        model: Model for extraction (required for ALWAYS mode).
        mode: How learning is extracted. Default: ALWAYS.
        schema: Custom schema for user profile data. Default: UserProfile.

        # Extraction operations
        enable_update_profile: Allow updating profile fields (name, etc).

        # Agent tools
        enable_agent_tools: Expose tools to the agent.
        agent_can_update_profile: If agent_tools enabled, provide update_user_profile tool.

        # Prompt customization
        instructions: Custom instructions for what to capture.
        additional_instructions: Extra instructions appended to default.
        system_message: Full override for extraction system message.
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # Mode and extraction
    mode: LearningMode = LearningMode.ALWAYS
    schema: Optional[Type[Any]] = None

    # Extraction operations
    enable_update_profile: bool = True  # Allow updating profile fields

    # Agent tools
    enable_agent_tools: bool = False
    agent_can_update_profile: bool = True

    # Prompt customization
    instructions: Optional[str] = None
    additional_instructions: Optional[str] = None
    system_message: Optional[str] = None

    def __repr__(self) -> str:
        return f"UserProfileConfig(mode={self.mode.value}, enable_agent_tools={self.enable_agent_tools})"


@dataclass
class UserMemoryConfig:
    """Configuration for User Memory learning type.

    User Memory stores unstructured observations about users that don't fit
    into structured profile fields. These are long-term memories that
    persist across sessions.

    Scope: USER (fixed) - Retrieved and stored by user_id.

    Attributes:
        db: Database backend for storage.
        model: Model for extraction (required for ALWAYS mode).
        mode: How learning is extracted. Default: ALWAYS.
        schema: Custom schema for memories data. Default: Memories.

        # Extraction operations
        enable_add_memory: Allow adding new memories during extraction.
        enable_update_memory: Allow updating existing memories.
        enable_delete_memory: Allow deleting memories.
        enable_clear_memories: Allow clearing all memories (dangerous).

        # Agent tools
        enable_agent_tools: Expose tools to the agent.
        agent_can_update_memories: If agent_tools enabled, provide update_user_memory tool.

        # Prompt customization
        instructions: Custom instructions for what to capture.
        additional_instructions: Extra instructions appended to default.
        system_message: Full override for extraction system message.
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # Mode and extraction
    mode: LearningMode = LearningMode.ALWAYS
    schema: Optional[Type[Any]] = None

    # Extraction operations
    enable_add_memory: bool = True
    enable_update_memory: bool = True
    enable_delete_memory: bool = True
    enable_clear_memories: bool = False  # Dangerous - disabled by default

    # Agent tools
    enable_agent_tools: bool = False
    agent_can_update_memories: bool = True

    # Prompt customization
    instructions: Optional[str] = None
    additional_instructions: Optional[str] = None
    system_message: Optional[str] = None

    def __repr__(self) -> str:
        return f"UserMemoryConfig(mode={self.mode.value}, enable_agent_tools={self.enable_agent_tools})"


# Backwards compatibility alias
MemoriesConfig = UserMemoryConfig


@dataclass
class SessionContextConfig:
    """Configuration for Session Context learning type.

    Session Context captures state and summary for the current session:
    what's happened, goals, plans, and progress.

    Scope: SESSION (fixed) - Retrieved and stored by session_id.

    Key behavior: Context builds on previous context. Each extraction
    receives the previous context and updates it, rather than creating
    from scratch. This ensures continuity even with truncated message history.

    Attributes:
        db: Database backend for storage.
        model: Model for extraction (required for ALWAYS mode).
        mode: How learning is extracted. Default: ALWAYS.
        schema: Custom schema for session context. Default: SessionContext.

        # Planning mode
        enable_planning: Track goal, plan, and progress (not just summary).
        enable_add_context: Allow creating new context.
        enable_update_context: Allow updating existing context.
        enable_delete_context: Allow deleting context.
        enable_clear_context: Allow clearing context.

        # Prompt customization
        instructions: Custom instructions for extraction.
        additional_instructions: Extra instructions appended to default.
        system_message: Full override for extraction system message.
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # Mode and extraction
    mode: LearningMode = LearningMode.ALWAYS
    schema: Optional[Type[Any]] = None

    # Planning mode
    enable_planning: bool = False
    # Extraction operations
    enable_add_context: bool = True
    enable_update_context: bool = True
    enable_delete_context: bool = True
    enable_clear_context: bool = False

    # Prompt customization
    instructions: Optional[str] = None
    additional_instructions: Optional[str] = None
    system_message: Optional[str] = None

    def __repr__(self) -> str:
        return f"SessionContextConfig(mode={self.mode.value}, enable_planning={self.enable_planning})"


@dataclass
class LearnedKnowledgeConfig:
    """Configuration for Learned Knowledge learning type.

    Learned Knowledge captures reusable insights and patterns that
    can be shared across users and agents.

    Scope: `namespace` + KNOWLEDGE (fixed):
    - "user": Private learned knowledge per user
    - "global": Shared with everyone (default)
    - Custom string: Explicit grouping (e.g., "engineering", "sales_west")

    IMPORTANT: A knowledge base is required for learnings to work.
    Either provide it here or pass it to LearningMachine directly.

    Attributes:
        knowledge: Knowledge base instance (vector store) for storage.
                   REQUIRED - learnings cannot be saved/searched without this.
        model: Model for extraction (if using ALWAYS mode).
        mode: How learning is extracted. Default: AGENTIC.
        schema: Custom schema for learning data. Default: LearnedKnowledge.

        # Sharing boundary
        namespace: Sharing boundary ("user", "global", or custom).

        # Agent tools
        enable_agent_tools: Expose tools to the agent.
        agent_can_save: If agent_tools enabled, provide save_learning tool.
        agent_can_search: If agent_tools enabled, provide search_learnings tool.

        # Prompt customization
        instructions: Custom instructions for what makes a good learning.
        additional_instructions: Extra instructions appended to default.
        system_message: Full override for extraction system message.
    """

    # Knowledge base - required for learnings to work
    knowledge: Optional[Any] = None  # agno.knowledge.Knowledge
    model: Optional["Model"] = None

    # Mode and extraction
    mode: LearningMode = LearningMode.AGENTIC
    schema: Optional[Type[Any]] = None

    # Sharing boundary
    namespace: str = "global"

    # Agent tools
    enable_agent_tools: bool = True
    agent_can_save: bool = True
    agent_can_search: bool = True

    # Prompt customization
    instructions: Optional[str] = None
    additional_instructions: Optional[str] = None
    system_message: Optional[str] = None

    def __repr__(self) -> str:
        has_knowledge = self.knowledge is not None
        return f"LearnedKnowledgeConfig(mode={self.mode.value}, knowledge={has_knowledge}, enable_agent_tools={self.enable_agent_tools})"


@dataclass
class EntityMemoryConfig:
    """Configuration for EntityMemory learning type.

    EntityMemory stores facts about third-party entities: companies,
    projects, people, systems, products, etc. Think of it as UserProfile
    but for things that aren't the user.

    Entities have:
    - Core properties (name, description, key-value properties)
    - Facts (semantic memory - "Acme uses PostgreSQL")
    - Events (episodic memory - "Acme launched v2 on Jan 15")
    - Relationships (graph edges - "Bob is CEO of Acme")

    Scope is controlled by `namespace`:
    - "user": Private entity graph per user
    - "global": Shared with everyone (default)
    - Custom string: Explicit grouping (e.g., "sales_west")

    Attributes:
        db: Database backend for storage.
        model: Model for extraction (required for ALWAYS mode).
        mode: How learning is extracted. Default: ALWAYS.
        schema: Custom schema for entity memory data. Default: EntityMemory.

        # Sharing boundary
        namespace: Sharing boundary ("user", "global", or custom).

        # Extraction operations
        enable_create_entity: Allow creating new entities.
        enable_update_entity: Allow updating entity properties.
        enable_add_fact: Allow adding facts to entities.
        enable_update_fact: Allow updating existing facts.
        enable_delete_fact: Allow deleting facts.
        enable_add_event: Allow adding events to entities.
        enable_add_relationship: Allow adding relationships.

        # Agent tools
        enable_agent_tools: Expose tools to the agent.
        agent_can_create_entity: If agent_tools enabled, provide create_entity tool.
        agent_can_update_entity: If agent_tools enabled, provide update_entity tool.
        agent_can_search_entities: If agent_tools enabled, provide search_entities tool.

        # Prompt customization
        instructions: Custom instructions for entity extraction.
        additional_instructions: Extra instructions appended to default.
        system_message: Full override for extraction system message.
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # Mode and extraction
    mode: LearningMode = LearningMode.ALWAYS
    schema: Optional[Type[Any]] = None

    # Sharing boundary
    namespace: str = "global"

    # Extraction operations
    enable_create_entity: bool = True
    enable_update_entity: bool = True
    enable_add_fact: bool = True
    enable_update_fact: bool = True
    enable_delete_fact: bool = True
    enable_add_event: bool = True
    enable_add_relationship: bool = True

    # Agent tools
    enable_agent_tools: bool = False
    agent_can_create_entity: bool = True
    agent_can_update_entity: bool = True
    agent_can_search_entities: bool = True

    # Prompt customization
    instructions: Optional[str] = None
    additional_instructions: Optional[str] = None
    system_message: Optional[str] = None

    def __repr__(self) -> str:
        return f"EntityMemoryConfig(mode={self.mode.value}, namespace={self.namespace}, enable_agent_tools={self.enable_agent_tools})"


# =============================================================================
# Phase 2 Configurations (Placeholders)
# =============================================================================


@dataclass
class DecisionLogConfig:
    """Configuration for Decision Logs learning type.

    Decision Logs record decisions made by the agent with reasoning
    and context. Useful for auditing and learning from past decisions.

    Scope: AGENT (fixed) - Stored and retrieved by agent_id.

    Note: Deferred to Phase 2.
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # Mode and extraction
    mode: LearningMode = LearningMode.ALWAYS
    schema: Optional[Type[Any]] = None

    # Agent tools
    enable_agent_tools: bool = True
    agent_can_save: bool = True
    agent_can_search: bool = True

    # Prompt customization
    system_message: Optional[str] = None
    instructions: Optional[str] = None
    additional_instructions: Optional[str] = None

    def __repr__(self) -> str:
        return f"DecisionLogConfig(mode={self.mode.value})"


@dataclass
class FeedbackConfig:
    """Configuration for Behavioral Feedback learning type.

    Behavioral Feedback captures signals about what worked and what
    didn't: thumbs up/down, corrections, regeneration requests.

    Scope: AGENT (fixed) - Stored and retrieved by agent_id.

    Note: Deferred to Phase 2.
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # Mode and extraction
    mode: LearningMode = LearningMode.ALWAYS
    schema: Optional[Type[Any]] = None

    # Prompt customization
    instructions: Optional[str] = None

    def __repr__(self) -> str:
        return "FeedbackConfig(mode=ALWAYS)"


@dataclass
class SelfImprovementConfig:
    """Configuration for Self-Improvement learning type.

    Self-Improvement proposes updates to agent instructions based
    on feedback patterns and successful interactions.

    Scope: AGENT (fixed) - Stored and retrieved by agent_id.

    Note: Deferred to Phase 3.
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # Mode and extraction
    mode: LearningMode = LearningMode.HITL
    schema: Optional[Type[Any]] = None

    # Prompt customization
    instructions: Optional[str] = None

    def __repr__(self) -> str:
        return "SelfImprovementConfig(mode=HITL)"
