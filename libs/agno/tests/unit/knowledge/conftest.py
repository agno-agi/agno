"""Pytest fixtures for knowledge testing."""

from typing import Any, Dict, List, Optional, Tuple

import pytest

from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.base import VectorDb


class StubVectorDb(VectorDb):
    """Records what Knowledge hands the backend on every call."""

    def __init__(self, content_exists: bool = False, upsert_supported: bool = False) -> None:
        self.content_exists = content_exists
        self.upsert_supported = upsert_supported
        self.writes: List[Tuple[str, Optional[str]]] = []
        self.exists_calls: List[Tuple[str, Optional[str]]] = []
        self.inserted_documents: List[Document] = []
        self.upserted_documents: List[Document] = []
        self.search_calls: List[Dict[str, Any]] = []

    @property
    def owners(self) -> List[Optional[str]]:
        """The owner of every write, in write order."""
        return [user_id for _, user_id in self.writes]

    def create(self) -> None:
        pass

    async def async_create(self) -> None:
        pass

    def name_exists(self, name: str) -> bool:
        return False

    def async_name_exists(self, name: str) -> bool:
        return False

    def id_exists(self, id: str) -> bool:
        return False

    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        # Mirrors the column-based backends: None matches any owner, a set user_id only that owner's rows.
        self.exists_calls.append((content_hash, user_id))
        if self.content_exists:
            return True
        if user_id is None:
            return any(written == content_hash for written, _ in self.writes)
        return (content_hash, user_id) in self.writes

    def upsert_available(self) -> bool:
        return self.upsert_supported

    def insert(self, content_hash: str, documents: List[Document], filters=None, user_id: Optional[str] = None) -> None:
        self.writes.append((content_hash, user_id))
        self.inserted_documents.extend(documents)

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters=None, user_id: Optional[str] = None
    ) -> None:
        self.insert(content_hash, documents, filters, user_id)

    def upsert(self, content_hash: str, documents: List[Document], filters=None, user_id: Optional[str] = None) -> None:
        self.writes.append((content_hash, user_id))
        self.upserted_documents.extend(documents)

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters=None, user_id: Optional[str] = None
    ) -> None:
        self.upsert(content_hash, documents, filters, user_id)

    def search(self, query: str, limit: int = 5, filters=None, user_id: Optional[str] = None) -> List[Document]:
        self.search_calls.append({"query": query, "limit": limit, "filters": filters, "user_id": user_id})
        return []

    async def async_search(
        self, query: str, limit: int = 5, filters=None, user_id: Optional[str] = None
    ) -> List[Document]:
        return self.search(query, limit, filters, user_id)

    def drop(self) -> None:
        pass

    async def async_drop(self) -> None:
        pass

    def exists(self) -> bool:
        return True

    async def async_exists(self) -> bool:
        return True

    def delete(self) -> bool:
        return True

    def delete_by_id(self, id: str) -> bool:
        return True

    def delete_by_name(self, name: str) -> bool:
        return True

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        return True

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        pass

    def delete_by_content_id(self, content_id: str, user_id: Optional[str] = None) -> bool:
        return True

    def get_supported_search_types(self) -> List[str]:
        return ["vector"]


@pytest.fixture
def vector_db() -> StubVectorDb:
    return StubVectorDb()


@pytest.fixture
def knowledge(vector_db) -> Knowledge:
    return Knowledge(vector_db=vector_db)
