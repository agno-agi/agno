"""ChromaDb per-user RAG isolation contract.

Chroma's vendor-recommended multi-tenancy primitive is one collection per
tenant, so isolation here is collection ROUTING rather than filtering. These
tests prove that:

* Inserts with ``user_id`` write to ``{base}__{user_id}``.
* Inserts with ``user_id=None`` write to the BASE collection (which doubles
  as the shared / org-wide bucket).
* Scoped searches read BOTH the caller's collection AND the base, merging
  results — so admin-uploaded shared content stays discoverable.
* Unscoped (``user_id=None``) searches span every ``{base}__*`` collection
  plus the base. An admin must never see fewer rows than the user they are
  auditing.
* Cross-user isolation: Alice's search never surfaces Bob's chunks.

``FakeChromaClient`` stands in for the engine. It stores rows per collection
and records which collection every read touched, so the assertions are about
the collections the backend actually routed to — a scoped search that reached
into another owner's collection is the failure this file exists to catch.
"""

from typing import Any, Dict, List, Optional

import pytest

from agno.knowledge.document import Document
from agno.vectordb.chroma import ChromaDb
from agno.vectordb.chroma.chromadb import BASE_COLLECTION_METADATA_KEY

TEST_COLLECTION = "isolation_test"


class FakeCollection:
    """One Chroma collection: an id-keyed row store that logs its reads."""

    def __init__(self, name: str, metadata: Optional[Dict[str, Any]], client: "FakeChromaClient"):
        self.name = name
        self.metadata = metadata
        self._client = client
        self.rows: Dict[str, Dict[str, Any]] = {}

    def add(self, ids, embeddings, documents, metadatas) -> None:
        for row_id, embedding, document, metadata in zip(ids, embeddings, documents, metadatas):
            self.rows[row_id] = {"document": document, "metadata": dict(metadata), "embedding": embedding}

    def upsert(self, ids, embeddings, documents, metadatas) -> None:
        """Chroma's upsert is add-or-replace keyed on the row id."""
        self.add(ids, embeddings, documents, metadatas)

    def _matches(self, metadata: Dict[str, Any], where: Optional[Dict[str, Any]]) -> bool:
        """Evaluate the ``where`` shapes this backend emits: ``{field: {"$eq": v}}``,
        ``{"$in": [...]}`` and bare equality. Anything else is a loud failure rather
        than a silent match-everything."""
        if not where:
            return True
        for field, condition in where.items():
            if not isinstance(condition, dict):
                if metadata.get(field) != condition:
                    return False
                continue
            operator, expected = next(iter(condition.items()))
            if operator == "$eq":
                if metadata.get(field) != expected:
                    return False
            elif operator == "$ne":
                if metadata.get(field) == expected:
                    return False
            elif operator == "$in":
                if metadata.get(field) not in expected:
                    return False
            else:
                raise AssertionError(f"FakeCollection cannot evaluate operator {operator!r}")
        return True

    def _selected(self, where=None, where_document=None) -> List[str]:
        selected = []
        for row_id, row in self.rows.items():
            if not self._matches(row["metadata"], where):
                continue
            if where_document and where_document.get("$contains") not in row["document"]:
                continue
            selected.append(row_id)
        return selected

    def get(self, where=None, where_document=None, limit=None, include=None) -> Dict[str, Any]:
        self._client.fetched.append(self.name)
        ids = self._selected(where, where_document)[:limit]
        return {
            "ids": ids,
            "metadatas": [self.rows[i]["metadata"] for i in ids],
            "documents": [self.rows[i]["document"] for i in ids],
            "embeddings": [self.rows[i]["embedding"] for i in ids],
        }

    def query(self, query_embeddings, n_results=5, where=None, include=None) -> Dict[str, Any]:
        self._client.queried.append(self.name)
        ids = self._selected(where)[:n_results]
        return {
            "ids": [ids],
            "metadatas": [[self.rows[i]["metadata"] for i in ids]],
            "documents": [[self.rows[i]["document"] for i in ids]],
            "embeddings": [[self.rows[i]["embedding"] for i in ids]],
            # Distances ascend with insertion order so the cross-collection
            # merge in ``search`` has something real to sort by.
            "distances": [[0.1 * (rank + 1) for rank in range(len(ids))]],
        }

    def delete(self, ids) -> None:
        for row_id in ids:
            self.rows.pop(row_id, None)

    def count(self) -> int:
        return len(self.rows)


