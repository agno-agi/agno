"""V1 PostgreSQL memory database compatibility stub."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agno.memory.v2.db.base import MemoryDb


@dataclass
class PostgresMemoryDb(MemoryDb):
    """V1-compatible PostgreSQL memory database stub.

    This stub provides a V1-compatible interface while using V2 memory structure.
    """

    table_name: str = "memories"
    db_url: str = ""

    def create_memory(self, **kwargs) -> None:
        """Create a memory entry."""
        pass

    def read_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Read a memory entry."""
        return None

    def update_memory(self, memory_id: str, **kwargs) -> None:
        """Update a memory entry."""
        pass

    def delete_memory(self, memory_id: str) -> None:
        """Delete a memory entry."""
        pass

    def search_memories(self, query: str, **kwargs) -> List[Dict[str, Any]]:
        """Search memories."""
        return []
