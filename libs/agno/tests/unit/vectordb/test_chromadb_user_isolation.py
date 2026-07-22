"""ChromaDb per-user RAG isolation contract.

Chroma's vendor-recommended multi-tenancy primitive is one collection per
tenant. These tests prove that:

* Inserts with ``user_id`` write to ``{base}__{user_id}``.
* Inserts with ``user_id=None`` write to the BASE collection (which doubles
  as the shared / org-wide bucket).
* Scoped searches read BOTH the caller's collection AND the base, merging
  results — so admin-uploaded shared content stays discoverable.
* Cross-user isolation: Alice's search never surfaces Bob's chunks.

The merge happens inside ``ChromaDb.search`` (over-fetches up to 2×limit
across the two collections, sorts by distance, takes top limit). We test
the contract, not the merge ranking algorithm specifically — the latter
would be brittle and depend on mock embedding distances.
"""

import os
import shutil
from typing import List

import pytest

from agno.knowledge.document import Document
from agno.vectordb.chroma import ChromaDb

TEST_COLLECTION = "isolation_test"
TEST_PATH = "tmp/test_chromadb_isolation"


@pytest.fixture
def chroma_db(mock_embedder):
    """A fresh ChromaDb per test, including ALL per-user collections."""
    os.makedirs(TEST_PATH, exist_ok=True)
    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)
        os.makedirs(TEST_PATH)

    db = ChromaDb(
        collection=TEST_COLLECTION,
        path=TEST_PATH,
        persistent_client=False,
        embedder=mock_embedder,
    )
    db.create()
    yield db

    try:
        db.drop()  # drops base AND any per-user collections
    except Exception:
        pass
    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)


def _alice_docs() -> List[Document]:
    return [Document(name="alice-salary", content="Alice's salary is $180k.")]


def _bob_docs() -> List[Document]:
    return [Document(name="bob-salary", content="Bob's salary is $215k.")]


def _shared_docs() -> List[Document]:
    return [Document(name="company-holidays", content="The office is closed Jan 1.")]


class TestCollectionNaming:
    """The naming convention is part of the public contract — operators
    can inspect collections by name to audit which users own what."""

    def test_none_resolves_to_base_collection_name(self, chroma_db):
        assert chroma_db._collection_name_for(None) == TEST_COLLECTION

    def test_empty_string_resolves_to_base_collection_name(self, chroma_db):
        # Empty string is treated the same as None — both mean "no scope".
        assert chroma_db._collection_name_for("") == TEST_COLLECTION

    def test_simple_user_id_uses_double_underscore_separator(self, chroma_db):
        assert chroma_db._collection_name_for("alice") == f"{TEST_COLLECTION}__alice"

    def test_long_user_id_gets_hashed(self, chroma_db):
        # Chroma collection names cap at 63 chars total. A user_id long
        # enough to blow that should fall back to a stable hash suffix.
        very_long = "x" * 80
        name = chroma_db._collection_name_for(very_long)
        # Hash suffix: 16 hex chars. ``{base}__{16-hex-chars}``.
        assert name.startswith(f"{TEST_COLLECTION}__")
        suffix = name[len(TEST_COLLECTION) + 2 :]
        assert len(suffix) == 16
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_user_id_with_invalid_chars_gets_hashed(self, chroma_db):
        # Chroma name rule: alphanumeric + ``_.-``. Email addresses use
        # ``@`` and ``.`` which would fail the regex — fall back to hash.
        name = chroma_db._collection_name_for("alice@corp.com")
        assert name.startswith(f"{TEST_COLLECTION}__")
        suffix = name[len(TEST_COLLECTION) + 2 :]
        assert len(suffix) == 16


class TestInsertRoutesToPerUserCollection:
    """Owned chunks land in the caller's per-user collection; unowned
    chunks land in the base collection (which is also the shared bucket)."""

    def test_alice_insert_creates_alice_collection(self, chroma_db):
        chroma_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")

        # The Alice-specific collection now exists.
        alice_coll = chroma_db.client.get_collection(name=f"{TEST_COLLECTION}__alice")
        rows = alice_coll.get()
        assert len(rows["ids"]) == 1

    def test_none_insert_goes_to_base_collection(self, chroma_db):
        chroma_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)

        base = chroma_db.client.get_collection(name=TEST_COLLECTION)
        rows = base.get()
        assert len(rows["ids"]) == 1

    def test_alice_and_bob_inserts_are_in_separate_collections(self, chroma_db):
        chroma_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        chroma_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")

        alice_coll = chroma_db.client.get_collection(name=f"{TEST_COLLECTION}__alice")
        bob_coll = chroma_db.client.get_collection(name=f"{TEST_COLLECTION}__bob")

        # Each collection has exactly one row — neither leaked into the other.
        assert len(alice_coll.get()["ids"]) == 1
        assert len(bob_coll.get()["ids"]) == 1
        # Cross-check the content too: Alice's row in Alice's collection, etc.
        alice_doc = alice_coll.get()["documents"][0]
        bob_doc = bob_coll.get()["documents"][0]
        assert "Alice" in alice_doc
        assert "Bob" in bob_doc