class FakeChromaClient:
    """A Chroma client stand-in that records every collection a read touched."""

    def __init__(self):
        self.collections: Dict[str, FakeCollection] = {}
        # Collection names that received a vector query / a get, in call order.
        self.queried: List[str] = []
        self.fetched: List[str] = []
        # Older Chroma returns names from list_collections, newer returns objects.
        self.list_collections_returns_names = False

    def get_collection(self, name: str) -> FakeCollection:
        if name not in self.collections:
            raise ValueError(f"Collection {name} does not exist")
        return self.collections[name]

    def create_collection(self, name: str, metadata=None) -> FakeCollection:
        self.collections[name] = FakeCollection(name, metadata, self)
        return self.collections[name]

    def get_or_create_collection(self, name: str, metadata=None) -> FakeCollection:
        if name not in self.collections:
            return self.create_collection(name, metadata)
        return self.collections[name]

    def delete_collection(self, name: str) -> None:
        self.collections.pop(name, None)

    def list_collections(self):
        if self.list_collections_returns_names:
            return list(self.collections)
        return list(self.collections.values())

    def get_max_batch_size(self) -> int:
        return 100


@pytest.fixture
def chroma_db(mock_embedder):
    """A ChromaDb wired to FakeChromaClient — no engine, no path on disk."""
    db = ChromaDb(
        collection=TEST_COLLECTION,
        path="tmp/never-written",
        persistent_client=False,
        embedder=mock_embedder,
    )
    db._client = FakeChromaClient()  # type: ignore[assignment]
    db.create()
    return db


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
        # An empty owner has no per-user collection of its own, so it lands on
        # the base one. It is still an owner, not the unscoped read — see
        # TestEmptyStringIsAScopeNotAnAdminView.
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
        chroma_db.client.queried.clear()
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

    def test_scoped_search_reads_only_the_caller_and_the_base(self, populated_db):
        """The routing itself, not just the rows it returned. Bob's collection
        is never even opened, so there is nothing to leak."""
        populated_db.search(query="salary", limit=10, user_id="alice")

        assert populated_db.client.queried == [f"{TEST_COLLECTION}__alice", TEST_COLLECTION]

    def test_unknown_owner_reads_only_the_base(self, populated_db):
        """Carol has never uploaded. Her scope resolves to the shared bucket
        alone — not to every collection, which would be an admin read."""
        results = populated_db.search(query="anything", limit=10, user_id="carol")

        assert populated_db.client.queried == [TEST_COLLECTION]
        assert {d.name for d in results} == {"company-holidays"}

    def test_admin_user_id_none_sees_every_owner(self, populated_db):
        """``user_id=None`` is the unscoped read, so it spans every owner's
        collection plus the shared base — the same thing dropping the owner
        predicate does on pgvector / LanceDB. Chroma reaches it by listing
        its own ``{base}__*`` collections rather than by widening a filter."""
        results = populated_db.search(query="anything", limit=10, user_id=None)
        names = {d.name for d in results}

        assert "company-holidays" in names
        assert "alice-salary" in names
        assert "bob-salary" in names

    def test_unscoped_search_reads_every_owner_collection(self, populated_db):
        """The routing behind the assertion above."""
        populated_db.search(query="anything", limit=10, user_id=None)

        assert sorted(populated_db.client.queried) == sorted(
            [TEST_COLLECTION, f"{TEST_COLLECTION}__alice", f"{TEST_COLLECTION}__bob"]
        )

    def test_unscoped_search_spans_owners_when_chroma_lists_names(self, populated_db):
        """Older Chroma returns collection NAMES from ``list_collections``,
        newer versions return objects. The unscoped read has to span every
        owner either way."""
        populated_db.client.list_collections_returns_names = True

        results = populated_db.search(query="anything", limit=10, user_id=None)

        assert {d.name for d in results} == {"alice-salary", "bob-salary", "company-holidays"}

    def test_an_unscoped_read_never_returns_less_than_a_scoped_one(self, populated_db):
        """Guards the inversion: an admin must not see fewer rows than the
        user they are auditing."""
        scoped = populated_db.search(query="anything", limit=10, user_id="alice")
        unscoped = populated_db.search(query="anything", limit=10, user_id=None)

        assert len(unscoped) >= len(scoped)


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
        chroma_db.client.fetched.clear()
        return chroma_db

    def test_scoped_delete_only_touches_callers_collection(self, populated_db):
        """Bob deletes 'doc-1' scoped to himself — alice's chunks remain
        in alice's collection."""
        populated_db.delete_by_content_id("doc-1", user_id="bob")

        alice_coll = populated_db.client.get_collection(name=f"{TEST_COLLECTION}__alice")
        bob_coll = populated_db.client.get_collection(name=f"{TEST_COLLECTION}__bob")
        assert len(alice_coll.get()["ids"]) == 1
        assert len(bob_coll.get()["ids"]) == 0

    def test_scoped_delete_never_opens_another_owners_collection(self, populated_db):
        populated_db.delete_by_content_id("doc-1", user_id="bob")

        assert populated_db.client.fetched == [f"{TEST_COLLECTION}__bob"]

    def test_alice_can_delete_her_own(self, populated_db):
        populated_db.delete_by_content_id("doc-1", user_id="alice")

        alice_coll = populated_db.client.get_collection(name=f"{TEST_COLLECTION}__alice")
        bob_coll = populated_db.client.get_collection(name=f"{TEST_COLLECTION}__bob")
        assert len(alice_coll.get()["ids"]) == 0
        assert len(bob_coll.get()["ids"]) == 1

    def test_unscoped_delete_targets_base_collection_only(self, populated_db):
        """``user_id=None`` only operates on the base/shared collection
        — it cannot delete from a per-user collection. The unscoped READ
        spans every owner; the unscoped DELETE deliberately does not,
        so an admin cleanup can't wipe every user's chunks at once."""
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


