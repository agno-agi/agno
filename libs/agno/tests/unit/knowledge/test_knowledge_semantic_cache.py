"""Unit tests for Knowledge semantic cache behavior."""

import time
from threading import RLock
from typing import Any, Dict, List, Optional, Union

import pytest

from agno.filters import FilterExpr
from agno.knowledge.document import Document
from agno.knowledge.embedder.base import Embedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.base import VectorDb
from agno.vectordb.search import SearchType


class DeterministicEmbedder(Embedder):
    """Simple embedder used for deterministic semantic cache tests."""

    def __init__(self, embedding_map: Dict[str, List[float]], fail: bool = False):
        self.embedding_map = embedding_map
        self.fail = fail
        self.sync_calls = 0
        self.async_calls = 0

    def get_embedding(self, text: str) -> List[float]:
        self.sync_calls += 1
        if self.fail:
            raise RuntimeError("embedder failure")
        return self.embedding_map.get(text, [0.0, 0.0])

    def get_embedding_and_usage(self, text: str):
        return self.get_embedding(text), None

    async def async_get_embedding(self, text: str) -> List[float]:
        self.async_calls += 1
        if self.fail:
            raise RuntimeError("embedder failure")
        return self.embedding_map.get(text, [0.0, 0.0])

    async def async_get_embedding_and_usage(self, text: str):
        return await self.async_get_embedding(text), None


class MockVectorDb(VectorDb):
    """Mock VectorDb that tracks search calls and returns query-specific docs."""

    def __init__(self, embedder: Optional[Embedder] = None):
        self.search_calls: List[Dict[str, Any]] = []
        self.search_type = SearchType.vector
        self.embedder = embedder

    def create(self) -> None:
        pass

    async def async_create(self) -> None:
        pass

    def name_exists(self, name: str) -> bool:
        return False

    async def async_name_exists(self, name: str) -> bool:
        return False

    def id_exists(self, id: str) -> bool:
        return False

    def content_hash_exists(self, content_hash: str) -> bool:
        return False

    def insert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    async def async_insert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    def upsert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    async def async_upsert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    def upsert_available(self) -> bool:
        return True

    def search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        self.search_calls.append({"query": query, "limit": limit, "filters": filters, "search_type": self.search_type})
        return [Document(name="doc", content=f"doc for {query}", meta_data={"query": query})]

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        self.search_calls.append({"query": query, "limit": limit, "filters": filters, "search_type": self.search_type})
        return [Document(name="doc", content=f"doc for {query}", meta_data={"query": query})]

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

    def delete_by_content_id(self, content_id: str) -> bool:
        return True

    def get_supported_search_types(self) -> List[str]:
        return ["vector", "hybrid", "keyword"]


class NonSerializableEmbedder(Embedder):
    """Embedder carrying an RLock to simulate non-serializable runtime fields."""

    def __init__(self):
        self._lock = RLock()

    def get_embedding(self, text: str) -> List[float]:
        if "similar" in text:
            return [0.99, 0.01]
        return [1.0, 0.0]

    def get_embedding_and_usage(self, text: str):
        return self.get_embedding(text), None

    async def async_get_embedding(self, text: str) -> List[float]:
        return self.get_embedding(text)

    async def async_get_embedding_and_usage(self, text: str):
        return self.get_embedding(text), None


def _embedding_map() -> Dict[str, List[float]]:
    return {
        "question one": [1.0, 0.0],
        "question one similar": [0.99, 0.01],
        "question one weakly similar": [0.7, 0.3],
        "question two": [0.0, 1.0],
    }


def test_semantic_cache_hit_skips_second_vector_search():
    embedder = DeterministicEmbedder(_embedding_map())
    mock_db = MockVectorDb(embedder=embedder)
    knowledge = Knowledge(
        vector_db=mock_db,
        enable_semantic_cache=True,
        semantic_cache_similarity_threshold=0.95,
    )

    first = knowledge.search("question one")
    second = knowledge.search("question one similar")

    assert len(mock_db.search_calls) == 1
    assert first[0].content == second[0].content


