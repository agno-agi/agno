"""Legacy (pre-v3) custom VectorDb adapters must keep working unscoped.

v3 threads ``user_id=`` into every ``vector_db`` call. A third-party adapter
written against the v2 ABC has no ``user_id`` parameters, so before the fix the
kwarg raised ``TypeError`` — swallowed by the surrounding ``except Exception``
into ``[]``/no-op: every existing custom adapter silently lost all retrieval
after upgrade, isolation on or off. The boundary now signature-sniffs
(``strict_user_id_kwarg``): unscoped calls omit the kwarg and run exactly like
v2; scoped calls against a legacy adapter fail closed with a clear error.
"""

from typing import Any, Dict, List, Optional

import pytest

from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.utils.knowledge import strict_user_id_kwarg


class LegacyVectorDb:
    """A v2-signature adapter: no user_id anywhere, no **kwargs."""

    def __init__(self):
        self.store: Dict[str, List[Document]] = {}

    # v2 lifecycle surface (no user_id anywhere)
    def exists(self) -> bool:
        return True

    def create(self) -> None:
        pass

    def drop(self) -> None:
        self.store.clear()

    def search(self, query: str, limit: int = 5, filters: Any = None) -> List[Document]:
        docs = [d for docs in self.store.values() for d in docs]
        return docs[:limit]

    async def async_search(self, query: str, limit: int = 5, filters: Any = None) -> List[Document]:
        return self.search(query, limit, filters)

    def upsert_available(self) -> bool:
        return False

    def insert(self, content_hash: str, documents: List[Document], filters: Any = None) -> None:
        self.store[content_hash] = documents

    def upsert(self, content_hash: str, documents: List[Document], filters: Any = None) -> None:
        self.store[content_hash] = documents

    def content_hash_exists(self, content_hash: str) -> bool:
        return content_hash in self.store

    def delete_by_content_id(self, content_id: str) -> None:
        self.store.pop(content_id, None)


class ModernVectorDb(LegacyVectorDb):
    """v3-signature twin: records the user_id each call received."""

    def __init__(self):
        super().__init__()
        self.seen_user_ids: List[Optional[str]] = []

    def search(self, query: str, limit: int = 5, filters: Any = None, user_id: Optional[str] = None):
        self.seen_user_ids.append(user_id)
        return super().search(query, limit, filters)

    def insert(self, content_hash: str, documents: List[Document], filters: Any = None, user_id: Optional[str] = None):
        self.seen_user_ids.append(user_id)
        super().insert(content_hash, documents, filters)

    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        self.seen_user_ids.append(user_id)
        return super().content_hash_exists(content_hash)


class KwargsVectorDb(LegacyVectorDb):
    """A v2 adapter written with **kwargs. NOT v3-aware: it swallows user_id.

    Must be treated as legacy (fail-closed on scoped calls), not fooled into
    running unscoped — otherwise a scoped search returns every owner's chunks
    and a scoped write lands in the NULL/shared bucket.
    """

    def search(self, query: str, limit: int = 5, filters: Any = None, **kwargs) -> List[Document]:
        return super().search(query, limit, filters)

    def insert(self, content_hash: str, documents: List[Document], filters: Any = None, **kwargs) -> None:
        super().insert(content_hash, documents, filters)

    def content_hash_exists(self, content_hash: str, **kwargs) -> bool:
        return super().content_hash_exists(content_hash)


@pytest.fixture
def legacy_knowledge():
    db = LegacyVectorDb()
    db.insert("h1", [Document(id="d1", name="doc", content="the quarterly report", content_id="c1")])
    return Knowledge(vector_db=db), db


