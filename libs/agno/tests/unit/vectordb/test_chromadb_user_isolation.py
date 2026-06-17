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


def _user_coll_name(db, user_id: str) -> str:
    """The physical collection name for ``user_id`` — sha256-suffixed, so
    tests must resolve it through the db rather than string-build it."""
    return db._collection_name_for(user_id)


def _embedded(db, documents: List[Document]) -> List[Document]:
    """Pre-set embeddings on docs so the async path doesn't depend on the
    MagicMock embedder's (unmocked) async_embed — same convention the
    existing chroma async tests use."""
    for doc in documents:
        doc.embedding = db.embedder.get_embedding(doc.content)
    return documents


class TestCollectionNaming:
    """The naming convention is part of the public contract — operators
    can inspect collections by name to audit which users own what.

    The user_id -> collection-name mapping is INJECTIVE: the suffix is
    always a sha256 hex digest of the id, so distinct ids never collide and
    a crafted id can't forge another user's collection name.
    """

    # Chroma's hard limit on collection names is 63 chars total. The wrapper
    # truncates the sha256 hex to a budget that fits inside ``{base}__{suffix}``
    # while still leaving enough entropy to be collision-free at any realistic
    # tenant count.
    SHA_LEN = 16  # truncated sha256 prefix length

    def _suffix_of(self, chroma_db, user_id: str) -> str:
        name = chroma_db._collection_name_for(user_id)
        assert name.startswith(f"{TEST_COLLECTION}__")
        return name[len(TEST_COLLECTION) + 2 :]

    def test_none_resolves_to_base_collection_name(self, chroma_db):
        assert chroma_db._collection_name_for(None) == TEST_COLLECTION

    def test_simple_user_id_is_hashed_not_passed_through(self, chroma_db):
        # No passthrough path: even a clean alphanumeric id is hashed, so a
        # raw id can never collide with a hashed one.
        suffix = self._suffix_of(chroma_db, "alice")
        assert suffix != "alice"
        assert len(suffix) == self.SHA_LEN
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_suffix_is_always_sha256_hex(self, chroma_db):
        # Adversarial id zoo: emails, unicode, spaces, uppercase, 1-char,
        # 80-char. Every one yields a fixed-length lowercase-hex suffix.
        # Empty/whitespace ids are normalized to None at the Knowledge
        # boundary; backends only ever see (None | non-empty str).
        adversarial = [
            "alice@corp.com",
            "üñîçødé-名前",
            "id with spaces",
            "MixedCaseID",
            "a",
            "x" * 80,
            "../../etc/passwd",
        ]
        for uid in adversarial:
            name = chroma_db._collection_name_for(uid)
            suffix = name[len(TEST_COLLECTION) + 2 :]
            assert len(suffix) == self.SHA_LEN
            assert all(c in "0123456789abcdef" for c in suffix)
            # Result must satisfy Chroma's own name validator.
            chroma_db.client.create_collection(name=name)
            chroma_db.client.delete_collection(name=name)

    def test_mapping_is_injective_distinct_ids_distinct_collections(self, chroma_db):
        # The core invariant: two different ids must never share a collection.
        ids = ["alice", "bob", "alice@corp.com", "Alice", "alice ", " alice"]
        names = {chroma_db._collection_name_for(uid) for uid in ids}
        assert len(names) == len(ids)

    def test_deterministic_same_id_same_collection(self, chroma_db):
        # Stability across calls/processes: the suffix is a pure function.
        a = chroma_db._collection_name_for("alice")
        b = chroma_db._collection_name_for("alice")
        assert a == b

    def test_impersonation_via_crafted_id_cannot_reach_victim_collection(self, chroma_db):
        # The original bug: a user whose id equalled ``md5(victim)[:16]``
        # landed in the victim's collection because clean ids were passed
        # through verbatim while weird ids were md5-hashed. With sha256-only
        # suffixes there is no passthrough, so a crafted id resolves to its
        # OWN sha256 collection — never the victim's.
        from hashlib import md5, sha256

        victim = "victim-user"
        victim_coll = chroma_db._collection_name_for(victim)

        # Attacker crafts an id matching the OLD md5[:16] of the victim.
        crafted = md5(victim.encode()).hexdigest()[:16]
        attacker_coll = chroma_db._collection_name_for(crafted)

        assert attacker_coll != victim_coll
        # And it resolves to the attacker's own truncated-sha256 namespace.
        expected = f"{TEST_COLLECTION}__{sha256(crafted.encode()).hexdigest()[: self.SHA_LEN]}"
        assert attacker_coll == expected


