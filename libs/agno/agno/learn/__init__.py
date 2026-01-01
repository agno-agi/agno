"""
LearningMachine
===============
Unified learning system for Agno agents.

Quick Start:
```python
    from agno.learn import LearningMachine, UserProfileConfig

    # Simple: enable everything with defaults
    learning = LearningMachine(db=db, model=model)

    # Pick what you want
    learning = LearningMachine(
        db=db,
        model=model,
        user_profile=True,
        session_context=True,
        learned_knowledge=False,
    )

    # Full control
    learning = LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            enable_tool=True,
        ),
    )
```

Components:
- LearningMachine: Main orchestrator
- Configs: UserProfileConfig, SessionContextConfig, KnowledgeConfig
- Schemas: BaseUserProfile, BaseSessionContext, BaseLearning
- Stores: UserProfileStore, SessionContextStore, KnowledgeStore
"""

# Core
# Enums
# Configs
from agno.learn.config import (
    DecisionLogConfig,
    ExtractionConfig,
    ExtractionTiming,
    FeedbackConfig,
    KnowledgeConfig,
    LearningMode,
    SelfImprovementConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.learn.machine import LearningMachine, create_learning_machine

# Schemas
from agno.learn.schemas import (
    BaseDecision,
    BaseFeedback,
    BaseInstructionUpdate,
    BaseLearning,
    BaseSessionContext,
    BaseUserProfile,
)

# Stores
from agno.learn.stores import (
    KnowledgeStore,
    LearningStore,
    SessionContextStore,
    UserProfileStore,
    from_dict_safe,
    to_dict_safe,
)

__all__ = [
    # Core
    "LearningMachine",
    "create_learning_machine",
    # Enums
    "LearningMode",
    "ExtractionTiming",
    # Configs
    "ExtractionConfig",
    "UserProfileConfig",
    "SessionContextConfig",
    "KnowledgeConfig",
    "DecisionLogConfig",
    "FeedbackConfig",
    "SelfImprovementConfig",
    # Schemas
    "BaseUserProfile",
    "BaseSessionContext",
    "BaseLearning",
    "BaseDecision",
    "BaseFeedback",
    "BaseInstructionUpdate",
    # Stores
    "LearningStore",
    "UserProfileStore",
    "SessionContextStore",
    "KnowledgeStore",
    # Helpers
    "from_dict_safe",
    "to_dict_safe",
]