class TestContentHashExistsScope:
    """The dedup existence gate is scoped by collection, not by a predicate:
    with an owner it reads that owner's collection alone, so another owner's
    identical upload is never judged a duplicate — ``skip_if_exists`` would
    otherwise deny the second owner a copy of content they cannot retrieve.
    ``None`` reads the base collection alone, the same one
    ``_delete_by_content_hash`` clears for ``None`` — this gate is the guard half
    of that pair and the two halves have to address the same bucket."""

    @pytest.fixture
    def populated_db(self, chroma_db):
        """One hash Bob owns, a different one in the shared base collection."""
        chroma_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        chroma_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        chroma_db.client.fetched.clear()
        return chroma_db

    def test_owner_sees_his_own_hash(self, populated_db):
        assert populated_db.content_hash_exists("hb", user_id="bob") is True

    def test_another_owners_hash_is_not_a_duplicate(self, populated_db):
        """Alice uploading the bytes Bob already holds must not be skipped —
        she has no copy of her own to retrieve."""
        assert populated_db.content_hash_exists("hb", user_id="alice") is False

    def test_the_shared_hash_is_not_the_owners_duplicate(self, populated_db):
        """Same rule for the shared bucket: it is not Bob's collection."""
        assert populated_db.content_hash_exists("hs", user_id="bob") is False

    def test_scoped_check_reads_only_the_callers_collection(self, populated_db):
        """The routing behind it — the base collection is not consulted."""
        populated_db.content_hash_exists("hb", user_id="bob")

        assert populated_db.client.fetched == [f"{TEST_COLLECTION}__bob"]

    def test_a_privately_owned_hash_is_not_in_the_shared_bucket(self, populated_db):
        """The regression. ``None`` used to span every owner's collection, so a
        hash Bob privately held answered True for the shared bucket — and a later
        shared publish under ``skip_if_exists`` was swallowed, leaving the base
        collection without the content it was asked to hold."""
        assert populated_db.content_hash_exists("hb", user_id=None) is False

    def test_unscoped_check_sees_the_shared_bucket_too(self, populated_db):
        assert populated_db.content_hash_exists("hs", user_id=None) is True

    def test_unscoped_check_reads_the_base_collection_only(self, populated_db):
        """The routing behind it: the base collection, and no owner's."""
        populated_db.content_hash_exists("hb", user_id=None)

        assert populated_db.client.fetched == [TEST_COLLECTION]

    def test_shared_publish_survives_a_private_holder(self, populated_db):
        """The user-visible half: with the gate reading the base collection only,
        the shared publish is not skipped and the base collection really ends up
        holding the hash — which is what ``skip_if_exists`` used to prevent."""
        if not populated_db.content_hash_exists("hb", user_id=None):
            populated_db.insert(content_hash="hb", documents=_bob_docs(), user_id=None)

        base = populated_db.client.collections[TEST_COLLECTION]
        assert [row["metadata"]["content_hash"] for row in base.rows.values()] == ["hs", "hb"]