class TestInsertRoutesToPerUserCollection:
    """Owned chunks land in the caller's per-user collection; unowned
    chunks land in the base collection (which is also the shared bucket)."""

    def test_alice_insert_creates_alice_collection(self, chroma_db):
        chroma_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")

        # The Alice-specific collection now exists.
        alice_coll = chroma_db.client.get_collection(name=_user_coll_name(chroma_db, "alice"))
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

        alice_coll = chroma_db.client.get_collection(name=_user_coll_name(chroma_db, "alice"))
        bob_coll = chroma_db.client.get_collection(name=_user_coll_name(chroma_db, "bob"))

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
        # Also check by content, so a leak is caught regardless of name tracking.
        for d in results:
            assert "Bob's salary" not in d.content

    def test_bob_never_sees_alices_chunk(self, populated_db):
        results = populated_db.search(query="salary", limit=10, user_id="bob")
        names = {d.name for d in results}
        assert "alice-salary" not in names

    def test_admin_user_id_none_sees_all_owners_and_shared(self, populated_db):
        """``user_id=None`` is the admin view: it fans out across the base
        (shared) collection AND every per-user collection, so the result is
        the union of every owner's chunks plus shared content.

        Searches with ``user_id=None`` see everything, matching the pgvector
        and LanceDB behaviour."""
        results = populated_db.search(query="anything", limit=10, user_id=None)
        names = {d.name for d in results}
        assert "company-holidays" in names  # shared
        assert "alice-salary" in names  # alice's per-user chunk
        assert "bob-salary" in names  # bob's per-user chunk

    def test_admin_view_empty_when_nothing_ingested(self, chroma_db):
        """Fan-out over zero per-user collections + empty base is just empty,
        not an error."""
        results = chroma_db.search(query="anything", limit=10, user_id=None)
        assert results == []


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

        alice_coll = populated_db.client.get_collection(name=_user_coll_name(populated_db, "alice"))
        bob_coll = populated_db.client.get_collection(name=_user_coll_name(populated_db, "bob"))
        assert len(alice_coll.get()["ids"]) == 1
        assert len(bob_coll.get()["ids"]) == 0

    def test_alice_can_delete_her_own(self, populated_db):
        populated_db.delete_by_content_id("doc-1", user_id="alice")

        alice_coll = populated_db.client.get_collection(name=_user_coll_name(populated_db, "alice"))
        bob_coll = populated_db.client.get_collection(name=_user_coll_name(populated_db, "bob"))
        assert len(alice_coll.get()["ids"]) == 0
        assert len(bob_coll.get()["ids"]) == 1

    def test_unscoped_delete_fans_out_across_all_owners(self, populated_db):
        """``user_id=None`` deletes across ALL owners — base + every
        per-user collection — matching the read-side admin fan-out."""
        result = populated_db.delete_by_content_id("doc-1", user_id=None)
        assert result is True

        # Both per-user collections had doc-1; both are now purged.
        alice_coll = populated_db.client.get_collection(name=_user_coll_name(populated_db, "alice"))
        bob_coll = populated_db.client.get_collection(name=_user_coll_name(populated_db, "bob"))
        assert len(alice_coll.get()["ids"]) == 0
        assert len(bob_coll.get()["ids"]) == 0

    def test_scoped_delete_does_nothing_when_user_collection_does_not_exist(self, populated_db):
        """Carol has never uploaded anything. Her scoped delete of doc-1
        does nothing (returns False) rather than erroring."""
        result = populated_db.delete_by_content_id("doc-1", user_id="carol")
        assert result is False

        # Existing data untouched.
        alice_coll = populated_db.client.get_collection(name=_user_coll_name(populated_db, "alice"))
        bob_coll = populated_db.client.get_collection(name=_user_coll_name(populated_db, "bob"))
        assert len(alice_coll.get()["ids"]) == 1
        assert len(bob_coll.get()["ids"]) == 1


class TestDropCleansUpPerUserCollections:
    """``drop()`` must wipe per-user collections too — otherwise they'd
    leak across test runs and across customer migrations."""

    def test_drop_removes_per_user_collections(self, chroma_db):
        chroma_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        chroma_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")

        alice_name = _user_coll_name(chroma_db, "alice")
        bob_name = _user_coll_name(chroma_db, "bob")

        # Sanity: both per-user collections exist before drop.
        existing = [c.name if hasattr(c, "name") else c for c in chroma_db.client.list_collections()]
        assert alice_name in existing
        assert bob_name in existing

        chroma_db.drop()

        after = [c.name if hasattr(c, "name") else c for c in chroma_db.client.list_collections()]
        assert alice_name not in after
        assert bob_name not in after
        assert TEST_COLLECTION not in after


