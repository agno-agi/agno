"""V1 memory database base class compatibility stub."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class MemoryDb(ABC):
    """V1-compatible base class for memory databases."""

    @abstractmethod
    def create_memory(self, **kwargs) -> None:
        """Create a memory entry."""
        pass

    @abstractmethod
    def read_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Read a memory entry."""
        pass

    @abstractmethod
    def update_memory(self, memory_id: str, **kwargs) -> None:
        """Update a memory entry."""
        pass

    @abstractmethod
    def delete_memory(self, memory_id: str) -> None:
        """Delete a memory entry."""
        pass

    @abstractmethod
    def search_memories(self, query: str, **kwargs) -> List[Dict[str, Any]]:
        """Search memories."""
        pass
