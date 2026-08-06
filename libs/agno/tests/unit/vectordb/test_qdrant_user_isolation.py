"""Qdrant per-user RAG isolation contract.

Qdrant's vendor-recommended multi-tenancy is a single collection with a
tenant-indexed payload field. We index ``user_id`` as a KEYWORD with
``is_tenant=True`` so the engine stores tenant data contiguously and can
prune by tenant before walking the HNSW graph.

* Inserts with ``user_id`` stamp the value into the payload's ``user_id``
  field (NOT inside ``meta_data``).
* Inserts with ``user_id=None`` leave it NULL — the SHARED bucket.
* Scoped searches use a Filter with ``should`` matching either the caller's
  id OR is_empty(user_id), so admin-uploaded shared content stays
  discoverable.
* Unscoped (admin) searches apply no scope and see everything.

We use Qdrant's in-memory mode (``location=":memory:"``) so this is a true
end-to-end test with no mocking of the database itself — same approach as
the LanceDB isolation tests.
"""

from typing import List

import pytest

from agno.knowledge.document import Document
from agno.vectordb.qdrant import Qdrant

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


class TestPayloadHasUserIdKey:
    """Pin the contract: ``user_id`` is a top-level payload key, not nested
    inside ``meta_data``. The payload index relies on this — moving it into
    a sub-dict would silently degrade reads from O(tenant) back to O(N)."""

    def test_user_id_key_constant_is_user_id(self):
        # Storage compatibility marker. If this changes, every previously
        # persisted row's user_id stops being readable by the filter.
        assert Qdrant.USER_ID_KEY == "user_id"

    def test_explicit_user_id_persisted_top_level(self, qdrant_db):
        qdrant_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")

        # Scroll the raw payload to verify the top-level key.
        points, _ = qdrant_db.client.scroll(collection_name=TEST_COLLECTION, limit=10, with_payload=True)
        assert len(points) == 1
        assert points[0].payload[Qdrant.USER_ID_KEY] == "alice"

    def test_none_user_id_persisted_as_null(self, qdrant_db):
        """Shared chunks store ``None`` in ``user_id``. The scope filter
        uses IsEmptyCondition, which matches both None and absent."""
        qdrant_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)

        points, _ = qdrant_db.client.scroll(collection_name=TEST_COLLECTION, limit=10, with_payload=True)
        assert len(points) == 1
        assert points[0].payload[Qdrant.USER_ID_KEY] is None

    def test_user_id_omitted_defaults_to_null(self, qdrant_db):
        """Backwards-compatible: callers that never pass ``user_id`` get
        NULL (shared) — they're effectively opting out of isolation."""
        qdrant_db.insert(content_hash="h1", documents=_shared_docs())

        points, _ = qdrant_db.client.scroll(collection_name=TEST_COLLECTION, limit=10, with_payload=True)
        assert points[0].payload[Qdrant.USER_ID_KEY] is None


class TestUserScopeFilter:
    """The scope-filter builder is small enough to unit-test directly. We
    catch the OR semantics and the shared-NULL pattern without spinning
    up the DB at all."""

    def test_none_returns_no_filter(self, qdrant_db):
        assert qdrant_db._user_scope_filter(None) is None

    def test_simple_alice_filter_has_should_with_two_conditions(self, qdrant_db):
        # OR ("should") between: user_id == alice  OR  is_empty(user_id).
        f = qdrant_db._user_scope_filter("alice")
        assert f is not None
        # Pydantic model — exercise via repr/dump to keep the test stable
        # across qdrant-client versions.
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


class TestSearchIsolationContract:
    """The load-bearing test: alice's search returns her chunks plus
    shared chunks, but never bob's. This is what makes K2 actually work."""

    @pytest.fixture
    def populated_db(self, qdrant_db):
        """Three rows: one alice, one bob, one shared (NULL)."""
        qdrant_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        qdrant_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        qdrant_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return qdrant_db

    def test_alice_sees_her_own_chunk(self, populated_db):
        results = populated_db.search(query="salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "alice-salary" in names

    def test_alice_sees_shared_chunk(self, populated_db):
        results = populated_db.search(query="anything", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "company-holidays" in names

    def test_alice_never_sees_bobs_chunk(self, populated_db):
        """The isolation contract. If this fails the whole feature is
        broken — alice would be retrieving bob's confidential chunks."""
        results = populated_db.search(query="salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "bob-salary" not in names
        # Belt and braces: also check content.
        for d in results:
            assert "Bob's salary" not in d.content

    def test_bob_never_sees_alices_chunk(self, populated_db):
        results = populated_db.search(query="salary", limit=10, user_id="bob")
        names = {d.name for d in results}
        assert "alice-salary" not in names

    def test_admin_sees_everything(self, populated_db):
        """``user_id=None`` at search time means no scope — admin view."""
        results = populated_db.search(query="anything", limit=10, user_id=None)
        names = {d.name for d in results}
        assert "alice-salary" in names
        assert "bob-salary" in names
        assert "company-holidays" in names


class TestDeleteByContentIdIsolation:
    """``delete_by_content_id(content_id, user_id=...)`` must scope the
    delete to the caller's chunks — otherwise Bob could guess Alice's
    content_id and wipe her chunks.

    Qdrant scopes via a ``must`` filter combining ``content_id`` AND
    ``user_id`` on the server side.
    """

    @pytest.fixture
    def populated_db(self, qdrant_db):
        """Two users own chunks under the SAME content_id 'doc-1'. The
        adversarial scenario — Bob guesses the id and tries to delete it.
        Without ``user_id`` scoping he'd wipe Alice's row too."""
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

    def test_scoped_delete_only_removes_callers_chunks(self, populated_db):
        """Bob asks to delete 'doc-1' under his own scope — Alice's chunk
        must remain."""
        populated_db.delete_by_content_id("doc-1", user_id="bob")

        assert self._owners(populated_db) == ["alice"], "Isolation broken: bob's scoped delete touched alice's chunks"

    def test_alice_can_delete_her_own(self, populated_db):
        populated_db.delete_by_content_id("doc-1", user_id="alice")
        assert self._owners(populated_db) == ["bob"]

    def test_unscoped_delete_wipes_everyone(self, populated_db):
        """Legacy behaviour: ``user_id=None`` deletes across all owners.
        Pin it so we notice if the default semantics change."""
        populated_db.delete_by_content_id("doc-1", user_id=None)

        assert populated_db.get_count() == 0

    def test_scoped_delete_misses_when_user_does_not_own_anything(self, populated_db):
        """Carol has no chunks. Her scoped delete of doc-1 is a no-op."""
        populated_db.delete_by_content_id("doc-1", user_id="carol")
        assert populated_db.get_count() == 2
