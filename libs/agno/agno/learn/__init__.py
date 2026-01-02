"""
Agno Learning Module
====================
Gives agents the ability to learn and remember.

Main Components:
- LearningMachine: Orchestrates all learning capabilities
- Stores: Storage backends for each learning type
- Schemas: Data structures for learnings
- Config: Configuration options

Quick Start:
    >>> from agno.learn import LearningMachine
    >>> from agno.learn.config import UserProfileConfig, LearningMode
    >>>
    >>> # Basic usage - just add to your agent
    >>> learning = LearningMachine(
    ...     db=my_db,
    ...     model=my_model,
    ...     user_profile=True,  # Enable user profile learning
    ... )
    >>>
    >>> # Get context for agent prompt
    >>> context = learning.build_context(user_id="alice")
    >>>
    >>> # Get tools to expose to agent
    >>> tools = learning.get_tools(user_id="alice")
    >>>
    >>> # Process conversation for learnings
    >>> learning.process(messages, user_id="alice")

Learning Types:
- UserProfile: Long-term memories about users (preferences, facts, history)
- SessionContext: Current session state (summary, goals, progress)
- LearnedKnowledge: Reusable insights that apply across users

See Also:
- agno.learn.config: Configuration options
- agno.learn.schemas: Data structures
- agno.learn.stores: Storage backends
"""

from agno.learn.config import (
    ExtractionConfig,
    ExtractionTiming,
    LearnedKnowledgeConfig,
    LearningMode,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.learn.machine import LearningMachine
from agno.learn.schemas import (
    LearnedKnowledge,
    SessionContext,
    UserProfile,
)
from agno.learn.stores import (
    LearnedKnowledgeStore,
    LearningStore,
    SessionContextStore,
    UserProfileStore,
)

__all__ = [
    # Main class
    "LearningMachine",
    # Configs
    "LearningMode",
    "ExtractionTiming",
    "ExtractionConfig",
    "UserProfileConfig",
    "SessionContextConfig",
    "LearnedKnowledgeConfig",
    # Schemas
    "UserProfile",
    "SessionContext",
    "LearnedKnowledge",
    # Stores
    "LearningStore",
    "UserProfileStore",
    "SessionContextStore",
    "LearnedKnowledgeStore",
]
