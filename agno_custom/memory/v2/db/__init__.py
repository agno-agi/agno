"""V2 DB compatibility stubs for V1→V2 migration."""

from agno_custom.memory.v2.db.base import MemoryDb
from agno_custom.memory.v2.db.postgres import PostgresMemoryDb
from agno_custom.memory.v2.db.schema import MemoryRow

__all__ = ["MemoryDb", "MemoryRow", "PostgresMemoryDb"]
