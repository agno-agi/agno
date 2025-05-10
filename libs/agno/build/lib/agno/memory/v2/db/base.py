from abc import ABC, abstractmethod
from typing import List, Optional

from agno.memory.v2.db.schema import MemoryRow


class MemoryDb(ABC):
    """Base class for the Memory Database."""

    @abstractmethod
    def create(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def memory_exists(self, memory: MemoryRow) -> bool:
        raise NotImplementedError

    @abstractmethod
    def read_memories(
        self, user_id: Optional[str] = None, limit: Optional[int] = None, sort: Optional[str] = None
    ) -> List[MemoryRow]:
        raise NotImplementedError

    @abstractmethod
    def upsert_memory(self, memory: MemoryRow) -> Optional[MemoryRow]:
        raise NotImplementedError

    @abstractmethod
    def delete_memory(self, memory_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def drop_table(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def table_exists(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> bool:
        raise NotImplementedError
