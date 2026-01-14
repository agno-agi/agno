"""
Agno Learning Module
====================
Gives agents the ability to learn and remember.

Main Components:
- LearningMachine: Unified learning system
- Config: Configuration for learning types
- Schemas: Data structures for learning types
- Stores: Storage backends for learning types
"""

from agno.learn.config import (
    EntityMemoryConfig,
    LearnedKnowledgeConfig,
    LearningMode,
    MemoriesConfig,
    SessionContextConfig,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.learn.machine import LearningMachine
from agno.learn.schemas import (
    EntityMemory,
    LearnedKnowledge,
    Memories,
    SessionContext,
    UserProfile,
)
from agno.learn.stores import (
    EntityMemoryStore,
    LearnedKnowledgeStore,
    LearningStore,
    MemoriesStore,
    SessionContextStore,
    UserMemoryStore,
    UserProfileStore,
)

__all__ = [
    # Main class
    "LearningMachine",
    # Configs
    "LearningMode",
    "UserProfileConfig",
    "UserMemoryConfig",
    "MemoriesConfig",  # Backwards compatibility alias
    "EntityMemoryConfig",
    "SessionContextConfig",
    "LearnedKnowledgeConfig",
    # Schemas
    "UserProfile",
    "Memories",
    "EntityMemory",
    "SessionContext",
    "LearnedKnowledge",
    # Stores
    "LearningStore",
    "UserProfileStore",
    "UserMemoryStore",
    "MemoriesStore",  # Backwards compatibility alias
    "SessionContextStore",
    "LearnedKnowledgeStore",
    "EntityMemoryStore",
]
