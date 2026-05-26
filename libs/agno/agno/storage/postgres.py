"""V1 PostgreSQL storage compatibility stub."""

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

from agno.storage.base import Storage


@dataclass
class PostgresStorage(Storage):
    """V1-compatible PostgreSQL storage stub.

    This stub provides the V1 interface that agno_custom expects.
    """

    db_url: str = ""
    table_name: str = ""
    mode: Optional[Literal["user", "team", "workflow"]] = None
    auto_upgrade_schema: bool = False
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        """Initialize metadata."""
        if self.metadata is None:
            self.metadata = {}

    def create(self, **kwargs) -> None:
        """Create a storage entry."""
        pass

    def read(self, storage_id: str) -> Optional[Dict[str, Any]]:
        """Read a storage entry."""
        return None

    def update(self, storage_id: str, **kwargs) -> None:
        """Update a storage entry."""
        pass

    def delete(self, storage_id: str) -> None:
        """Delete a storage entry."""
        pass
