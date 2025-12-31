"""
LearningMachine Configuration
=============================
Enums and configuration classes for the unified learning system.

Uses dataclasses instead of Pydantic BaseModels to avoid runtime
overhead and validation errors that could break agents mid-run.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional, Type, Union

if TYPE_CHECKING:
    from agno.db.base import AsyncBaseDb, BaseDb
    from agno.models.base import Model


class LearningMode(Enum):
    """How learning is extracted and saved.

    Attributes:
        BACKGROUND: Automatically extract and save learnings in the background.
        AGENTIC: Learning extraction is agent driven via tool usage.
        PROPOSE: Agent proposes learning in chat, user confirms.
        HITL: Background extracts and queues for human approval.
    """

    BACKGROUND = "background"
    AGENTIC = "agentic"
    PROPOSE = "propose"
    HITL = "hitl"


class ExtractionTiming(Enum):
    """When extraction runs relative to LLM response.

    Attributes:
        BEFORE: Runs before LLM call. Adds latency before response.
        PARALLEL: Runs while LLM generates response. Fast, but may
                 duplicate if agent also saves learnings via tool.
        AFTER: Runs after response is returned. Slower, but can
              check what agent saved to avoid duplicates.
    """

    BEFORE = "before"
    PARALLEL = "parallel"
    AFTER = "after"


@dataclass
class ExtractionConfig:
    """Configuration for learning extraction.

    Attributes:
        timing: When to run extraction relative to LLM response.
        run_after_messages: Run extraction after every N messages.
                           Set to 1 for every message, 2 for every other, etc.
    """

    timing: ExtractionTiming = ExtractionTiming.PARALLEL
    run_after_messages: int = 1


@dataclass
class UserProfileConfig:
    """Configuration for User Profile learning type.

    User Profile captures long-term memory about users that persists
    across sessions: name, preferences, communication style, etc.

    Scope: USER (fixed) — Retrieved and stored by user_id.

    Attributes:
        db: Database backend for storage.
        model: Model for extraction.
        mode: How learning is extracted. Default: BACKGROUND.
        extraction: Extraction settings.
        schema: Custom schema for user profile data.
                Default: BaseUserProfile.

        # Agent tool
        enable_tool: Whether to provide update_user_memory tool to agent.

        # Internal extraction tools
        enable_add: Allow adding new profile entries.
        enable_update: Allow updating existing entries.
        enable_delete: Allow deleting entries.
        enable_clear: Allow clearing all profile data.

        # Prompt customization
        system_message: Full override for extraction system message.
        instructions: Custom instructions for what to capture.
        additional_instructions: Extra instructions appended to default.
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # Mode and extraction
    mode: LearningMode = LearningMode.BACKGROUND
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    schema: Optional[Type[Any]] = None

    # Agent tool
    enable_tool: bool = True

    # Internal extraction tools
    enable_add: bool = True
    enable_update: bool = True
    enable_delete: bool = True
    enable_clear: bool = False

    # Prompt customization
    system_message: Optional[str] = None
    instructions: Optional[str] = None
    additional_instructions: Optional[str] = None


@dataclass
class SessionContextConfig:
    """Configuration for Session Context learning type.

    Session Context captures state and summary for the current session:
    what's happened, goals, plans, and progress.

    Scope: SESSION (fixed) — Retrieved and stored by session_id.

    Note: mode is fixed to BACKGROUND. No agent tool is provided
    because session context is system-managed only.

    Attributes:
        db: Database backend for storage.
        model: Model for extraction.
        extraction: Extraction settings.
        schema: Custom schema for session context data.
                Default: BaseSessionContext.

        # Feature flags
        enable_planning: If True, extract goal/plan/progress in addition
                        to summary. If False, extract summary only.

        # Internal extraction tools
        enable_add: Allow adding new context entries.
        enable_update: Allow updating existing entries.
        enable_delete: Allow deleting entries.
        enable_clear: Allow clearing all context data.

        # Prompt customization
        system_message: Full override for extraction system message.
        instructions: Custom instructions for extraction.
        additional_instructions: Extra instructions appended to default.
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # mode is fixed to BACKGROUND - not configurable
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    schema: Optional[Type[Any]] = None

    # Feature flags
    enable_planning: bool = False

    # Internal extraction tools
    enable_add: bool = True
    enable_update: bool = True
    enable_delete: bool = True
    enable_clear: bool = False

    # Prompt customization
    system_message: Optional[str] = None
    instructions: Optional[str] = None
    additional_instructions: Optional[str] = None


@dataclass
class KnowledgeConfig:
    """Configuration for Learned Knowledge learning type.

    Learned Knowledge captures reusable insights and patterns that
    can be shared across users and potentially across agents.

    Scope: KNOWLEDGE (fixed) — Stored in Knowledge Base, retrieved
    via semantic search based on current query.

    Attributes:
        db: Database backend for storage.
        model: Model for extraction.
        mode: How learning is extracted. Default: PROPOSE.
        extraction: Extraction settings (only if mode=BACKGROUND).
        schema: Custom schema for learning data.
                Default: BaseLearning.

        # Agent tool
        enable_tool: Whether to provide save_learning tool to agent.

        # Internal extraction tools
        enable_add: Allow adding new learnings.
        enable_update: Allow updating existing learnings.
        enable_delete: Allow deleting learnings.

        # Prompt customization
        system_message: Full override for extraction system message.
        instructions: Custom instructions for what makes a good learning.
        additional_instructions: Extra instructions appended to default.
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # Mode and extraction
    mode: LearningMode = LearningMode.PROPOSE
    extraction: Optional[ExtractionConfig] = None
    schema: Optional[Type[Any]] = None

    # Agent tool
    enable_tool: bool = True

    # Internal extraction tools
    enable_add: bool = True
    enable_update: bool = True
    enable_delete: bool = True

    # Prompt customization
    system_message: Optional[str] = None
    instructions: Optional[str] = None
    additional_instructions: Optional[str] = None


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

    # Agent tool
    enable_tool: bool = True

    # Internal extraction tools
    enable_add: bool = True
    enable_update: bool = True
    enable_delete: bool = True

    # Prompt customization
    system_message: Optional[str] = None
    instructions: Optional[str] = None
    additional_instructions: Optional[str] = None


@dataclass
class FeedbackConfig:
    """Configuration for Behavioral Feedback learning type.

    Behavioral Feedback captures signals about what worked and what
    didn't: thumbs up/down, corrections, regeneration requests.

    Scope: AGENT (fixed) — Stored and retrieved by agent_id.

    Note: mode is fixed to BACKGROUND. No agent tool - feedback
    is captured from external signals (UI, corrections in chat).

    Note: Deferred to Phase 2.
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # mode is fixed to BACKGROUND
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    schema: Optional[Type[Any]] = None

    # Prompt customization
    instructions: Optional[str] = None


@dataclass
class SelfImprovementConfig:
    """Configuration for Self-Improvement learning type.

    Self-Improvement proposes updates to agent instructions based
    on feedback patterns and successful interactions.

    Scope: AGENT (fixed) — Stored and retrieved by agent_id.

    Note: mode is fixed to HITL. No agent tool - self-improvement
    is system-managed with human approval.

    Note: Deferred to Phase 4.
    """

    # Required fields
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # mode is fixed to HITL
    schema: Optional[Type[Any]] = None

    # Prompt customization
    instructions: Optional[str] = None
