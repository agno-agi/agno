"""Knowledge-level reranking: over-fetch, trimming and failure handling."""

from typing import Dict, List, Optional

import pytest

from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.base import Reranker


class StubVectorDb:
    """Records the limit it was asked for and returns that many documents."""

    def __init__(self, available: int = 100):
        self.available = available
        self.requested_limit: Optional[int] = None

    def exists(self) -> bool:
        return True

    def create(self) -> None:  # pragma: no cover - exists() is always True
        raise AssertionError("create should not be called")

    def search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        self.requested_limit = limit
        count = min(limit, self.available)
        return [Document(id=str(i), content=f"doc {i}") for i in range(count)]

    async def async_search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        return self.search(query=query, limit=limit, filters=filters)


class NoAsyncVectorDb(StubVectorDb):
    """Exercises the asearch fallback for adapters without async support."""

    async def async_search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        raise NotImplementedError


class ReverseReranker(Reranker):
    """Reverses order so the effect of reranking is observable."""

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        return list(reversed(documents))


class FailingReranker(Reranker):
    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        raise RuntimeError("reranker unavailable")


def test_search_without_reranker_is_unchanged():
    db = StubVectorDb()
    knowledge = Knowledge(vector_db=db)

    results = knowledge.search("q", max_results=5)

    assert db.requested_limit == 5
    assert len(results) == 5


def test_search_over_fetches_when_reranker_is_set():
    db = StubVectorDb()
    knowledge = Knowledge(vector_db=db, reranker=ReverseReranker(), rerank_multiplier=5)

    results = knowledge.search("q", max_results=5)

    assert db.requested_limit == 25
    assert len(results) == 5
    # Reversing 25 candidates surfaces the tail, which plain search would never return.
    assert results[0].id == "24"


def test_over_fetch_is_capped():
    db = StubVectorDb()
    knowledge = Knowledge(vector_db=db, reranker=ReverseReranker(), rerank_multiplier=5, max_rerank_candidates=30)

    knowledge.search("q", max_results=10)

    assert db.requested_limit == 30


def test_reranker_failure_falls_back_to_vector_db_order():
    db = StubVectorDb()
    knowledge = Knowledge(vector_db=db, reranker=FailingReranker())

    results = knowledge.search("q", max_results=5)

    assert len(results) == 5
    assert results[0].id == "0"


def test_fewer_candidates_than_requested_is_not_padded():
    db = StubVectorDb(available=3)
    knowledge = Knowledge(vector_db=db, reranker=ReverseReranker())

    results = knowledge.search("q", max_results=5)

    assert len(results) == 3


@pytest.mark.asyncio
async def test_asearch_applies_reranker():
    db = StubVectorDb()
    knowledge = Knowledge(vector_db=db, reranker=ReverseReranker())

    results = await knowledge.asearch("q", max_results=5)

    assert db.requested_limit == 25
    assert results[0].id == "24"


@pytest.mark.asyncio
async def test_asearch_applies_reranker_on_sync_fallback():
    db = NoAsyncVectorDb()
    knowledge = Knowledge(vector_db=db, reranker=ReverseReranker())

    results = await knowledge.asearch("q", max_results=5)

    assert db.requested_limit == 25
    assert results[0].id == "24"


@pytest.mark.parametrize("multiplier", [0, -1, True])
def test_invalid_rerank_multiplier_is_rejected(multiplier):
    with pytest.raises(ValueError, match="rerank_multiplier"):
        Knowledge(vector_db=StubVectorDb(), rerank_multiplier=multiplier)


@pytest.mark.parametrize("candidates", [0, -1, True])
def test_invalid_max_rerank_candidates_is_rejected(candidates):
    with pytest.raises(ValueError, match="max_rerank_candidates"):
        Knowledge(vector_db=StubVectorDb(), max_rerank_candidates=candidates)


class ValueErrorReranker(Reranker):
    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        raise ValueError("misconfigured")


def test_reranker_value_error_propagates():
    # Misconfiguration must surface rather than degrade to unreranked results.
    knowledge = Knowledge(vector_db=StubVectorDb(), reranker=ValueErrorReranker())

    with pytest.raises(ValueError, match="misconfigured"):
        knowledge.search("q", max_results=5)


@pytest.mark.asyncio
async def test_reranker_value_error_propagates_async():
    knowledge = Knowledge(vector_db=StubVectorDb(), reranker=ValueErrorReranker())

    with pytest.raises(ValueError, match="misconfigured"):
        await knowledge.asearch("q", max_results=5)


def test_search_limit_never_drops_below_requested_results():
    # The ceiling caps the widening, not the caller's own request.
    knowledge = Knowledge(
        vector_db=StubVectorDb(), reranker=ReverseReranker(), rerank_multiplier=5, max_rerank_candidates=100
    )

    assert knowledge._search_limit(150) == 150


def test_over_fetch_is_capped_between_requested_and_ceiling():
    knowledge = Knowledge(
        vector_db=StubVectorDb(), reranker=ReverseReranker(), rerank_multiplier=5, max_rerank_candidates=100
    )

    assert knowledge._search_limit(10) == 50
    assert knowledge._search_limit(30) == 100


def test_large_max_results_returns_everything_requested():
    db = StubVectorDb(available=200)
    knowledge = Knowledge(vector_db=db, reranker=ReverseReranker(), max_rerank_candidates=100)

    results = knowledge.search("q", max_results=150)

    assert db.requested_limit == 150
    assert len(results) == 150


@pytest.mark.asyncio
async def test_async_rerank_does_not_block_the_event_loop():
    import asyncio
    import threading

    main_thread = threading.get_ident()
    seen: List[int] = []

    class ThreadRecordingReranker(Reranker):
        def rerank(self, query: str, documents: List[Document]) -> List[Document]:
            seen.append(threading.get_ident())
            return documents

    knowledge = Knowledge(vector_db=StubVectorDb(), reranker=ThreadRecordingReranker())
    await knowledge.asearch("q", max_results=5)

    assert seen and seen[0] != main_thread
    assert asyncio.get_running_loop().is_running()


def test_page_store_results_are_reranked():
    # Page-backed knowledge returns before the vector db, so it needs its own wiring.
    from agno.knowledge.page import SearchResult

    class StubPageStore:
        pass

    recorded: Dict[str, int] = {}

    knowledge = Knowledge.__new__(Knowledge)
    knowledge.page_store = StubPageStore()
    knowledge.max_results = 10
    knowledge.reranker = ReverseReranker()
    knowledge.rerank_multiplier = 5
    knowledge.max_rerank_candidates = 100

    def fake_search_pages(query, *, limit=10, **kwargs):
        recorded["limit"] = limit
        return SearchResult(results=[], partial=False)

    knowledge.search_pages = fake_search_pages  # type: ignore[method-assign]
    knowledge._page_documents = staticmethod(  # type: ignore[method-assign]
        lambda result: [Document(id=str(i), content=f"doc {i}") for i in range(25)]
    )

    results = knowledge.search("q", max_results=5)

    assert recorded["limit"] == 25
    assert len(results) == 5
    assert results[0].id == "24"