class TestUnscopedLegacyRunsLikeV2:
    def test_search_returns_results_instead_of_silent_empty(self, legacy_knowledge):
        knowledge, _ = legacy_knowledge
        results = knowledge.search("report")
        assert [d.content for d in results] == ["the quarterly report"], (
            "unscoped search on a legacy adapter must work like v2, not swallow a TypeError into []"
        )

    @pytest.mark.asyncio
    async def test_asearch_falls_back_and_returns_results(self, legacy_knowledge):
        knowledge, _ = legacy_knowledge
        results = await knowledge.asearch("report")
        assert [d.content for d in results] == ["the quarterly report"]

    def test_unscoped_insert_path_works(self, legacy_knowledge):
        knowledge, db = legacy_knowledge
        from agno.knowledge.content import Content

        content = Content(name="n", content_hash="h2", user_id=None)
        knowledge._handle_vector_db_insert(
            content, [Document(id="d2", name="n", content="fresh", content_id="c2")], upsert=False
        )
        assert "h2" in db.store
        assert content.status is not None and content.status.value.lower() != "failed"

    def test_unscoped_delete_by_content_id_works(self, legacy_knowledge):
        knowledge, db = legacy_knowledge
        knowledge.vector_db.delete_by_content_id("h1", **strict_user_id_kwarg(db.delete_by_content_id, None))
        assert "h1" not in db.store


class TestScopedLegacyFailsClosed:
    def test_scoped_search_raises_instead_of_running_unscoped(self, legacy_knowledge):
        knowledge, _ = legacy_knowledge
        with pytest.raises(ValueError, match="does not declare a user_id parameter"):
            knowledge.search("report", user_id="alice")

    @pytest.mark.asyncio
    async def test_scoped_asearch_raises(self, legacy_knowledge):
        knowledge, _ = legacy_knowledge
        with pytest.raises(ValueError, match="does not declare a user_id parameter"):
            await knowledge.asearch("report", user_id="alice")

    def test_scoped_insert_marks_content_failed_not_silent(self, legacy_knowledge):
        knowledge, db = legacy_knowledge
        from agno.knowledge.content import Content

        content = Content(name="n", content_hash="h3", user_id="alice")
        knowledge._handle_vector_db_insert(
            content, [Document(id="d3", name="n", content="private", content_id="c3")], upsert=False
        )
        assert "h3" not in db.store, "a scoped write must never land unscoped in a legacy store"
        assert content.status is not None and content.status.value.lower() == "failed"


class TestKwargsAdapterTreatedAsLegacy:
    """A **kwargs adapter is NOT v3-aware and must fail closed on scoped calls,
    never be handed user_id and run unscoped."""

    def _knowledge(self):
        db = KwargsVectorDb()
        db.insert("h1", [Document(id="d1", name="doc", content="secret report", content_id="c1")])
        return Knowledge(vector_db=db), db

    def test_scoped_search_raises_not_unscoped(self):
        knowledge, _ = self._knowledge()
        with pytest.raises(ValueError, match="does not declare a user_id parameter"):
            knowledge.search("report", user_id="alice")

    def test_unscoped_search_still_works(self):
        knowledge, _ = self._knowledge()
        assert [d.content for d in knowledge.search("report")] == ["secret report"]

    def test_scoped_write_fails_closed_not_null_bucket(self):
        knowledge, db = self._knowledge()
        from agno.knowledge.content import Content

        content = Content(name="n", content_hash="h2", user_id="alice")
        knowledge._handle_vector_db_insert(
            content, [Document(id="d2", name="n", content="private", content_id="c2")], upsert=False
        )
        assert "h2" not in db.store, "a **kwargs adapter must not swallow user_id and store the row shared"
        assert content.status is not None and content.status.value.lower() == "failed"


