from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from agno.document import Document


class VectorDb(ABC):
    """Base class for Vector Databases"""

    @abstractmethod
    def create(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def async_create(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def doc_exists(self, document: Document) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def async_doc_exists(self, document: Document) -> bool:
        raise NotImplementedError

    @abstractmethod
    def name_exists(self, name: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def async_name_exists(self, name: str) -> bool:
        raise NotImplementedError

    def id_exists(self, id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError

    def upsert_available(self) -> bool:
        return False

    @abstractmethod
    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        raise NotImplementedError

    @abstractmethod
    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        raise NotImplementedError

    def vector_search(self, query: str, limit: int = 5) -> List[Document]:
        raise NotImplementedError

    def keyword_search(self, query: str, limit: int = 5) -> List[Document]:
        raise NotImplementedError

    def hybrid_search(self, query: str, limit: int = 5) -> List[Document]:
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
