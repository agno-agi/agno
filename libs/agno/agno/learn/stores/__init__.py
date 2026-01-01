"""
LearningMachine Stores
======================
Storage backends for each learning type.

Built-in stores:
- UserProfileStore: Long-term user memory
- SessionContextStore: Current session state
- LearningsStore: Reusable insights with semantic search

Custom stores:
- Implement LearningStore protocol to create your own learning types
- Use from_dict_safe/to_dict_safe helpers for schema parsing
"""

from agno.learn.stores.learnings import LearningsStore
from agno.learn.stores.protocol import (
    LearningStore,
    from_dict_safe,
    to_dict_safe,
)
from agno.learn.stores.session import SessionContextStore
from agno.learn.stores.user import UserProfileStore

__all__ = [
    # Protocol
    "LearningStore",
    # Helpers
    "from_dict_safe",
    "to_dict_safe",
    # Built-in stores
    "UserProfileStore",
    "SessionContextStore",
    "LearningsStore",
]
