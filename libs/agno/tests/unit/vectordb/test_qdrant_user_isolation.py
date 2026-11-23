"""Qdrant per-user RAG isolation, run end-to-end against Qdrant's in-memory mode."""

from typing import List

import pytest

from agno.knowledge.document import Document
from agno.vectordb.qdrant import Qdrant

from .conftest import DeterministicEmbedder

TEST_COLLECTION = "isolation_test"


@pytest.fixture
def qdrant_db(mock_embedder):
    """A fresh Qdrant per test, in-memory so no cleanup is required."""
    db = Qdrant(
        collection=TEST_COLLECTION,
        location=":memory:",
        embedder=mock_embedder,
    )
    db.create()
    yield db
    try:
        db.drop()
    except Exception:
        pass


def _alice_docs() -> List[Document]:
    return [Document(name="alice-salary", content="Alice's salary is $180k.")]


def _bob_docs() -> List[Document]:
    return [Document(name="bob-salary", content="Bob's salary is $215k.")]


def _shared_docs() -> List[Document]:
    return [Document(name="company-holidays", content="The office is closed Jan 1.")]


class TestWriteStampsOwner:
    """``user_id`` is a top-level payload key, not nested inside ``meta_data``."""

    def test_explicit_user_id_persisted_top_level(self, qdrant_db):
        qdrant_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")

        points, _ = qdrant_db.client.scroll(collection_name=TEST_COLLECTION, limit=10, with_payload=True)
        assert len(points) == 1
        assert points[0].payload[Qdrant.USER_ID_KEY] == "alice"

    def test_none_user_id_persisted_as_null(self, qdrant_db):
        qdrant_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)

        points, _ = qdrant_db.client.scroll(collection_name=TEST_COLLECTION, limit=10, with_payload=True)
        assert len(points) == 1
        assert points[0].payload[Qdrant.USER_ID_KEY] is None

    def test_user_id_omitted_defaults_to_null(self, qdrant_db):
        """Callers that never pass ``user_id`` get NULL, the shared bucket."""
        qdrant_db.insert(content_hash="h1", documents=_shared_docs())

        points, _ = qdrant_db.client.scroll(collection_name=TEST_COLLECTION, limit=10, with_payload=True)
        assert points[0].payload[Qdrant.USER_ID_KEY] is None


class TestUserScopeFilter:
    def test_none_returns_no_filter(self, qdrant_db):
        assert qdrant_db._user_scope_filter(None) is None

    def test_simple_alice_filter_has_should_with_two_conditions(self, qdrant_db):
        # "should" is Qdrant's OR: user_id == alice OR is_empty(user_id).
        f = qdrant_db._user_scope_filter("alice")
        assert f is not None
        # Dump the pydantic model so the assertions survive qdrant-client version churn.
        dumped = f.model_dump(exclude_none=True)
        assert "should" in dumped
        assert len(dumped["should"]) == 2

    def test_merge_with_no_base_returns_scope_unchanged(self, qdrant_db):
        scope = qdrant_db._user_scope_filter("alice")
        assert qdrant_db._merge_filters(None, scope) is scope

    def test_merge_with_no_scope_returns_base_unchanged(self, qdrant_db):
        from qdrant_client.http import models

        base = models.Filter(must=[models.FieldCondition(key="meta_data.tag", match=models.MatchValue(value="x"))])
        assert qdrant_db._merge_filters(base, None) is base