class TestUpsertDedupScope:
    """``upsert`` deletes any stored copy of the same ``content_hash`` before
    it rewrites the chunks. That delete has to land in the caller's own
    collection: it used to always target the base one, so a user upserting
    content the admin had already shared deleted the shared copy for everyone.
    """

    @pytest.fixture
    def shared_db(self, chroma_db):
        """An admin upload with no owner (base collection) and one chunk Bob
        already owns, so his collection exists before the upsert under test."""
        chroma_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        chroma_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        chroma_db.client.fetched.clear()
        return chroma_db

    def test_scoped_upsert_of_identical_content_keeps_the_shared_copy(self, shared_db):
        """The keystone. Bob upserts byte-identical content under his own
        scope — the company-wide document must survive."""
        shared_db.upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")

        base = shared_db.client.get_collection(name=TEST_COLLECTION)
        assert len(base.get()["ids"]) == 1

    def test_another_owner_can_still_retrieve_the_shared_doc(self, shared_db):
        """The user-visible half of the assertion above: Alice's retrieval of
        the org-wide document still works after Bob's upsert."""
        shared_db.upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")

        results = shared_db.search(query="anything", limit=10, user_id="alice")
        assert {d.name for d in results} == {"company-holidays"}

    def test_scoped_upsert_writes_the_callers_own_copy(self, shared_db):
        shared_db.upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")

        bob_coll = shared_db.client.get_collection(name=f"{TEST_COLLECTION}__bob")
        assert {row["name"] for row in bob_coll.get()["metadatas"]} == {"bob-salary", "company-holidays"}

    def test_scoped_upsert_never_reads_the_base_collection(self, shared_db):
        """The routing behind it: both halves of the dedup pair — the
        existence gate and the delete — stay inside Bob's collection."""
        shared_db.upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")

        assert shared_db.client.fetched == [f"{TEST_COLLECTION}__bob"]

    def test_re_upsert_by_an_owner_leaves_the_shared_copy_alone(self, shared_db):
        """The dedup delete actually running: Bob's second upsert of the same
        hash finds his own chunks, clears them, and stops there."""
        shared_db.upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")
        shared_db.upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")

        base = shared_db.client.get_collection(name=TEST_COLLECTION)
        assert len(base.get()["ids"]) == 1

    def test_owner_re_upserting_his_own_content_still_dedups(self, shared_db):
        """Scoping the dedup must not switch it off — Bob's second upsert of
        the same hash replaces his chunks instead of piling up new ones."""
        shared_db.upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")
        shared_db.upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")

        bob_coll = shared_db.client.get_collection(name=f"{TEST_COLLECTION}__bob")
        assert len(bob_coll.get()["ids"]) == 2

    async def test_async_upsert_keeps_the_shared_copy(self, shared_db):
        """``async_upsert`` carries the same dedup pair as the sync path."""
        await shared_db.async_upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")

        base = shared_db.client.get_collection(name=TEST_COLLECTION)
        bob_coll = shared_db.client.get_collection(name=f"{TEST_COLLECTION}__bob")
        assert len(base.get()["ids"]) == 1
        assert len(bob_coll.get()["ids"]) == 2


