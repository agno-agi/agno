"""Regression tests for explicit zero-result knowledge searches."""

from typing import List

import pytest

from agno.knowledge.document import Document
from agno.knowledge.filesystem import FileSystemKnowledge
from agno.knowledge.knowledge import Knowledge


class RecordingVectorDb:
    """Minimal vector database that records limits and exposes sync/async paths."""

    def __init__(self):
        self.requested_limits: List[int] = []

    def exists(self) -> bool:
        return True

    def create(self) -> None:  # pragma: no cover - exists() is always true
        raise AssertionError("create should not be called")

    def search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        self.requested_limits.append(limit)
        return [Document(id=str(i), content=f"doc {i}") for i in range(limit)]

    async def async_search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        return self.search(query=query, limit=limit, filters=filters)


@pytest.mark.parametrize("method_name", ["_list_files", "_grep", "retrieve"])
def test_filesystem_knowledge_honors_zero_max_results(tmp_path, method_name: str):
    """File-backed search must not replace an explicit zero with its default limit."""
    (tmp_path / "matching.txt").write_text("matching content")
    knowledge = FileSystemKnowledge(base_dir=str(tmp_path), max_results=7)

    method = getattr(knowledge, method_name)
    query = "*" if method_name == "_list_files" else "matching"

    assert method(query, max_results=0) == []


@pytest.mark.asyncio
async def test_filesystem_knowledge_async_retrieve_honors_zero_max_results(tmp_path):
    """The async protocol path must preserve the same zero-result contract."""
    (tmp_path / "matching.txt").write_text("matching content")
    knowledge = FileSystemKnowledge(base_dir=str(tmp_path), max_results=7)

    assert await knowledge.aretrieve("matching", max_results=0) == []


def test_vector_knowledge_search_honors_zero_max_results():
    """Sync vector search returns early instead of querying for default results."""
    db = RecordingVectorDb()
    knowledge = Knowledge(vector_db=db, max_results=7)

    results = knowledge.search("query", max_results=0)

    assert db.requested_limits == []
    assert results == []


@pytest.mark.asyncio
async def test_vector_knowledge_async_search_honors_zero_max_results():
    """Async vector search returns early instead of querying for default results."""
    db = RecordingVectorDb()
    knowledge = Knowledge(vector_db=db, max_results=7)

    results = await knowledge.asearch("query", max_results=0)

    assert db.requested_limits == []
    assert results == []


def test_page_knowledge_search_honors_zero_max_results():
    """Page search returns early because its coordinator rejects a zero limit."""
    knowledge = Knowledge.__new__(Knowledge)
    knowledge.page_store = object()
    knowledge.max_results = 7
    knowledge.reranker = None

    def fail_search_pages(*args, **kwargs):
        raise AssertionError("search_pages should not be called")

    knowledge.search_pages = fail_search_pages

    assert knowledge.search("query", max_results=0) == []


@pytest.mark.asyncio
async def test_page_knowledge_async_search_honors_zero_max_results():
    """Async page search preserves the same early-return contract."""
    knowledge = Knowledge.__new__(Knowledge)
    knowledge.page_store = object()
    knowledge.max_results = 7
    knowledge.reranker = None

    async def fail_search_pages(*args, **kwargs):
        raise AssertionError("asearch_pages should not be called")

    knowledge.asearch_pages = fail_search_pages

    assert await knowledge.asearch("query", max_results=0) == []
