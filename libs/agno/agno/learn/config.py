"""
LearningMachine Configuration
=============================
Enums and configuration classes for the unified learning system.

Uses dataclasses instead of Pydantic BaseModels to avoid runtime
overhead and validation errors that could break agents mid-run.

Configurations:
- LearningMode: How learning is extracted (BACKGROUND, AGENTIC, PROPOSE, HITL)
- ExtractionTiming: When extraction runs (BEFORE, PARALLEL, AFTER)
- ExtractionConfig: Settings for background extraction
- UserProfileConfig: Config for user profile learning
- SessionContextConfig: Config for session context learning
- LearnedKnowledgeConfig: Config for learned knowledge
"""

from dataclasses import dataclass, field
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

    Attributes:
        BACKGROUND: Automatically extract and save learnings in the background.
                   No user interaction needed. Best for user profiles.
        AGENTIC: Learning extraction is agent-driven via tool usage.
                Agent decides when to save learnings using provided tools.
        PROPOSE: Agent proposes learning in chat, user confirms before saving.
                Best for explicit knowledge capture with user validation.
        HITL: Human-in-the-loop. Background extracts and queues for human approval.
              Best for sensitive or high-stakes learning types.
    """

    BACKGROUND = "background"
    AGENTIC = "agentic"
    PROPOSE = "propose"
    HITL = "hitl"


class ExtractionTiming(Enum):
    """When extraction runs relative to LLM response.

    Attributes:
        BEFORE: Runs before LLM call. Adds latency before response.
               Use when you need fresh context for the response.
        PARALLEL: Runs while LLM generates response. Fast, but may
                 duplicate if agent also saves learnings via tool.
        AFTER: Runs after response is returned. Slower, but can
              check what agent saved to avoid duplicates.
    """

    BEFORE = "before"
    PARALLEL = "parallel"
    AFTER = "after"


# =============================================================================
# Extraction Configuration
# =============================================================================


@dataclass
class ExtractionConfig:
    """Configuration for learning extraction.

    Controls when and how often background extraction runs.

    Attributes:
        timing: When to run extraction relative to LLM response.
        run_after_messages: Run extraction after every N messages.
                           Set to 1 for every message, 2 for every other, etc.
    """

    timing: ExtractionTiming = ExtractionTiming.PARALLEL
    run_after_messages: int = 1


# =============================================================================
# Learning Type Configurations
# =============================================================================


@dataclass
class UserProfileConfig:
    """Configuration for User Profile learning type.

    User Profile captures long-term memory about users that persists
    across sessions: name, preferences, communication style, etc.

    Scope: USER (fixed) - Retrieved and stored by user_id.

    ## Two Types of Profile Data

    1. **Profile Fields** (structured): name, preferred_name, and any custom
       fields added when extending the schema. Updated via `update_profile` tool.

    2. **Memories** (unstructured): Observations that don't fit schema fields.
       Updated via `add_memory`, `update_memory`, `delete_memory` tools.

    Attributes:
        db: Database backend for storage.
        model: Model for extraction (required for BACKGROUND mode).
        mode: How learning is extracted. Default: BACKGROUND.
        extraction: Extraction timing settings.
        schema: Custom schema for user profile data. Default: UserProfile.

        # Extraction operations (BACKGROUND mode)
        enable_add_memory: Allow adding new memories during extraction.
        enable_update_memory: Allow updating existing memories.
        enable_delete_memory: Allow deleting memories.
        enable_clear_memories: Allow clearing all memories (dangerous).
        enable_update_profile: Allow updating profile fields (name, etc).

        # Agent tools (AGENTIC mode or when enable_agent_tools=True)
        enable_agent_tools: Master switch to expose tools to the agent.
        agent_can_update_memories: If agent_tools enabled, allow memory updates.
        agent_can_update_profile: If agent_tools enabled, allow profile updates.

        # Prompt customization
        system_message: Full override for extraction system message.
        instructions: Custom instructions for what to capture.
        additional_instructions: Extra instructions appended to default.

    Example:
        >>> config = UserProfileConfig(
        ...     db=my_db,
        ...     model=my_model,
        ...     mode=LearningMode.BACKGROUND,
        ...     enable_agent_tools=True,  # Expose tools to agent
        ...     instructions="Focus on professional preferences only.",
        ... )

    Example with extended schema:
        >>> @dataclass
        ... class MyUserProfile(UserProfile):
        ...     company: Optional[str] = field(default=None, metadata={"description": "Where they work"})
        ...     role: Optional[str] = field(default=None, metadata={"description": "Job title"})
        ...
        >>> config = UserProfileConfig(
        ...     schema=MyUserProfile,  # Agent sees company, role as updateable fields
        ... )
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # Mode and extraction
    mode: LearningMode = LearningMode.BACKGROUND
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    schema: Optional[Type[Any]] = None

    # Extraction operations (what can happen during BACKGROUND extraction)
    enable_add_memory: bool = True
    enable_update_memory: bool = True
    enable_delete_memory: bool = True
    enable_clear_memories: bool = False  # Dangerous - disabled by default
    enable_update_profile: bool = True  # Allow updating profile fields

    # Agent tools (AGENTIC mode or explicit enable)
    enable_agent_tools: bool = False  # Master switch
    agent_can_update_memories: bool = True  # If agent_tools enabled
    agent_can_update_profile: bool = True  # If agent_tools enabled

    # Prompt customization
    system_message: Optional[str] = None
    instructions: Optional[str] = None
    additional_instructions: Optional[str] = None

    def __repr__(self) -> str:
        return f"UserProfileConfig(mode={self.mode.value}, enable_agent_tools={self.enable_agent_tools})"


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
        model: Model for extraction (required for BACKGROUND mode).
        mode: How learning is extracted. Default: BACKGROUND.
        extraction: Extraction timing settings.
        schema: Custom schema for session context. Default: SessionContext.

        # Feature flags
        enable_planning: If True, extract goal/plan/progress in addition
                        to summary. If False, extract summary only.

        # Prompt customization
        system_message: Full override for extraction system message.
        instructions: Custom instructions for extraction.
        additional_instructions: Extra instructions appended to default.

    Example:
        >>> config = SessionContextConfig(
        ...     db=my_db,
        ...     model=my_model,
        ...     extraction=ExtractionConfig(
        ...         timing=ExtractionTiming.AFTER,
        ...         run_after_messages=5,
        ...     ),
        ...     enable_planning=True,  # Track goals and progress
        ... )
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # Mode and extraction
    mode: LearningMode = LearningMode.BACKGROUND
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    schema: Optional[Type[Any]] = None

    # Feature flags
    enable_planning: bool = False

    # Prompt customization
    system_message: Optional[str] = None
    instructions: Optional[str] = None
    additional_instructions: Optional[str] = None

    def __repr__(self) -> str:
        return f"SessionContextConfig(mode={self.mode.value}, enable_planning={self.enable_planning})"