class TestSearchIsolationContract:
    """The load-bearing test: cross-user retrieval is impossible."""

    @pytest.fixture
    def populated_db(self, chroma_db):
        """Three uploads: alice's, bob's, and one shared (no user_id)."""
        chroma_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        chroma_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        chroma_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return chroma_db

    def test_alice_sees_her_own_chunk(self, populated_db):
        results = populated_db.search(query="salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "alice-salary" in names

    def test_alice_sees_shared_chunk(self, populated_db):
        results = populated_db.search(query="anything", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "company-holidays" in names

    def test_alice_never_sees_bobs_chunk(self, populated_db):
        """The canonical isolation assertion."""
        results = populated_db.search(query="salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "bob-salary" not in names
        # Belt and braces: also check by content. If isolation ever leaks
        # we want this test to scream regardless of how names are tracked.
        for d in results:
            assert "Bob's salary" not in d.content

    def test_bob_never_sees_alices_chunk(self, populated_db):
        results = populated_db.search(query="salary", limit=10, user_id="bob")
        names = {d.name for d in results}
        assert "alice-salary" not in names

    def test_admin_user_id_none_sees_only_base_collection(self, populated_db):
        """When ``user_id=None``, search reads only the base collection —
        that's the unscoped / admin view of the SHARED bucket. To see
        per-user content you'd need to know which user. This matches
        Chroma's collection model: there's no cross-collection "see all"
        from the client side without iterating.

        Note: this is materially different from pgvector / LanceDB where
        ``user_id=None`` returns ALL rows. The Chroma model deliberately
        physically separates per-user data — admin tooling that needs to
        see across users does it by passing each user_id in turn."""
        results = populated_db.search(query="anything", limit=10, user_id=None)
        names = {d.name for d in results}
        # Shared chunk visible...
        assert "company-holidays" in names
        # ...but the per-user collections are NOT queried under None.
        assert "alice-salary" not in names
        assert "bob-salary" not in names


class TestDeleteByContentIdIsolation:
    """``delete_by_content_id(content_id, user_id=...)`` must route to
    the caller's per-user collection — otherwise Bob could guess Alice's
    content_id and wipe her chunks.

    Chroma's collection-based isolation makes this physical: a scoped
    delete cannot reach another user's collection even by accident.
    """

    @pytest.fixture
    def populated_db(self, chroma_db):
        """Two users own chunks under the SAME content_id ``doc-1``. The
        chunks live in physically separate collections."""
        alice_doc = Document(name="alice-doc", content="Alice's secret.")
        alice_doc.content_id = "doc-1"
        bob_doc = Document(name="bob-doc", content="Bob's secret.")
        bob_doc.content_id = "doc-1"

        chroma_db.insert(content_hash="h-alice", documents=[alice_doc], user_id="alice")
        chroma_db.insert(content_hash="h-bob", documents=[bob_doc], user_id="bob")
        return chroma_db

    def test_scoped_delete_only_touches_callers_collection(self, populated_db):
        """Bob deletes 'doc-1' scoped to himself — alice's chunks remain
        in alice's collection."""
        populated_db.delete_by_content_id("doc-1", user_id="bob")

        alice_coll = populated_db.client.get_collection(name=f"{TEST_COLLECTION}__alice")
        bob_coll = populated_db.client.get_collection(name=f"{TEST_COLLECTION}__bob")
        assert len(alice_coll.get()["ids"]) == 1
        assert len(bob_coll.get()["ids"]) == 0

    def test_alice_can_delete_her_own(self, populated_db):
        populated_db.delete_by_content_id("doc-1", user_id="alice")

        alice_coll = populated_db.client.get_collection(name=f"{TEST_COLLECTION}__alice")
        bob_coll = populated_db.client.get_collection(name=f"{TEST_COLLECTION}__bob")
        assert len(alice_coll.get()["ids"]) == 0
        assert len(bob_coll.get()["ids"]) == 1

    def test_unscoped_delete_targets_base_collection_only(self, populated_db):
        """``user_id=None`` only operates on the base/shared collection
        — it cannot delete from a per-user collection. This matches
        Chroma's read-side semantic for ``user_id=None`` (sees only
        the base collection)."""
        # Pre-condition: per-user collections have one row each, base is
        # empty (nothing inserted with user_id=None).
        populated_db.delete_by_content_id("doc-1", user_id=None)

        # Per-user collections are untouched.
        alice_coll = populated_db.client.get_collection(name=f"{TEST_COLLECTION}__alice")
        bob_coll = populated_db.client.get_collection(name=f"{TEST_COLLECTION}__bob")
        assert len(alice_coll.get()["ids"]) == 1
        assert len(bob_coll.get()["ids"]) == 1

    def test_scoped_delete_no_op_when_user_collection_does_not_exist(self, populated_db):
        """Carol has never uploaded anything. Her scoped delete of doc-1
        is a quiet no-op (returns False), not an error."""
        result = populated_db.delete_by_content_id("doc-1", user_id="carol")
        assert result is False

        # Existing data untouched.
        alice_coll = populated_db.client.get_collection(name=f"{TEST_COLLECTION}__alice")
        bob_coll = populated_db.client.get_collection(name=f"{TEST_COLLECTION}__bob")
        assert len(alice_coll.get()["ids"]) == 1
        assert len(bob_coll.get()["ids"]) == 1


class TestDropCleansUpPerUserCollections:
    """``drop()`` must wipe per-user collections too — otherwise they'd
    leak across test runs and across customer migrations."""

    def test_drop_removes_per_user_collections(self, chroma_db):
        chroma_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        chroma_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")

        # Sanity: both per-user collections exist before drop.
        existing = [c.name if hasattr(c, "name") else c for c in chroma_db.client.list_collections()]
        assert f"{TEST_COLLECTION}__alice" in existing
        assert f"{TEST_COLLECTION}__bob" in existing

        chroma_db.drop()

        after = [c.name if hasattr(c, "name") else c for c in chroma_db.client.list_collections()]
        assert f"{TEST_COLLECTION}__alice" not in after
        assert f"{TEST_COLLECTION}__bob" not in after
        assert TEST_COLLECTION not in after
