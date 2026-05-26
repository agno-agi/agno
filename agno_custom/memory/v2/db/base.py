"""V1 memory database base class compatibility stub.

V1 had: agno.memory.v2.db.base.MemoryDb
V2 uses: Different structure with agno.db and agno.memory

This stub provides a V1-compatible interface for MemoryDb.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class MemoryDb(ABC):
    """V1-compatible base class for memory databases.

    This is a stub providing the V1 interface that agno_custom expects.
    In V2, memory is handled differently through agno.db and agno.memory.
    """

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
