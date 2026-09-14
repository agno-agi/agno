"""Candidate pool widening for vector db rerankers that select a subset."""

import asyncio
import threading
from typing import ClassVar, Dict, List, Optional

import pytest

from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.base import Reranker


class ReverseReranker(Reranker):
    """Scores nothing, just reverses order so the effect of reranking is observable."""

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        return list(reversed(documents))


class PoolReranker(ReverseReranker):
    """A subset-selecting reranker, so Knowledge widens the fetch for it."""

    needs_candidate_pool: ClassVar[bool] = True


class StubVectorDb:
    """Records the limit it was asked for, returns that many documents, and applies
    its reranker the way the real adapters do."""

    def __init__(self, available: int = 100, reranker: Optional[Reranker] = None):
        self.available = available
        self.reranker = reranker
        self.requested_limit: Optional[int] = None

    def exists(self) -> bool:
        return True

    def create(self) -> None:  # pragma: no cover - exists() is always True
        raise AssertionError("create should not be called")

    def search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        self.requested_limit = limit
        count = min(limit, self.available)
        documents = [Document(id=str(i), content=f"doc {i}") for i in range(count)]
        if self.reranker is not None:
            documents = self.reranker.rerank(query=query, documents=documents)
        return documents

    async def async_search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        return self.search(query=query, limit=limit, filters=filters)


class NoAsyncVectorDb(StubVectorDb):
    """Exercises the asearch fallback for adapters without async support."""

    async def async_search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        raise NotImplementedError


def test_search_without_reranker_is_unchanged():
    db = StubVectorDb()
    knowledge = Knowledge(vector_db=db)

    results = knowledge.search("q", max_results=5)

    assert db.requested_limit == 5
    assert len(results) == 5
    assert results[0].id == "0"


def test_scoring_reranker_does_not_widen_the_fetch():
    # A reranker that scores each document on its own gains nothing from a wider pool,
    # so the fetch, and its cost, stay exactly what the caller asked for.
    db = StubVectorDb(reranker=ReverseReranker())
    knowledge = Knowledge(vector_db=db)

    results = knowledge.search("q", max_results=5)

    assert db.requested_limit == 5
    assert len(results) == 5
    assert results[0].id == "4"


def test_subset_reranker_widens_the_fetch_and_trims():
    db = StubVectorDb(reranker=PoolReranker())
    knowledge = Knowledge(vector_db=db)

    results = knowledge.search("q", max_results=5)

    assert db.requested_limit == 25
    assert len(results) == 5
    # Reversing 25 candidates surfaces the tail, which plain search would never return.
    assert results[0].id == "24"


def test_widened_fetch_is_capped():
    db = StubVectorDb(reranker=PoolReranker())
    knowledge = Knowledge(vector_db=db)

    knowledge.search("q", max_results=30)

    assert db.requested_limit == 100


def test_search_limit_never_drops_below_requested_results():
    # The ceiling caps the widening, not the caller's own request.
    knowledge = Knowledge(vector_db=StubVectorDb(reranker=PoolReranker()))

    assert knowledge._search_limit(10) == 50
    assert knowledge._search_limit(30) == 100
    assert knowledge._search_limit(150) == 150


def test_large_max_results_returns_everything_requested():
    db = StubVectorDb(available=200, reranker=PoolReranker())
    knowledge = Knowledge(vector_db=db)

    results = knowledge.search("q", max_results=150)

    assert db.requested_limit == 150
    assert len(results) == 150


def test_fewer_candidates_than_requested_is_not_padded():
    db = StubVectorDb(available=3, reranker=PoolReranker())
    knowledge = Knowledge(vector_db=db)

    results = knowledge.search("q", max_results=5)

    assert len(results) == 3


def test_vector_db_without_reranker_attribute_is_left_alone():
    class BareVectorDb(StubVectorDb):
        def __init__(self):
            super().__init__()
            del self.reranker

    knowledge = Knowledge(vector_db=BareVectorDb())

    assert knowledge._search_limit(5) == 5


@pytest.mark.asyncio
async def test_asearch_widens_and_trims():
    db = StubVectorDb(reranker=PoolReranker())
    knowledge = Knowledge(vector_db=db)

    results = await knowledge.asearch("q", max_results=5)

    assert db.requested_limit == 25
    assert len(results) == 5
    assert results[0].id == "24"


@pytest.mark.asyncio
async def test_asearch_widens_on_sync_fallback():
    db = NoAsyncVectorDb(reranker=PoolReranker())
    knowledge = Knowledge(vector_db=db)

    results = await knowledge.asearch("q", max_results=5)

    assert db.requested_limit == 25
    assert len(results) == 5
    assert results[0].id == "24"


def test_page_store_fetch_is_not_widened():
    # Page-backed knowledge has no vector db reranker, so its limit passes through.
    from agno.knowledge.page import SearchResult

    class StubPageStore:
        pass

    recorded: Dict[str, int] = {}

    knowledge = Knowledge.__new__(Knowledge)
    knowledge.page_store = StubPageStore()
    knowledge.vector_db = None
    knowledge.max_results = 10

    def fake_search_pages(query, *, limit=10, **kwargs):
        recorded["limit"] = limit
        return SearchResult(results=[], partial=False)

    knowledge.search_pages = fake_search_pages  # type: ignore[method-assign]
    knowledge._page_documents = staticmethod(  # type: ignore[method-assign]
        lambda result: [Document(id=str(i), content=f"doc {i}") for i in range(5)]
    )

    results = knowledge.search("q", max_results=5)

    assert recorded["limit"] == 5
    assert len(results) == 5


@pytest.mark.asyncio
async def test_base_arerank_runs_off_the_event_loop():
    main_thread = threading.get_ident()
    seen: List[int] = []

    class ThreadRecordingReranker(Reranker):
        def rerank(self, query: str, documents: List[Document]) -> List[Document]:
            seen.append(threading.get_ident())
            return documents

    await ThreadRecordingReranker().arerank("q", [Document(id="0", content="doc 0")])

    assert seen and seen[0] != main_thread
    assert asyncio.get_running_loop().is_running()