def test_semantic_cache_threshold_gating_causes_miss():
    embedder = DeterministicEmbedder(_embedding_map())
    mock_db = MockVectorDb(embedder=embedder)
    knowledge = Knowledge(
        vector_db=mock_db,
        enable_semantic_cache=True,
        semantic_cache_similarity_threshold=0.95,
    )

    knowledge.search("question one")
    second = knowledge.search("question one weakly similar")

    assert len(mock_db.search_calls) == 2
    assert second[0].content == "doc for question one weakly similar"


def test_semantic_cache_ttl_expiration():
    embedder = DeterministicEmbedder(_embedding_map())
    mock_db = MockVectorDb(embedder=embedder)
    knowledge = Knowledge(
        vector_db=mock_db,
        enable_semantic_cache=True,
        semantic_cache_similarity_threshold=0.95,
        semantic_cache_ttl=0,
    )

    knowledge.search("question one")
    time.sleep(0.01)
    knowledge.search("question one similar")

    assert len(mock_db.search_calls) == 2


def test_semantic_cache_max_entries_eviction():
    embedder = DeterministicEmbedder(_embedding_map())
    mock_db = MockVectorDb(embedder=embedder)
    knowledge = Knowledge(
        vector_db=mock_db,
        enable_semantic_cache=True,
        semantic_cache_similarity_threshold=0.95,
        semantic_cache_max_entries=1,
    )

    knowledge.search("question one")
    knowledge.search("question two")
    knowledge.search("question one similar")

    assert len(mock_db.search_calls) == 3


def test_semantic_cache_context_isolation_for_filters_search_type_and_limit():
    embedder = DeterministicEmbedder(_embedding_map())
    mock_db = MockVectorDb(embedder=embedder)
    knowledge = Knowledge(
        vector_db=mock_db,
        enable_semantic_cache=True,
        semantic_cache_similarity_threshold=0.95,
    )

    knowledge.search("question one", filters={"kind": "a"}, max_results=3, search_type="vector")
    knowledge.search("question one similar", filters={"kind": "b"}, max_results=3, search_type="vector")
    knowledge.search("question one similar", filters={"kind": "a"}, max_results=4, search_type="vector")
    knowledge.search("question one similar", filters={"kind": "a"}, max_results=3, search_type="hybrid")
    knowledge.search("question one similar", filters={"kind": "a"}, max_results=3, search_type="vector")

    # First four calls miss due to context mismatch; final call hits first entry context.
    assert len(mock_db.search_calls) == 4


@pytest.mark.asyncio
async def test_async_semantic_cache_hit_skips_second_vector_search():
    embedder = DeterministicEmbedder(_embedding_map())
    mock_db = MockVectorDb(embedder=embedder)
    knowledge = Knowledge(
        vector_db=mock_db,
        enable_semantic_cache=True,
        semantic_cache_similarity_threshold=0.95,
    )

    await knowledge.asearch("question one")
    second = await knowledge.asearch("question one similar")

    assert len(mock_db.search_calls) == 1
    assert second[0].content == "doc for question one"


def test_semantic_cache_fail_open_when_no_embedder():
    mock_db = MockVectorDb(embedder=None)
    knowledge = Knowledge(
        vector_db=mock_db,
        enable_semantic_cache=True,
        semantic_cache_similarity_threshold=0.95,
    )

    knowledge.search("question one")
    knowledge.search("question one similar")

    assert len(mock_db.search_calls) == 2


def test_semantic_cache_fail_open_on_embedder_error():
    failing_embedder = DeterministicEmbedder(_embedding_map(), fail=True)
    mock_db = MockVectorDb(embedder=None)
    knowledge = Knowledge(
        vector_db=mock_db,
        enable_semantic_cache=True,
        semantic_cache_similarity_threshold=0.95,
        semantic_cache_embedder=failing_embedder,
    )

    knowledge.search("question one")
    knowledge.search("question one similar")

    assert len(mock_db.search_calls) == 2


def test_cached_documents_are_immutable_from_caller_mutations():
    embedder = DeterministicEmbedder(_embedding_map())
    mock_db = MockVectorDb(embedder=embedder)
    knowledge = Knowledge(
        vector_db=mock_db,
        enable_semantic_cache=True,
        semantic_cache_similarity_threshold=0.95,
    )

    first = knowledge.search("question one")
    first[0].meta_data["mutated"] = True

    second = knowledge.search("question one similar")
    assert "mutated" not in second[0].meta_data

    second[0].meta_data["another_mutation"] = True
    third = knowledge.search("question one similar")
    assert "another_mutation" not in third[0].meta_data
    assert len(mock_db.search_calls) == 1


