from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from agno.knowledge.document import Document


class VectorDb(ABC):
    """Base class for Vector Databases"""

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
    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        raise NotImplementedError

    @abstractmethod
    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
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

    @abstractmethod
    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_by_content_id(self, content_id: str) -> bool:
        raise NotImplementedError