class TestPerUserUpsertDedup:
    """Re-ingesting the same ``content_hash`` for a per-user scope must
    REPLACE the old chunks, not accumulate duplicates. The dedup path
    (``content_hash_exists`` / ``_delete_by_content_hash``) has to run
    against the per-user collection, not the base one."""

    def test_reupsert_same_content_hash_replaces_in_per_user_collection(self, chroma_db):
        v1 = [Document(name="doc", content="Version one of Alice's doc.")]
        chroma_db.upsert(content_hash="ch-1", documents=v1, user_id="alice")

        alice_coll = chroma_db.client.get_collection(name=_user_coll_name(chroma_db, "alice"))
        assert alice_coll.count() == 1

        # Re-upsert: same content_hash, changed content. Old chunk for this
        # hash must be deleted from the per-user collection, not left behind.
        v2 = [Document(name="doc", content="Version two of Alice's doc — rewritten.")]
        chroma_db.upsert(content_hash="ch-1", documents=v2, user_id="alice")

        rows = alice_coll.get()
        assert alice_coll.count() == 1  # replaced, not accumulated
        assert "Version two" in rows["documents"][0]

    def test_reupsert_does_not_touch_base_or_other_users(self, chroma_db):
        chroma_db.upsert(content_hash="ch-x", documents=_alice_docs(), user_id="alice")
        chroma_db.upsert(content_hash="ch-x", documents=_bob_docs(), user_id="bob")

        # Re-upsert alice's same content_hash with new content.
        chroma_db.upsert(
            content_hash="ch-x",
            documents=[Document(name="alice-salary", content="Alice's salary is now $200k.")],
            user_id="alice",
        )

        alice_coll = chroma_db.client.get_collection(name=_user_coll_name(chroma_db, "alice"))
        bob_coll = chroma_db.client.get_collection(name=_user_coll_name(chroma_db, "bob"))
        # Alice's collection replaced; bob's untouched despite same hash.
        assert alice_coll.count() == 1
        assert bob_coll.count() == 1
        assert "Bob" in bob_coll.get()["documents"][0]


class TestInsertAfterDrop:
    """``drop()`` must reset the cached base collection too — otherwise the
    next insert reuses a deleted Collection object and raises NotFoundError."""

    def test_insert_after_drop_recreates_base_collection(self, chroma_db):
        chroma_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)
        chroma_db.drop()

        # This used to crash with NotFoundError on the stale cached base.
        chroma_db.insert(content_hash="h2", documents=_shared_docs(), user_id=None)

        base = chroma_db.client.get_collection(name=TEST_COLLECTION)
        assert base.count() == 1

    def test_search_after_drop_then_insert_works(self, chroma_db):
        chroma_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        chroma_db.drop()
        chroma_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")

        results = chroma_db.search(query="salary", limit=10, user_id="alice")
        assert "alice-salary" in {d.name for d in results}


class TestDeleteCleansUpPerUserCollections:
    """``delete()`` (the reset/clear path) must also sweep per-user
    collections — otherwise it orphans them, leaking one user's chunks
    into a "fresh" deployment."""

    def test_delete_removes_per_user_collections(self, chroma_db):
        chroma_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        chroma_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        chroma_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)

        alice_name = _user_coll_name(chroma_db, "alice")
        bob_name = _user_coll_name(chroma_db, "bob")

        assert chroma_db.delete() is True

        after = [c.name if hasattr(c, "name") else c for c in chroma_db.client.list_collections()]
        assert alice_name not in after
        assert bob_name not in after
        assert TEST_COLLECTION not in after