@dataclass
class LearnedKnowledgeConfig:
    """Configuration for Learned Knowledge learning type.

    Learned Knowledge captures reusable insights and patterns that
    can be shared across users and potentially across agents.

    Scope: KNOWLEDGE (fixed) - Stored in Knowledge Base, retrieved
    via semantic search based on current query.

    IMPORTANT: A knowledge base is required for learnings to work.
    Either provide it here or pass it to LearningMachine directly.

    Attributes:
        knowledge: Knowledge base instance (vector store) for storage.
                   REQUIRED - learnings cannot be saved/searched without this.
        model: Model for extraction (if using BACKGROUND mode).
        mode: How learning is extracted. Default: AGENTIC.
        extraction: Extraction settings (only if mode=BACKGROUND).
        schema: Custom schema for learning data. Default: LearnedKnowledge.

        # Agent tools
        enable_agent_tools: Master switch to expose tools to the agent.
        enable_save: If agent_tools enabled, provide save_learning tool.
        enable_search: If agent_tools enabled, provide search_learnings tool.

        # Prompt customization
        system_message: Full override for extraction system message.
        instructions: Custom instructions for what makes a good learning.
        additional_instructions: Extra instructions appended to default.

    Example:
        >>> config = LearnedKnowledgeConfig(
        ...     knowledge=my_knowledge_base,  # Required!
        ...     mode=LearningMode.AGENTIC,    # Agent saves via tool
        ...     enable_agent_tools=True,
        ...     enable_save=True,
        ...     enable_search=True,
        ... )
    """

    # Knowledge base - required for learnings to work
    knowledge: Optional[Any] = None  # agno.knowledge.Knowledge

    # Model for extraction (optional, only needed for BACKGROUND mode)
    model: Optional["Model"] = None

    # Mode and extraction
    mode: LearningMode = LearningMode.AGENTIC
    extraction: Optional[ExtractionConfig] = None
    schema: Optional[Type[Any]] = None

    # Agent tools
    enable_agent_tools: bool = True  # Master switch (default True for learnings)
    enable_save: bool = True  # save_learning tool (if agent_tools enabled)
    enable_search: bool = True  # search_learnings tool (if agent_tools enabled)

    # Prompt customization
    system_message: Optional[str] = None
    instructions: Optional[str] = None
    additional_instructions: Optional[str] = None

    def __post_init__(self):
        """Validate configuration."""
        from agno.utils.log import log_warning

        # Warn if knowledge is missing - learnings won't work without it
        if self.knowledge is None:
            log_warning(
                "LearnedKnowledgeConfig: knowledge base is None. "
                "Learnings cannot be saved or searched without a knowledge base. "
                "Provide a Knowledge instance to LearnedKnowledgeConfig or LearningMachine."
            )

        # Warn if BACKGROUND mode but no model
        if self.mode == LearningMode.BACKGROUND and self.model is None:
            log_warning(
                "LearnedKnowledgeConfig: BACKGROUND mode requires a model for extraction. "
                "Provide a model to LearnedKnowledgeConfig or LearningMachine."
            )

    def __repr__(self) -> str:
        has_knowledge = self.knowledge is not None
        return f"LearnedKnowledgeConfig(mode={self.mode.value}, knowledge={has_knowledge}, enable_agent_tools={self.enable_agent_tools})"


