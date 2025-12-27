from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from agno.knowledge.document import Document
from agno.utils.log import log_warning
from agno.utils.string import generate_id


class VectorDb(ABC):
    """Base class for Vector Databases"""

    def __init__(self, *, id: Optional[str] = None, name: Optional[str] = None, description: Optional[str] = None):
        """Initialize base VectorDb.

        Args:
            id: Optional custom ID. If not provided, an id will be generated.
            name: Optional name for the vector database.
            description: Optional description for the vector database.
        """
        if name is None:
            name = self.__class__.__name__

        self.name = name
        self.description = description
        # Last resort fallback to generate id from name if ID not specified
        self.id = id if id else generate_id(name)

    @abstractmethod
    def create(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def async_create(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def name_exists(self, name: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def async_name_exists(self, name: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def id_exists(self, id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def content_hash_exists(self, content_hash: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        raise NotImplementedError

    def upsert_available(self) -> bool:
        return False

    @abstractmethod
    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(self, query: str, limit: int = 5, filters: Optional[Any] = None) -> List[Document]:
        raise NotImplementedError

    @abstractmethod
    async def async_search(self, query: str, limit: int = 5, filters: Optional[Any] = None) -> List[Document]:
        raise NotImplementedError

    @abstractmethod
    def drop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def async_drop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def exists(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def async_exists(self) -> bool:
        raise NotImplementedError

    def optimize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete_by_id(self, id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete_by_name(self, name: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        raise NotImplementedError

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update the metadata for documents with the given content_id.

        Default implementation logs a warning. Subclasses should override this method
        to provide their specific implementation.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
        log_warning(
            f"{self.__class__.__name__}.update_metadata() is not implemented. "
            f"Metadata update for content_id '{content_id}' was skipped."
        )

    @abstractmethod
    def delete_by_content_id(self, content_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_supported_search_types(self) -> List[str]:
        raise NotImplementedError