@pytest.mark.asyncio
async def test_clear_semantic_cache_and_aclear_semantic_cache():
    embedder = DeterministicEmbedder(_embedding_map())
    mock_db = MockVectorDb(embedder=embedder)
    knowledge = Knowledge(
        vector_db=mock_db,
        enable_semantic_cache=True,
        semantic_cache_similarity_threshold=0.95,
    )

    knowledge.search("question one")
    knowledge.clear_semantic_cache()
    knowledge.search("question one similar")

    assert len(mock_db.search_calls) == 2

    knowledge.clear_semantic_cache()
    await knowledge.asearch("question one")
    await knowledge.aclear_semantic_cache()
    await knowledge.asearch("question one similar")

    assert len(mock_db.search_calls) == 4


def test_semantic_cache_handles_non_serializable_document_fields():
    embedder = NonSerializableEmbedder()
    mock_db = MockVectorDb(embedder=embedder)

    def _search_with_embedder_doc(
        query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        mock_db.search_calls.append({"query": query, "limit": limit, "filters": filters, "search_type": mock_db.search_type})
        return [Document(name="doc", content=f"doc for {query}", meta_data={"query": query}, embedder=embedder)]

    mock_db.search = _search_with_embedder_doc  # type: ignore[method-assign]

    knowledge = Knowledge(
        vector_db=mock_db,
        enable_semantic_cache=True,
        semantic_cache_similarity_threshold=0.95,
    )

    first = knowledge.search("question one")
    second = knowledge.search("question one similar")

    assert len(mock_db.search_calls) == 1
    assert first[0].content == second[0].content


def test_semantic_cache_handles_non_serializable_metadata_and_usage():
    embedder = NonSerializableEmbedder()
    mock_db = MockVectorDb(embedder=embedder)

    def _search_with_non_serializable_fields(
        query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        mock_db.search_calls.append({"query": query, "limit": limit, "filters": filters, "search_type": mock_db.search_type})
        return [
            Document(
                name="doc",
                content=f"doc for {query}",
                meta_data={"query": query, "lock": RLock()},
                usage={"lock": RLock(), "tokens": 1},
                embedder=embedder,
            )
        ]

    mock_db.search = _search_with_non_serializable_fields  # type: ignore[method-assign]

    knowledge = Knowledge(
        vector_db=mock_db,
        enable_semantic_cache=True,
        semantic_cache_similarity_threshold=0.95,
    )

    first = knowledge.search("question one")
    second = knowledge.search("question one similar")

    assert len(mock_db.search_calls) == 1
    assert first[0].content == second[0].content
    assert isinstance(second[0].meta_data, dict)


def test_semantic_cache_hit_preserves_embedding_and_embedder():
    embedder = DeterministicEmbedder(_embedding_map())
    mock_db = MockVectorDb(embedder=embedder)

    def _search_with_embedding(
        query: str, limit: int = 5, filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> List[Document]:
        mock_db.search_calls.append({"query": query, "limit": limit, "filters": filters, "search_type": mock_db.search_type})
        return [
            Document(
                name="doc",
                content=f"doc for {query}",
                meta_data={"query": query},
                embedder=embedder,
                embedding=[0.3, 0.7],
            )
        ]

    mock_db.search = _search_with_embedding  # type: ignore[method-assign]

    knowledge = Knowledge(
        vector_db=mock_db,
        enable_semantic_cache=True,
        semantic_cache_similarity_threshold=0.95,
    )

    first = knowledge.search("question one")
    second = knowledge.search("question one similar")

    assert len(mock_db.search_calls) == 1
    assert first[0].embedding == [0.3, 0.7]
    assert second[0].embedding == [0.3, 0.7]
    assert second[0].embedder is embedder


def test_semantic_cache_invalid_ttl_raises_value_error():
    mock_db = MockVectorDb(embedder=None)

    with pytest.raises(ValueError, match="semantic_cache_ttl"):
        Knowledge(
            vector_db=mock_db,
            enable_semantic_cache=True,
            semantic_cache_ttl=-1,
        )
