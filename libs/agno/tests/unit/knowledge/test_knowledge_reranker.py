"""Knowledge-level reranking: over-fetch, trimming and failure handling."""

from typing import Dict, List, Optional

import pytest
from pydantic import Field

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
    """Reverses order so the effect of reranking is observable.

    Widens like a selecting reranker, so the pool behaviour is exercised.
    """

    candidate_multiplier: int = Field(default=5, ge=1)

    def rerank(self, query: str, documents: List[Document], limit: Optional[int] = None) -> List[Document]:
        return list(reversed(documents))


class FailingReranker(Reranker):
    def rerank(self, query: str, documents: List[Document], limit: Optional[int] = None) -> List[Document]:
        raise RuntimeError("reranker unavailable")


def test_search_without_reranker_is_unchanged():
    db = StubVectorDb()
    knowledge = Knowledge(vector_db=db)

    results = knowledge.search("q", max_results=5)

    assert db.requested_limit == 5
    assert len(results) == 5


def test_search_over_fetches_when_reranker_is_set():
    db = StubVectorDb()
    knowledge = Knowledge(vector_db=db, reranker=ReverseReranker())

    results = knowledge.search("q", max_results=5)

    assert db.requested_limit == 25
    assert len(results) == 5
    # Reversing 25 candidates surfaces the tail, which plain search would never return.
    assert results[0].id == "24"


def test_over_fetch_is_capped():
    db = StubVectorDb()
    knowledge = Knowledge(vector_db=db, reranker=ReverseReranker(max_candidates=30))

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


@pytest.mark.parametrize("kwargs", [{"candidate_multiplier": 0}, {"candidate_multiplier": -1}, {"max_candidates": 0}])
def test_invalid_pool_configuration_is_rejected(kwargs):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReverseReranker(**kwargs)


class ValueErrorReranker(Reranker):
    def rerank(self, query: str, documents: List[Document], limit: Optional[int] = None) -> List[Document]:
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
    knowledge = Knowledge(vector_db=StubVectorDb(), reranker=ReverseReranker(max_candidates=100))

    assert knowledge._search_limit(150) == 150


def test_over_fetch_is_capped_between_requested_and_ceiling():
    knowledge = Knowledge(vector_db=StubVectorDb(), reranker=ReverseReranker(max_candidates=100))

    assert knowledge._search_limit(10) == 50
    assert knowledge._search_limit(30) == 100


def test_large_max_results_returns_everything_requested():
    db = StubVectorDb(available=200)
    knowledge = Knowledge(vector_db=db, reranker=ReverseReranker(max_candidates=100))

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
        def rerank(self, query: str, documents: List[Document], limit: Optional[int] = None) -> List[Document]:
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

    def fake_search_pages(query, *, limit=10, **kwargs):
        recorded["limit"] = limit
        return SearchResult(results=[], partial=False)

    knowledge.search_pages = fake_search_pages  # type: ignore[method-assign]
    knowledge._page_documents = staticmethod(  # type: ignore[method-assign]
        lambda result: [Document(id=str(i), content=f"doc {i}") for i in range(25)]
    )

    results = knowledge.search("q", max_results=5)

    # Clamped to the page search ceiling rather than the full 5x widening.
    assert recorded["limit"] == 20
    assert len(results) == 5
    assert results[0].id == "24"


@pytest.mark.parametrize("max_results", [5, 10, 20])
def test_page_search_limit_stays_within_the_coordinator_ceiling(max_results):
    # PageCoordinator.search raises invalid_search_query outside 1..20, so the widened
    # page fetch has to clamp rather than pass a multiplied limit straight through.
    knowledge = Knowledge(vector_db=StubVectorDb(), reranker=ReverseReranker())

    assert 1 <= knowledge._page_search_limit(max_results) <= 20


def test_page_search_limit_still_widens_when_it_fits():
    knowledge = Knowledge(vector_db=StubVectorDb(), reranker=ReverseReranker())

    assert knowledge._page_search_limit(2) == 10


def test_reranker_with_the_older_signature_still_works():
    # Rerankers written before `limit` was added, including ones outside this repo,
    # must keep working rather than raising an unexpected-keyword TypeError.
    class LegacyReranker(Reranker):
        candidate_multiplier: int = Field(default=5, ge=1)

        def rerank(self, query: str, documents: List[Document]) -> List[Document]:
            return list(reversed(documents))

    knowledge = Knowledge(vector_db=StubVectorDb(), reranker=LegacyReranker())

    results = knowledge.search("q", max_results=5)

    assert len(results) == 5
    assert results[0].id == "24"


