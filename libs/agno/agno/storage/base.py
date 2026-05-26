"""V1 storage base class compatibility stub."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class Storage(ABC):
    """V1-compatible base storage class."""

    @abstractmethod
    def create(self, **kwargs) -> None:
        """Create a storage entry."""
        pass

    @abstractmethod
    def read(self, storage_id: str) -> Optional[Dict[str, Any]]:
        """Read a storage entry."""
        pass

    @abstractmethod
    def update(self, storage_id: str, **kwargs) -> None:
        """Update a storage entry."""
        pass

    @abstractmethod
    def delete(self, storage_id: str) -> None:
        """Delete a storage entry."""
        pass