class TestDeleteByContentHashScope:
    """``_delete_by_content_hash`` routes exactly like ``delete_by_content_id``:
    to the caller's collection when scoped, to the base one when not."""

    @pytest.fixture
    def populated_db(self, chroma_db):
        """The same content hash stored three times over — shared, Alice's and
        Bob's — which is what a re-upload of an org-wide document looks like."""
        chroma_db.insert(content_hash="h", documents=_shared_docs(), user_id=None)
        chroma_db.insert(content_hash="h", documents=_shared_docs(), user_id="alice")
        chroma_db.insert(content_hash="h", documents=_shared_docs(), user_id="bob")
        chroma_db.client.fetched.clear()
        return chroma_db

    def _counts(self, db) -> List[int]:
        """Row count of the base, Alice's and Bob's collections, in that order."""
        return [
            len(db.client.get_collection(name=name).get()["ids"])
            for name in (TEST_COLLECTION, f"{TEST_COLLECTION}__alice", f"{TEST_COLLECTION}__bob")
        ]

    def test_scoped_delete_clears_only_the_owner(self, populated_db):
        populated_db._delete_by_content_hash("h", user_id="bob")

        assert self._counts(populated_db) == [1, 1, 0]

    def test_none_delete_clears_only_the_shared_bucket(self, populated_db):
        """``None`` addresses the shared bucket alone — the same semantics
        pgvector and LanceDB give it — so a shared re-upsert can't wipe an
        owner's identical-content chunks."""
        populated_db._delete_by_content_hash("h", user_id=None)

        assert self._counts(populated_db) == [0, 1, 1]

    def test_delete_for_an_owner_with_no_collection_is_a_no_op(self, populated_db):
        """Carol has never written. Her scoped delete returns False and leaves
        every collection alone."""
        assert populated_db._delete_by_content_hash("h", user_id="carol") is False
        assert self._counts(populated_db) == [1, 1, 1]


class TestEmptyStringIsAScopeNotAnAdminView:
    """``""`` is falsy but it is still an owner the caller asked for. Widening
    it to the unscoped read would hand every owner's rows to whoever sent an
    empty user id — a header that failed to populate, say."""

    @pytest.fixture
    def populated_db(self, chroma_db):
        chroma_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        chroma_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        chroma_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        chroma_db.client.queried.clear()
        return chroma_db

    def test_empty_owner_never_sees_another_owners_chunk(self, populated_db):
        results = populated_db.search(query="salary", limit=10, user_id="")
        names = {d.name for d in results}

        assert "alice-salary" not in names
        assert "bob-salary" not in names

    def test_empty_owner_reads_the_base_collection_only(self, populated_db):
        """The routing behind the assertion above: no per-user collection is
        opened at all."""
        results = populated_db.search(query="anything", limit=10, user_id="")

        assert populated_db.client.queried == [TEST_COLLECTION]
        assert {d.name for d in results} == {"company-holidays"}

    def test_empty_owner_sees_strictly_less_than_the_admin_view(self, populated_db):
        empty = populated_db.search(query="anything", limit=10, user_id="")
        admin = populated_db.search(query="anything", limit=10, user_id=None)

        assert len(empty) < len(admin)