class TestSearchScope:
    """Alice's search returns her chunks plus shared chunks, but never bob's."""

    @pytest.fixture
    def search_corpus(self, qdrant_db):
        """Three rows: one alice, one bob, one shared (NULL)."""
        qdrant_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        qdrant_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        qdrant_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return qdrant_db

    def test_alice_sees_her_own_chunk(self, search_corpus):
        results = search_corpus.search(query="salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "alice-salary" in names

    def test_alice_sees_shared_chunk(self, search_corpus):
        results = search_corpus.search(query="anything", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "company-holidays" in names

    def test_alice_never_sees_bobs_chunk(self, search_corpus):
        results = search_corpus.search(query="salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "bob-salary" not in names
        for d in results:
            assert "Bob's salary" not in d.content

    def test_bob_never_sees_alices_chunk(self, search_corpus):
        results = search_corpus.search(query="salary", limit=10, user_id="bob")
        names = {d.name for d in results}
        assert "alice-salary" not in names

    def test_admin_sees_everything(self, search_corpus):
        """``user_id=None`` at search time means no scope — admin view."""
        results = search_corpus.search(query="anything", limit=10, user_id=None)
        names = {d.name for d in results}
        assert "alice-salary" in names
        assert "bob-salary" in names
        assert "company-holidays" in names

    def test_empty_user_id_is_an_owner_not_an_admin(self, search_corpus):
        """Only ``None`` is unscoped: an empty string is an owner, so it sees the shared bucket alone."""
        results = search_corpus.search(query="anything", limit=10, user_id="")
        names = {d.name for d in results}
        assert names == {"company-holidays"}

    @pytest.mark.asyncio
    async def test_async_search_scopes_to_the_caller(self):
        """In memory mode the async client is a separate store, so the sync tests above cannot cover this path."""
        db = Qdrant(collection=TEST_COLLECTION, location=":memory:", embedder=DeterministicEmbedder())
        await db.async_create()
        await db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        await db.async_insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        await db.async_insert(content_hash="hs", documents=_shared_docs(), user_id=None)

        results = await db.async_search(query="salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "alice-salary" in names
        assert "company-holidays" in names
        assert "bob-salary" not in names


class TestDeleteScope:
    """``delete_by_content_id`` must scope the delete to the caller's own chunks."""

    @pytest.fixture
    def content_id_corpus(self, qdrant_db):
        """Two users own chunks under the same content_id 'doc-1'."""
        alice_doc = Document(name="alice-doc", content="Alice's secret.")
        alice_doc.content_id = "doc-1"
        bob_doc = Document(name="bob-doc", content="Bob's secret.")
        bob_doc.content_id = "doc-1"

        qdrant_db.insert(content_hash="h-alice", documents=[alice_doc], user_id="alice")
        qdrant_db.insert(content_hash="h-bob", documents=[bob_doc], user_id="bob")
        return qdrant_db

    def _owners(self, db):
        points, _ = db.client.scroll(collection_name=TEST_COLLECTION, limit=100, with_payload=True)
        return sorted(p.payload[Qdrant.USER_ID_KEY] for p in points)

    def test_scoped_delete_only_removes_callers_chunks(self, content_id_corpus):
        """Bob deletes 'doc-1' under his own scope; alice's chunk must remain."""
        content_id_corpus.delete_by_content_id("doc-1", user_id="bob")

        assert self._owners(content_id_corpus) == ["alice"], (
            "Isolation broken: bob's scoped delete touched alice's chunks"
        )

    def test_alice_can_delete_her_own(self, content_id_corpus):
        content_id_corpus.delete_by_content_id("doc-1", user_id="alice")
        assert self._owners(content_id_corpus) == ["bob"]

    def test_unscoped_delete_wipes_everyone(self, content_id_corpus):
        """Legacy behaviour: ``user_id=None`` deletes across all owners."""
        content_id_corpus.delete_by_content_id("doc-1", user_id=None)

        assert content_id_corpus.get_count() == 0

    def test_scoped_delete_misses_when_user_does_not_own_anything(self, content_id_corpus):
        content_id_corpus.delete_by_content_id("doc-1", user_id="carol")
        assert content_id_corpus.get_count() == 2


class TestUpsertDedupScope:
    """Point ids fold in each chunk's own id, so a shrinking re-upsert orphans the surplus unless the owner's
    prior chunks are cleared first - and that clear must not reach another owner's rows."""

    @staticmethod
    def _chunks(n: int) -> List[Document]:
        return [Document(name=f"c{i}", content=f"chunk number {i}") for i in range(n)]

    @staticmethod
    def _owners(db) -> List:
        points, _ = db.client.scroll(collection_name=TEST_COLLECTION, limit=100, with_payload=True)
        return sorted((p.payload.get(Qdrant.USER_ID_KEY) for p in points), key=str)

    def test_shrinking_reupsert_leaves_no_orphans(self, qdrant_db):
        qdrant_db.upsert(content_hash="h", documents=self._chunks(3), user_id="alice")
        qdrant_db.upsert(content_hash="h", documents=self._chunks(1), user_id="alice")

        assert qdrant_db.get_count() == 1, "Surplus chunks from the longer version survived the re-upsert"

    def test_reupsert_never_clears_another_owner(self, qdrant_db):
        """The dedup delete must match the writing owner alone."""
        qdrant_db.upsert(content_hash="h", documents=self._chunks(2), user_id="bob")
        qdrant_db.upsert(content_hash="h", documents=self._chunks(2), user_id="alice")
        qdrant_db.upsert(content_hash="h", documents=self._chunks(1), user_id="alice")

        assert self._owners(qdrant_db) == ["alice", "bob", "bob"]

    def test_shared_reupsert_never_clears_an_owned_bucket(self, qdrant_db):
        qdrant_db.upsert(content_hash="h", documents=self._chunks(2), user_id="alice")
        qdrant_db.upsert(content_hash="h", documents=self._chunks(1), user_id=None)

        assert self._owners(qdrant_db) == [None, "alice", "alice"]

    def test_guard_and_delete_share_one_bucket(self, qdrant_db):
        """``content_hash_exists`` and ``_delete_by_content_hash`` must resolve the same rows."""
        qdrant_db.upsert(content_hash="h", documents=self._chunks(1), user_id="alice")

        assert qdrant_db.content_hash_exists("h", user_id="alice") is True
        assert qdrant_db.content_hash_exists("h", user_id=None) is False, (
            "The shared bucket must not see a privately owned row"
        )
        qdrant_db._delete_by_content_hash("h", user_id=None)
        assert self._owners(qdrant_db) == ["alice"], "A shared dedup delete cleared an owned row"


def test_user_id_key_is_a_storage_compatibility_marker():
    """Renaming the payload key strands every row already indexed under the old name."""
    assert Qdrant.USER_ID_KEY == "user_id"
