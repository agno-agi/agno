"""Compatibility stub for V1 PostgresMemoryDb (moved/restructured in V2)."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PostgresMemoryDb:
    """V1-compatible stub for PostgresMemoryDb.

    In V2, the database structure is handled by MemoryManager and db module.
    This stub provides minimal V1 interface compatibility.
    """

    table_name: Optional[str] = None
    db_url: Optional[str] = None

    def __init__(self, table_name: Optional[str] = None, db_url: Optional[str] = None):
        self.table_name = table_name
        self.db_url = db_url
