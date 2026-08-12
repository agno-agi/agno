"""ChromaDb per-user isolation: one collection per owner, ``{base}__{user_id}``, base for the shared bucket."""

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
    """Fixture to create and clean up a ChromaDb instance, including its per-user collections"""
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
        db.drop()  # drops the base and any per-user collections
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
    """Test how a user_id maps to a collection name."""

    def test_none_resolves_to_base_collection_name(self, chroma_db):
        assert chroma_db._collection_name_for(None) == TEST_COLLECTION

    def test_empty_string_is_a_real_tenant(self, chroma_db):
        # Only None is the shared bucket; "" is an owner and gets its own collection.
        assert chroma_db._collection_name_for("") != TEST_COLLECTION

    def test_simple_user_id_uses_double_underscore_separator(self, chroma_db):
        assert chroma_db._collection_name_for("alice") == f"{TEST_COLLECTION}__alice"

    def test_long_user_id_gets_hashed(self, chroma_db):
        # Chroma caps collection names at 63 chars, so a longer user_id falls back to a hash suffix.
        very_long = "x" * 80
        name = chroma_db._collection_name_for(very_long)
        assert name.startswith(f"{TEST_COLLECTION}__")
        suffix = name[len(TEST_COLLECTION) + 2 :]
        assert len(suffix) == 16
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_user_id_with_invalid_chars_gets_hashed(self, chroma_db):
        # Chroma allows only alphanumerics and ``_.-``, so an email address falls back to a hash suffix.
        name = chroma_db._collection_name_for("alice@corp.com")
        assert name.startswith(f"{TEST_COLLECTION}__")
        suffix = name[len(TEST_COLLECTION) + 2 :]
        assert len(suffix) == 16


class TestWriteStampsOwner:
    """Test that an insert lands in the caller's collection, or the base one when unowned."""

    def test_alice_insert_creates_alice_collection(self, chroma_db):
        chroma_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")

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

        assert len(alice_coll.get()["ids"]) == 1
        assert len(bob_coll.get()["ids"]) == 1

        alice_doc = alice_coll.get()["documents"][0]
        bob_doc = bob_coll.get()["documents"][0]
        assert "Alice" in alice_doc
        assert "Bob" in bob_doc


class TestSearchScope:
    """Test that a scoped search only reads the caller's collection and the shared one."""

    @pytest.fixture
    def search_corpus(self, chroma_db):
        """Fixture to insert one chunk for alice, one for bob and one shared"""
        chroma_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        chroma_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        chroma_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return chroma_db

    def test_alice_sees_her_own_chunk(self, search_corpus):
        results = search_corpus.search(query="salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "alice-salary" in names

    def test_alice_sees_shared_chunk(self, search_corpus):
        results = search_corpus.search(query="anything", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "company-holidays" in names

    def test_alice_never_sees_bobs_chunk(self, search_corpus):
        """Test that a scoped search never returns another user's chunk."""
        results = search_corpus.search(query="salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "bob-salary" not in names
        # Check the content too, in case a leaked chunk arrives without its name.
        for d in results:
            assert "Bob's salary" not in d.content

    def test_bob_never_sees_alices_chunk(self, search_corpus):
        results = search_corpus.search(query="salary", limit=10, user_id="bob")
        names = {d.name for d in results}
        assert "alice-salary" not in names

    def test_admin_user_id_none_sees_every_collection(self, search_corpus):
        """``user_id=None`` is the unscoped read, so it covers the base collection plus one per owner."""
        results = search_corpus.search(query="anything", limit=10, user_id=None)
        names = {d.name for d in results}
        assert "company-holidays" in names
        assert "alice-salary" in names
        assert "bob-salary" in names


class TestDeleteScope:
    """Test that ``delete_by_content_id`` routes to the caller's collection."""

    @pytest.fixture
    def content_id_corpus(self, chroma_db):
        """Fixture to give two users a chunk under the same content_id ``doc-1``"""
        alice_doc = Document(name="alice-doc", content="Alice's secret.")
        alice_doc.content_id = "doc-1"
        bob_doc = Document(name="bob-doc", content="Bob's secret.")
        bob_doc.content_id = "doc-1"

        chroma_db.insert(content_hash="h-alice", documents=[alice_doc], user_id="alice")
        chroma_db.insert(content_hash="h-bob", documents=[bob_doc], user_id="bob")
        return chroma_db

    def test_scoped_delete_only_touches_callers_collection(self, content_id_corpus):
        """Test that bob deleting ``doc-1`` leaves alice's copy in place."""
        content_id_corpus.delete_by_content_id("doc-1", user_id="bob")

        alice_coll = content_id_corpus.client.get_collection(name=f"{TEST_COLLECTION}__alice")
        bob_coll = content_id_corpus.client.get_collection(name=f"{TEST_COLLECTION}__bob")
        assert len(alice_coll.get()["ids"]) == 1
        assert len(bob_coll.get()["ids"]) == 0

    def test_alice_can_delete_her_own(self, content_id_corpus):
        content_id_corpus.delete_by_content_id("doc-1", user_id="alice")

        alice_coll = content_id_corpus.client.get_collection(name=f"{TEST_COLLECTION}__alice")
        bob_coll = content_id_corpus.client.get_collection(name=f"{TEST_COLLECTION}__bob")
        assert len(alice_coll.get()["ids"]) == 0
        assert len(bob_coll.get()["ids"]) == 1

    def test_unscoped_delete_wipes_every_owner(self, content_id_corpus):
        """``user_id=None`` is the unscoped delete, so it clears every owner's copy, not just the base one."""
        content_id_corpus.delete_by_content_id("doc-1", user_id=None)

        alice_coll = content_id_corpus.client.get_collection(name=f"{TEST_COLLECTION}__alice")
        bob_coll = content_id_corpus.client.get_collection(name=f"{TEST_COLLECTION}__bob")
        assert len(alice_coll.get()["ids"]) == 0
        assert len(bob_coll.get()["ids"]) == 0

    def test_scoped_delete_no_op_when_user_collection_does_not_exist(self, content_id_corpus):
        result = content_id_corpus.delete_by_content_id("doc-1", user_id="carol")
        assert result is False

        # Existing data untouched.
        alice_coll = content_id_corpus.client.get_collection(name=f"{TEST_COLLECTION}__alice")
        bob_coll = content_id_corpus.client.get_collection(name=f"{TEST_COLLECTION}__bob")
        assert len(alice_coll.get()["ids"]) == 1
        assert len(bob_coll.get()["ids"]) == 1


class TestDropCleansUpPerUserCollections:
    """Test that ``drop()`` removes the per-user collections, not just the base one."""

    def test_drop_removes_per_user_collections(self, chroma_db):
        chroma_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        chroma_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")

        # Both per-user collections exist before the drop
        existing = [c.name if hasattr(c, "name") else c for c in chroma_db.client.list_collections()]
        assert f"{TEST_COLLECTION}__alice" in existing
        assert f"{TEST_COLLECTION}__bob" in existing

        chroma_db.drop()

        after = [c.name if hasattr(c, "name") else c for c in chroma_db.client.list_collections()]
        assert f"{TEST_COLLECTION}__alice" not in after
        assert f"{TEST_COLLECTION}__bob" not in after
        assert TEST_COLLECTION not in after
