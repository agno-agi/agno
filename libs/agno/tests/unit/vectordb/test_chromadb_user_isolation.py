"""ChromaDb per-user isolation: one collection per owner, ``{base}__{user_id}``, base for the shared bucket."""

import os
import shutil
from typing import List

import pytest

from agno.knowledge.document import Document
from agno.vectordb.chroma import ChromaDb

from .conftest import DeterministicEmbedder

TEST_COLLECTION = "isolation_test"
TEST_PATH = "tmp/test_chromadb_isolation"


@pytest.fixture
def chroma_db():
    """Fixture to create and clean up a ChromaDb instance, including its per-user collections"""
    os.makedirs(TEST_PATH, exist_ok=True)
    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)
        os.makedirs(TEST_PATH)

    db = ChromaDb(
        collection=TEST_COLLECTION,
        path=TEST_PATH,
        persistent_client=False,
        embedder=DeterministicEmbedder(),
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


def _coll(db, user_id: str) -> str:
    """The physical collection an owner resolves to, asked of the adapter rather than spelled out.

    The mapping is deliberately not a literal: names are hashed, so hardcoding one here would
    just restate the implementation instead of checking it.
    """
    return db._collection_name_for(user_id)


class TestCollectionNaming:
    """Test how a user_id maps to a collection name."""

    def test_none_resolves_to_base_collection_name(self, chroma_db):
        assert chroma_db._collection_name_for(None) == TEST_COLLECTION

    def test_empty_string_is_a_real_tenant(self, chroma_db):
        # Only None is the shared bucket; "" is an owner and gets its own collection.
        assert chroma_db._collection_name_for("") != TEST_COLLECTION

    @pytest.mark.parametrize("user_id", ["alice", "x" * 80, "alice@corp.com", "", "../escape"])
    def test_every_user_id_is_hashed_into_the_suffix(self, chroma_db, user_id):
        """The suffix is always a hash, never the raw id — see the aliasing test below."""
        name = chroma_db._collection_name_for(user_id)
        assert name.startswith(f"{TEST_COLLECTION}__")
        suffix = name[len(TEST_COLLECTION) + 2 :]
        assert len(suffix) == 16
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_a_hash_shaped_user_id_cannot_alias_another_owner(self, chroma_db):
        """An owner must not be able to name themselves into someone else's collection.

        A digest is itself a valid Chroma name, so hashing only the ids that need it would
        leave two ways to spell one suffix: an owner who registers as ``md5(victim)[:16]``
        would land in the victim's collection with read, write and delete on its contents.
        """
        victim = "alice@corp.com"
        victim_suffix = chroma_db._collection_name_for(victim)[len(TEST_COLLECTION) + 2 :]

        # The attacker claims the victim's digest verbatim as their own user_id
        attacker_name = chroma_db._collection_name_for(victim_suffix)

        assert attacker_name != chroma_db._collection_name_for(victim)

    @pytest.mark.parametrize("base_length", [10, 480, 494, 495, 512, 600])
    def test_a_long_base_name_still_resolves_within_chromas_limit(self, base_length):
        """Chroma rejects a name over 512 chars, and the owner suffix costs 18 of them.

        A base long enough to push past the limit used to fail every scoped operation, so
        the base is digested too rather than letting the name grow unbounded.
        """
        db = ChromaDb(collection="b" * base_length, embedder=DeterministicEmbedder())

        name = db._collection_name_for("alice")

        assert 3 <= len(name) <= 512
        # The unscoped name is the caller's own and stays untouched
        assert db._collection_name_for(None) == "b" * base_length

    def test_two_long_base_names_do_not_collide(self):
        """Truncating alone would fold every base sharing a 494-char prefix into one collection."""
        shared_prefix = "b" * 600
        first = ChromaDb(collection=shared_prefix + "one", embedder=DeterministicEmbedder())
        second = ChromaDb(collection=shared_prefix + "two", embedder=DeterministicEmbedder())

        assert first._collection_name_for("alice") != second._collection_name_for("alice")


class TestWriteStampsOwner:
    """Test that an insert lands in the caller's collection, or the base one when unowned."""

    def test_alice_insert_creates_alice_collection(self, chroma_db):
        chroma_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")

        alice_coll = chroma_db.client.get_collection(name=_coll(chroma_db, "alice"))
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

        alice_coll = chroma_db.client.get_collection(name=_coll(chroma_db, "alice"))
        bob_coll = chroma_db.client.get_collection(name=_coll(chroma_db, "bob"))

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

        alice_coll = content_id_corpus.client.get_collection(name=_coll(content_id_corpus, "alice"))
        bob_coll = content_id_corpus.client.get_collection(name=_coll(content_id_corpus, "bob"))
        assert len(alice_coll.get()["ids"]) == 1
        assert len(bob_coll.get()["ids"]) == 0

    def test_alice_can_delete_her_own(self, content_id_corpus):
        content_id_corpus.delete_by_content_id("doc-1", user_id="alice")

        alice_coll = content_id_corpus.client.get_collection(name=_coll(content_id_corpus, "alice"))
        bob_coll = content_id_corpus.client.get_collection(name=_coll(content_id_corpus, "bob"))
        assert len(alice_coll.get()["ids"]) == 0
        assert len(bob_coll.get()["ids"]) == 1

    def test_unscoped_delete_wipes_every_owner(self, content_id_corpus):
        """``user_id=None`` is the unscoped delete, so it clears every owner's copy, not just the base one."""
        content_id_corpus.delete_by_content_id("doc-1", user_id=None)

        alice_coll = content_id_corpus.client.get_collection(name=_coll(content_id_corpus, "alice"))
        bob_coll = content_id_corpus.client.get_collection(name=_coll(content_id_corpus, "bob"))
        assert len(alice_coll.get()["ids"]) == 0
        assert len(bob_coll.get()["ids"]) == 0

    def test_scoped_delete_no_op_when_user_collection_does_not_exist(self, content_id_corpus):
        result = content_id_corpus.delete_by_content_id("doc-1", user_id="carol")
        assert result is False

        # Existing data untouched.
        alice_coll = content_id_corpus.client.get_collection(name=_coll(content_id_corpus, "alice"))
        bob_coll = content_id_corpus.client.get_collection(name=_coll(content_id_corpus, "bob"))
        assert len(alice_coll.get()["ids"]) == 1
        assert len(bob_coll.get()["ids"]) == 1


class TestDropCleansUpPerUserCollections:
    """Test that ``drop()`` removes the per-user collections, not just the base one."""

    def test_drop_removes_per_user_collections(self, chroma_db):
        chroma_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        chroma_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")

        # Both per-user collections exist before the drop
        existing = [c.name if hasattr(c, "name") else c for c in chroma_db.client.list_collections()]
        assert _coll(chroma_db, "alice") in existing
        assert _coll(chroma_db, "bob") in existing

        chroma_db.drop()

        after = [c.name if hasattr(c, "name") else c for c in chroma_db.client.list_collections()]
        assert _coll(chroma_db, "alice") not in after
        assert _coll(chroma_db, "bob") not in after
        assert TEST_COLLECTION not in after


class TestAsyncIsolation:
    """The async path must scope exactly as the sync one does.

    Chroma isolates by physical collection, so the async write has to resolve the same
    per-owner collection the sync write does — a divergence here would file a caller's
    chunks somewhere their own reads never look.
    """

    @pytest.fixture
    def async_corpus(self, chroma_db):
        chroma_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        chroma_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        chroma_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return chroma_db

    @pytest.mark.asyncio
    async def test_async_search_returns_own_and_shared_never_another_owner(self, async_corpus):
        names = {d.name for d in await async_corpus.async_search(query="salary", limit=10, user_id="alice")}

        assert "alice-salary" in names
        assert "bob-salary" not in names

    @pytest.mark.asyncio
    async def test_async_search_sees_the_shared_bucket(self, async_corpus):
        names = {d.name for d in await async_corpus.async_search(query="anything", limit=10, user_id="alice")}

        assert "company-holidays" in names

    @pytest.mark.asyncio
    async def test_async_unscoped_search_reads_the_base_collection(self, async_corpus):
        names = {d.name for d in await async_corpus.async_search(query="anything", limit=10, user_id=None)}

        assert "company-holidays" in names

    @pytest.mark.asyncio
    async def test_async_insert_lands_in_the_owners_collection(self, chroma_db):
        await chroma_db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")

        alice_coll = chroma_db.client.get_collection(name=_coll(chroma_db, "alice"))
        assert len(alice_coll.get()["ids"]) == 1

    @pytest.mark.asyncio
    async def test_async_insert_with_no_owner_lands_in_the_base_collection(self, chroma_db):
        await chroma_db.async_insert(content_hash="hs", documents=_shared_docs(), user_id=None)

        base = chroma_db.client.get_collection(name=TEST_COLLECTION)
        assert len(base.get()["ids"]) == 1

    @pytest.mark.asyncio
    async def test_async_insert_keeps_two_owners_apart(self, chroma_db):
        await chroma_db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        await chroma_db.async_insert(content_hash="hb", documents=_bob_docs(), user_id="bob")

        alice_coll = chroma_db.client.get_collection(name=_coll(chroma_db, "alice"))
        bob_coll = chroma_db.client.get_collection(name=_coll(chroma_db, "bob"))
        assert "Alice" in alice_coll.get()["documents"][0]
        assert "Bob" in bob_coll.get()["documents"][0]

    @pytest.mark.asyncio
    async def test_async_upsert_does_not_disturb_another_owner(self, chroma_db):
        await chroma_db.async_upsert(content_hash="h1", documents=_alice_docs(), user_id="alice")
        await chroma_db.async_upsert(content_hash="h1", documents=_bob_docs(), user_id="bob")
        await chroma_db.async_upsert(content_hash="h1", documents=_alice_docs(), user_id="alice")

        bob_coll = chroma_db.client.get_collection(name=_coll(chroma_db, "bob"))
        assert len(bob_coll.get()["ids"]) == 1
