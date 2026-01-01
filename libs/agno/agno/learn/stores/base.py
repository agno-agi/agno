"""
LearningMachine Base Store
==========================
Abstract base class and utilities for learning stores.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseLearningStore(ABC):
    """Abstract base class for learning storage backends.

    Each learning type has its own store implementation that handles:
    - Retrieval (get/search)
    - Storage (save/update)
    - Extraction (using LLM to extract learnings from conversation)

    Stores use dataclass schemas (not Pydantic) with from_dict()/to_dict()
    methods that never raise exceptions.
    """

    @abstractmethod
    def get(self, identifier: str) -> Optional[Any]:
        """Retrieve a learning by its identifier.

        Args:
            identifier: The unique identifier (user_id, session_id, etc.)

        Returns:
            The learning data as a dataclass instance, or None if not found.
        """
        pass

    @abstractmethod
    async def aget(self, identifier: str) -> Optional[Any]:
        """Async version of get."""
        pass

    @abstractmethod
    def save(self, identifier: str, data: Any) -> None:
        """Save or update a learning.

        Args:
            identifier: The unique identifier (user_id, session_id, etc.)
            data: The learning data to save (dataclass instance).
        """
        pass

    @abstractmethod
    async def asave(self, identifier: str, data: Any) -> None:
        """Async version of save."""
        pass


def to_dict_safe(obj: Any) -> Dict[str, Any]:
    """Convert any object to dict safely.

    Handles:
    - Dataclasses with to_dict() method
    - Plain dataclasses via asdict()
    - Dicts (returned as-is)

    Returns empty dict on failure.
    """
    if obj is None:
        return {}

    try:
        # Our schemas have to_dict()
        if hasattr(obj, "to_dict"):
            return obj.to_dict()

        # Plain dataclass
        from dataclasses import asdict, is_dataclass

        if is_dataclass(obj) and not isinstance(obj, type):
            return asdict(obj)

        # Already a dict
        if isinstance(obj, dict):
            return obj

        return {}
    except Exception:
        return {}


def from_dict_safe(schema: Any, data: Any) -> Optional[Any]:
    """Parse data into schema instance safely.

    Handles:
    - Schemas with from_dict() class method
    - Plain dataclasses via constructor

    Returns None on failure.
    """
    if data is None or schema is None:
        return None

    try:
        # Our schemas have from_dict()
        if hasattr(schema, "from_dict"):
            return schema.from_dict(data)

        # Plain dataclass - try direct construction
        from dataclasses import is_dataclass

        if is_dataclass(schema):
            if isinstance(data, str):
                import json

                data = json.loads(data)
            if isinstance(data, dict):
                return schema(**data)

        return None
    except Exception:
        return None