# =============================================================================
# Phase 2 Configurations (Placeholders)
# =============================================================================


@dataclass
class DecisionLogConfig:
    """Configuration for Decision Logs learning type.

    Decision Logs record decisions made by the agent with reasoning
    and context. Useful for auditing and learning from past decisions.

    Scope: AGENT (fixed) — Stored and retrieved by agent_id.

    Note: Deferred to Phase 2.
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # Mode and extraction
    mode: LearningMode = LearningMode.BACKGROUND
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    schema: Optional[Type[Any]] = None

    # Agent tools
    enable_agent_tools: bool = True
    enable_save: bool = True
    enable_search: bool = True

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

    Scope: AGENT (fixed) — Stored and retrieved by agent_id.

    Note: Deferred to Phase 2.
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # Mode and extraction
    mode: LearningMode = LearningMode.BACKGROUND
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    schema: Optional[Type[Any]] = None

    # Prompt customization
    instructions: Optional[str] = None

    def __repr__(self) -> str:
        return "FeedbackConfig(mode=BACKGROUND)"


@dataclass
class SelfImprovementConfig:
    """Configuration for Self-Improvement learning type.

    Self-Improvement proposes updates to agent instructions based
    on feedback patterns and successful interactions.

    Scope: AGENT (fixed) — Stored and retrieved by agent_id.

    Note: Deferred to Phase 3.
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # Mode and extraction
    mode: LearningMode = LearningMode.HITL
    extraction: Optional[ExtractionConfig] = None
    schema: Optional[Type[Any]] = None

    # Prompt customization
    instructions: Optional[str] = None

    def __repr__(self) -> str:
        return "SelfImprovementConfig(mode=HITL)"
