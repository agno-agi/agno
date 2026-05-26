"""Storage compatibility layer for V1→V2 migration.

V1 had: agno.storage.postgres.PostgresStorage
V2 has: Different structure in agno.db and agno.session

This module provides V1-compatible imports that map to V2 equivalents or stubs.
"""

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional


@dataclass
class PostgresStorage:
    """V1-compatible stub for PostgresStorage.

    In V2, storage is handled differently through:
    - agno.db.base.BaseDb
    - agno.session management
    - agno.storage.base.Storage (if it exists)

    This stub provides minimal V1 interface compatibility.
    """

    db_url: str
    table_name: str
    mode: Optional[Literal["user", "team", "workflow"]] = None
    auto_upgrade_schema: bool = False
    metadata: Dict[str, Any] = None

    def __init__(
        self,
        db_url: str,
        table_name: str,
        mode: Optional[Literal["user", "team", "workflow"]] = None,
        auto_upgrade_schema: bool = False,
    ):
        self.db_url = db_url
        self.table_name = table_name
        self.mode = mode
        self.auto_upgrade_schema = auto_upgrade_schema
        self.metadata = {}


__all__ = ["PostgresStorage"]