class TestSearchModeIsolation:
    """Isolation is physical (per-collection), so it must hold for EVERY
    search mode the backend supports — vector, keyword, and hybrid — not just
    the default vector path."""

    @pytest.fixture(params=["keyword", "hybrid"])
    def mode_db(self, request, mock_embedder):
        from agno.vectordb.search import SearchType

        os.makedirs(TEST_PATH, exist_ok=True)
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)
            os.makedirs(TEST_PATH)

        db = ChromaDb(
            collection=TEST_COLLECTION,
            path=TEST_PATH,
            persistent_client=False,
            embedder=mock_embedder,
            search_type=SearchType.keyword if request.param == "keyword" else SearchType.hybrid,
        )
        db.create()
        db.insert(
            content_hash="ha", documents=[Document(name="alice-salary", content="alice salary secret")], user_id="alice"
        )
        db.insert(
            content_hash="hb", documents=[Document(name="bob-salary", content="bob salary secret")], user_id="bob"
        )
        db.insert(content_hash="hs", documents=[Document(name="shared", content="salary office holiday")], user_id=None)
        yield db
        try:
            db.drop()
        except Exception:
            pass
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)

    def test_alice_sees_own_and_shared(self, mode_db):
        names = {d.name for d in mode_db.search(query="salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "shared" in names

    def test_alice_never_sees_bob(self, mode_db):
        names = {d.name for d in mode_db.search(query="salary", limit=10, user_id="alice")}
        assert "bob-salary" not in names

    def test_admin_sees_all_owners(self, mode_db):
        names = {d.name for d in mode_db.search(query="salary", limit=10, user_id=None)}
        assert {"alice-salary", "bob-salary", "shared"} <= names


class TestMaintenanceFanOut:
    """``delete_by_name`` / ``delete_by_metadata`` / ``update_metadata`` carry no
    ``user_id`` (they are unscoped admin ops), so they must fan out across the
    base AND every per-user collection. A prior bug only touched the base, so a
    name/metadata living in a per-user collection survived the delete."""

    @pytest.fixture
    def fanned_db(self, chroma_db):
        # Same name + content_id across alice, bob, and the shared bucket — each
        # in a physically separate collection.
        for user_id, suffix in [("alice", "a"), ("bob", "b"), (None, "s")]:
            doc = Document(name="shared-name", content=f"version {suffix}", meta_data={"tag": "purge"})
            doc.content_id = "cid-1"
            chroma_db.insert(content_hash=f"h{suffix}", documents=[doc], user_id=user_id)
        return chroma_db

    def _counts(self, db):
        return (
            db.client.get_collection(name=_user_coll_name(db, "alice")).count(),
            db.client.get_collection(name=_user_coll_name(db, "bob")).count(),
            db.client.get_collection(name=TEST_COLLECTION).count(),
        )

    def test_delete_by_name_fans_out(self, fanned_db):
        assert fanned_db.delete_by_name("shared-name") is True
        assert self._counts(fanned_db) == (0, 0, 0)

    def test_delete_by_metadata_fans_out(self, fanned_db):
        assert fanned_db.delete_by_metadata({"tag": "purge"}) is True
        assert self._counts(fanned_db) == (0, 0, 0)

    def test_update_metadata_fans_out(self, fanned_db):
        fanned_db.update_metadata("cid-1", {"reviewed": "yes"})
        for user_id in ["alice", "bob", None]:
            coll = fanned_db.client.get_collection(
                name=_user_coll_name(fanned_db, user_id) if user_id else TEST_COLLECTION
            )
            rows = coll.get(where={"content_id": {"$eq": "cid-1"}})
            assert rows["metadatas"][0].get("reviewed") == "yes"

    def test_update_metadata_cannot_reassign_owner(self, fanned_db):
        # The owner IS the physical collection in Chroma, so a ``user_id`` key in
        # caller metadata must not move a row out of its collection.
        before = self._counts(fanned_db)
        fanned_db.update_metadata("cid-1", {"user_id": "attacker"})
        assert self._counts(fanned_db) == before


class TestAsyncVariants:
    """Every isolation guarantee must hold through the async API too —
    they delegate to the sync implementation via ``asyncio.to_thread``,
    but we exercise them so a future divergence is caught."""

    @pytest.mark.asyncio
    async def test_async_insert_and_search_isolation(self, chroma_db):
        await chroma_db.async_insert(content_hash="ha", documents=_embedded(chroma_db, _alice_docs()), user_id="alice")
        await chroma_db.async_insert(content_hash="hb", documents=_embedded(chroma_db, _bob_docs()), user_id="bob")
        await chroma_db.async_insert(content_hash="hs", documents=_embedded(chroma_db, _shared_docs()), user_id=None)

        alice = await chroma_db.async_search(query="salary", limit=10, user_id="alice")
        alice_names = {d.name for d in alice}
        assert "alice-salary" in alice_names
        assert "company-holidays" in alice_names  # shared visible
        assert "bob-salary" not in alice_names  # isolation holds

    @pytest.mark.asyncio
    async def test_async_admin_none_sees_all_owners(self, chroma_db):
        await chroma_db.async_insert(content_hash="ha", documents=_embedded(chroma_db, _alice_docs()), user_id="alice")
        await chroma_db.async_insert(content_hash="hb", documents=_embedded(chroma_db, _bob_docs()), user_id="bob")
        await chroma_db.async_insert(content_hash="hs", documents=_embedded(chroma_db, _shared_docs()), user_id=None)

        results = await chroma_db.async_search(query="anything", limit=10, user_id=None)
        names = {d.name for d in results}
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names

    @pytest.mark.asyncio
    async def test_async_upsert_dedup_in_per_user_collection(self, chroma_db):
        await chroma_db.async_upsert(
            content_hash="ch-1",
            documents=_embedded(chroma_db, [Document(name="doc", content="Async version one.")]),
            user_id="alice",
        )
        await chroma_db.async_upsert(
            content_hash="ch-1",
            documents=_embedded(chroma_db, [Document(name="doc", content="Async version two — rewritten.")]),
            user_id="alice",
        )

        alice_coll = chroma_db.client.get_collection(name=_user_coll_name(chroma_db, "alice"))
        assert alice_coll.count() == 1
        assert "version two" in alice_coll.get()["documents"][0]