class TestSiblingKnowledgeBasesAreNotSwept:
    """A knowledge base literally named ``{base}__something`` is a different
    knowledge base, not one of our per-user collections. Per-user collections
    are tagged in their metadata at creation, and the sweep matches on the tag
    rather than on the name prefix."""

    SIBLING = f"{TEST_COLLECTION}__notes"

    @pytest.fixture
    def db_with_sibling(self, chroma_db):
        chroma_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        chroma_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)

        # A second knowledge base whose base collection collides with our
        # per-user naming scheme. It carries no owner tag.
        sibling = chroma_db.client.create_collection(name=self.SIBLING, metadata={"hnsw:space": "cosine"})
        sibling.add(
            ids=["sibling-1"],
            embeddings=[[0.1, 0.2, 0.3]],
            documents=["Someone else's private notes."],
            metadatas=[{"name": "sibling-notes"}],
        )
        chroma_db.client.queried.clear()
        return chroma_db

    def test_per_user_collection_carries_the_owner_tag(self, chroma_db):
        """The key is written into collection metadata that outlives the process,
        so the literal is pinned here as well as read off the constant — renaming
        the constant alone must not silently change what is on disk."""
        chroma_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")

        alice_coll = chroma_db.client.get_collection(name=f"{TEST_COLLECTION}__alice")
        assert BASE_COLLECTION_METADATA_KEY == "agno_base_collection"
        assert alice_coll.metadata[BASE_COLLECTION_METADATA_KEY] == TEST_COLLECTION

    def test_base_collection_is_not_tagged(self, chroma_db):
        chroma_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)

        base = chroma_db.client.get_collection(name=TEST_COLLECTION)
        assert "agno_base_collection" not in (base.metadata or {})

    def test_a_collection_tagged_with_the_old_key_is_not_ours(self, chroma_db):
        """There is no back-compat read of the pre-rename ``agno_user_scope_of``
        tag: ``user_id`` ships unreleased, so a collection carrying only the old
        key is a stranger's, exactly like an untagged one. Reading both keys would
        make any collection ever tagged by a foreign tool sweepable by ``drop``."""
        chroma_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        stale = chroma_db.client.create_collection(
            name=f"{TEST_COLLECTION}__stale",
            metadata={"hnsw:space": "cosine", "agno_user_scope_of": TEST_COLLECTION},
        )
        stale.add(
            ids=["stale-1"],
            embeddings=[[0.1, 0.2, 0.3]],
            documents=["Chunks written by an earlier build."],
            metadatas=[{"name": "stale-notes"}],
        )

        assert chroma_db._user_collection_names() == []

        results = chroma_db.search(query="anything", limit=10, user_id=None)
        assert "stale-notes" not in {d.name for d in results}

        chroma_db.drop()
        assert [c.name for c in chroma_db.client.list_collections()] == [f"{TEST_COLLECTION}__stale"]

    def test_unscoped_read_skips_the_sibling(self, db_with_sibling):
        results = db_with_sibling.search(query="anything", limit=10, user_id=None)

        assert self.SIBLING not in db_with_sibling.client.queried
        assert "sibling-notes" not in {d.name for d in results}

    def test_unscoped_read_still_spans_our_own_owners(self, db_with_sibling):
        """The tag must not cost us the collections that ARE ours."""
        results = db_with_sibling.search(query="anything", limit=10, user_id=None)

        assert {d.name for d in results} == {"alice-salary", "company-holidays"}

    def test_unscoped_read_skips_the_sibling_when_chroma_lists_names(self, db_with_sibling):
        """Older Chroma returns names from ``list_collections``, so the tag has
        to be fetched per collection — the sibling still stays out."""
        db_with_sibling.client.list_collections_returns_names = True

        results = db_with_sibling.search(query="anything", limit=10, user_id=None)

        assert self.SIBLING not in db_with_sibling.client.queried
        assert {d.name for d in results} == {"alice-salary", "company-holidays"}

    def test_drop_leaves_the_sibling_alone(self, db_with_sibling):
        db_with_sibling.drop()

        remaining = [c.name for c in db_with_sibling.client.list_collections()]
        assert remaining == [self.SIBLING]


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