def test_limit_is_passed_to_rerankers_that_accept_it():
    seen = {}

    class LimitAwareReranker(Reranker):
        def rerank(self, query: str, documents: List[Document], limit: Optional[int] = None) -> List[Document]:
            seen["limit"] = limit
            return documents

    knowledge = Knowledge(vector_db=StubVectorDb(), reranker=LimitAwareReranker())
    knowledge.search("q", max_results=5)

    assert seen["limit"] == 5


def test_a_scoring_reranker_does_not_widen_the_fetch():
    # The base default is 1: only rerankers that select a subset pay for a wider pool.
    class ScoringReranker(Reranker):
        def rerank(self, query: str, documents: List[Document], limit: Optional[int] = None) -> List[Document]:
            return documents

    db = StubVectorDb()
    knowledge = Knowledge(vector_db=db, reranker=ScoringReranker())

    knowledge.search("q", max_results=5)

    assert db.requested_limit == 5


def test_pool_size_is_configured_on_the_reranker():
    db = StubVectorDb()
    knowledge = Knowledge(vector_db=db, reranker=ReverseReranker(candidate_multiplier=3))

    knowledge.search("q", max_results=5)

    assert db.requested_limit == 15


class RerankerAwareVectorDb(StubVectorDb):
    """Runs its own reranker the way the adapters do, and records that it ran."""

    def __init__(self, available: int = 100):
        super().__init__(available=available)
        self.reranker: Optional[Reranker] = None
        self.reranker_ran = False

    def search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        documents = super().search(query=query, limit=limit, filters=filters)
        if self.reranker is not None:
            self.reranker_ran = True
            documents = self.reranker.rerank(query=query, documents=documents)
        return documents


def test_knowledge_reranker_wins_over_the_vector_db_one():
    db = RerankerAwareVectorDb()
    db.reranker = ReverseReranker()
    knowledge = Knowledge(vector_db=db, reranker=ReverseReranker())

    results = knowledge.search("q", max_results=5)

    assert db.reranker_ran is False
    # Reversed once, by Knowledge, rather than twice.
    assert results[0].id == "24"


def test_the_vector_db_reranker_is_restored_after_the_search():
    db = RerankerAwareVectorDb()
    original = ReverseReranker()
    db.reranker = original
    knowledge = Knowledge(vector_db=db, reranker=ReverseReranker())

    knowledge.search("q", max_results=5)

    assert db.reranker is original


def test_the_vector_db_reranker_still_runs_when_knowledge_has_none():
    db = RerankerAwareVectorDb()
    db.reranker = ReverseReranker()
    knowledge = Knowledge(vector_db=db)

    knowledge.search("q", max_results=5)

    assert db.reranker_ran is True


@pytest.mark.asyncio
async def test_knowledge_reranker_wins_in_async_search():
    db = RerankerAwareVectorDb()
    db.reranker = ReverseReranker()
    knowledge = Knowledge(vector_db=db, reranker=ReverseReranker())

    await knowledge.asearch("q", max_results=5)

    assert db.reranker_ran is False
    assert db.reranker is not None


def _captured_warnings(monkeypatch) -> List[str]:
    """Agno's logger sets propagate=False, so caplog never sees these."""
    import agno.knowledge.knowledge as knowledge_module

    messages: List[str] = []
    monkeypatch.setattr(knowledge_module, "log_warning", lambda message, *a, **k: messages.append(str(message)))
    return messages


def test_configuring_both_rerankers_warns(monkeypatch):
    messages = _captured_warnings(monkeypatch)
    db = RerankerAwareVectorDb()
    db.reranker = ReverseReranker()

    Knowledge(vector_db=db, reranker=ReverseReranker())

    assert any("set on both Knowledge and the vector db" in message for message in messages)


def test_configuring_one_reranker_does_not_warn(monkeypatch):
    messages = _captured_warnings(monkeypatch)
    db = RerankerAwareVectorDb()

    Knowledge(vector_db=db, reranker=ReverseReranker())

    assert not any("set on both Knowledge and the vector db" in message for message in messages)


@pytest.mark.asyncio
async def test_a_shipped_reranker_with_the_older_signature_survives_arerank():
    # CohereReranker does not override arerank, so the base one must not forward a
    # limit its two-argument rerank cannot accept.
    cohere = pytest.importorskip("agno.knowledge.reranker.cohere")

    reranker = cohere.CohereReranker(api_key="test")
    assert reranker.accepts_limit() is False

    # Reaches rerank without a TypeError; the empty list short-circuits the API call.
    assert await reranker.arerank(query="q", documents=[], limit=5) == []