class TestMultiSourceScopedIngestFailsNotCompleted:
    """Regression: the multi-source ingest loop resolved the strict kwarg INSIDE
    the per-source try, so a scoped ValueError was swallowed and the content was
    then marked COMPLETED with nothing indexed. It must end FAILED."""

    def _multi_source_content(self):
        from agno.knowledge.content import Content

        content = Content(name="site", content_hash="site-hash", user_id="alice")
        content.url = "https://example.com"
        return content

    def _two_source_docs(self):
        return [
            Document(
                id="p1", name="p1", content="page one", content_id="s1", meta_data={"url": "https://example.com/a"}
            ),
            Document(
                id="p2", name="p2", content="page two", content_id="s2", meta_data={"url": "https://example.com/b"}
            ),
        ]

    def test_sync_multi_source_scoped_ends_failed(self, monkeypatch):
        db = LegacyVectorDb()
        knowledge = Knowledge(vector_db=db)
        content = self._multi_source_content()
        docs = self._two_source_docs()

        monkeypatch.setattr(knowledge, "_insert_contents_db", lambda c: None)
        monkeypatch.setattr(knowledge, "_should_skip", lambda *a, **k: False)
        monkeypatch.setattr(knowledge, "_read", lambda *a, **k: docs)
        monkeypatch.setattr(knowledge, "_prepare_documents_for_insert", lambda *a, **k: None)
        monkeypatch.setattr(knowledge, "_build_document_content_hash", lambda d, c: f"h-{d.content_id}")
        monkeypatch.setattr(knowledge, "_update_content", lambda *a, **k: None)

        from agno.knowledge.content import ContentStatus

        # _load_content wraps _load_from_url and marks FAILED on the propagated ValueError.
        with pytest.raises(ValueError, match="does not declare a user_id parameter"):
            knowledge._load_content(content, upsert=False, skip_if_exists=False)

        assert content.status == ContentStatus.FAILED, "a swallowed scoped error must NOT report COMPLETED"
        assert db.store == {}, "nothing may be indexed when the scope cannot be honoured"


class TestModernAdapterUnchanged:
    def test_scoped_search_passes_user_id_through(self):
        db = ModernVectorDb()
        db.insert("h1", [Document(id="d1", name="doc", content="x", content_id="c1")])
        knowledge = Knowledge(vector_db=db)
        knowledge.search("x", user_id="alice")
        assert "alice" in db.seen_user_ids

    def test_unscoped_search_passes_none_through(self):
        db = ModernVectorDb()
        knowledge = Knowledge(vector_db=db)
        knowledge.search("x")
        assert db.seen_user_ids and db.seen_user_ids[-1] is None


class TestStrictKwargHelper:
    def test_kwargs_only_does_NOT_count_as_accepting(self):
        # Every VectorDb method declares user_id explicitly, so a legacy adapter
        # written with **kwargs is NOT v3-aware — it would swallow user_id and run
        # unscoped. The strict helper must refuse a scoped call, not fail open.
        def fn(query, limit=5, **kwargs):
            return kwargs

        assert strict_user_id_kwarg(fn, None) == {}  # unscoped still fine
        with pytest.raises(ValueError, match="does not declare a user_id parameter"):
            strict_user_id_kwarg(fn, "alice")

    def test_explicit_user_id_param_accepted(self):
        def fn(query, limit=5, user_id=None):
            return user_id

        assert strict_user_id_kwarg(fn, "alice") == {"user_id": "alice"}

    def test_legacy_unscoped_omits(self):
        def fn(query, limit=5):
            return []

        assert strict_user_id_kwarg(fn, None) == {}

    def test_legacy_scoped_raises(self):
        def fn(query, limit=5):
            return []

        with pytest.raises(ValueError, match="does not declare a user_id parameter"):
            strict_user_id_kwarg(fn, "alice")

    def test_mock_is_assumed_current(self):
        # A MagicMock reports a (*args, **kwargs) signature, indistinguishable
        # from a legacy adapter — but it stands in for a real v3 adapter, so it
        # must receive user_id, not raise.
        from unittest.mock import MagicMock

        m = MagicMock()
        assert strict_user_id_kwarg(m.search, "alice") == {"user_id": "alice"}

    def test_uninspectable_assumed_current(self):
        # ``min`` has no introspectable signature - assume current, let it raise its own error
        assert strict_user_id_kwarg(min, "alice") == {"user_id": "alice"}
