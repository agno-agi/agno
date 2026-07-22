"""Cassandra per-user RAG isolation contract.

The adapter stamps the owner into ``metadata['user_id']``: an explicit id for
scoped chunks, or the ``__shared__`` sentinel when ``user_id`` is None/omitted.
A scoped search unions the caller's own rows with the shared rows and never
reaches another user's bucket.

No Cassandra server is required: the cassio table class is patched with an
in-memory fake and the session is an in-memory fake sharing the same row
store, so the adapter's real owner-stamping, id-folding, own-OR-shared search
and scoped-delete logic runs against captured calls.
"""

import hashlib
from types import SimpleNamespace
from typing import List, Optional
from unittest.mock import patch

import pytest

from agno.knowledge.document import Document
from agno.utils.string import hash_string_sha256
from agno.vectordb.cassandra import Cassandra
from agno.vectordb.cassandra.cassandra import SHARED_USER_ID_VALUE, USER_ID_METADATA_KEY

# The adapter hardcodes a 1024-dim vector column; keep the fake embedder in sync.
DIM = 1024


class _DeterministicEmbedder:
    """A tiny embedder that needs no network or API key."""

    dimensions = DIM
    enable_batch = False

    def get_embedding(self, text):
        vector = [0.0] * self.dimensions
        vector[abs(hash(text)) % self.dimensions] = 1.0
        return vector

    def get_embedding_and_usage(self, text):
        return self.get_embedding(text), {"total_tokens": 1}

    async def async_get_embedding(self, text):
        return self.get_embedding(text)

    async def async_get_embedding_and_usage(self, text):
        return self.get_embedding(text), {"total_tokens": 1}

    def embed(self, document, **kwargs):
        document.embedding = self.get_embedding(document.content)
        return document

    async def async_embed(self, document, **kwargs):
        document.embedding = self.get_embedding(document.content)
        return document


class _Future:
    """Stand-in for the driver future returned by ``put_async``."""

    def result(self):
        return None


class _CountResult:
    """Mimics the driver result for ``SELECT COUNT(*)``."""

    def __init__(self, count: int):
        self._count = count

    def one(self):
        return (self._count,)


class _FakeSession:
    """An in-memory stand-in for the Cassandra session."""

    def __init__(self):
        self.rows: List[SimpleNamespace] = []
        self.executed: List = []
        self.deleted_row_ids: List[str] = []
        self.updates: List = []

    def execute(self, query, params=None):
        self.executed.append((query, params))
        q = " ".join(query.split())
        if q.startswith("SELECT COUNT(*)"):
            content_hash = params[0]
            if "metadata_s['user_id']" in q:
                user_id = params[1]
                count = sum(
                    1
                    for r in self.rows
                    if r.metadata_s.get("content_hash") == content_hash
                    and r.metadata_s.get(USER_ID_METADATA_KEY) == user_id
                )
            else:
                count = sum(1 for r in self.rows if r.metadata_s.get("content_hash") == content_hash)
            return _CountResult(count)
        if q.startswith("SELECT row_id, metadata_s"):
            return list(self.rows)
        if q.startswith("DELETE"):
            row_id = params[0]
            before = len(self.rows)
            self.rows = [r for r in self.rows if r.row_id != row_id]
            if len(self.rows) < before:
                self.deleted_row_ids.append(row_id)
            return _CountResult(0)
        if q.startswith("UPDATE"):
            new_meta, row_id = params
            for r in self.rows:
                if r.row_id == row_id:
                    r.metadata_s = dict(new_meta)
            self.updates.append((row_id, dict(new_meta)))
            return _CountResult(0)
        return _CountResult(0)


class _FakeTable:
    """An in-memory stand-in for AgnoMetadataVectorCassandraTable. It records
    the exact ``row_id`` / ``metadata`` the adapter stamps and simulates
    cassio's equality-AND metadata filter over the stored rows."""

    def __init__(self, session=None, **kwargs):
        self._session = session
        self.put_calls: List[dict] = []
        self.search_calls: List[dict] = []

    def put_async(self, row_id, vector, metadata, body_blob, document_name):
        self.put_calls.append(
            {
                "row_id": row_id,
                "vector": vector,
                "metadata": dict(metadata),
                "body_blob": body_blob,
                "document_name": document_name,
            }
        )
        self._session.rows.append(
            SimpleNamespace(
                row_id=row_id,
                metadata_s=dict(metadata),
                body_blob=body_blob,
                document_name=document_name,
                vector=vector,
            )
        )
        return _Future()

    def metric_ann_search(self, vector, n, metric, metadata=None):
        self.search_calls.append({"vector": vector, "n": n, "metric": metric, "metadata": metadata})
        hits = []
        for i, r in enumerate(self._session.rows):
            if metadata and any(r.metadata_s.get(k) != v for k, v in metadata.items()):
                continue
            hits.append(
                {
                    "row_id": r.row_id,
                    "body_blob": r.body_blob,
                    "metadata": dict(r.metadata_s),
                    "vector": r.vector,
                    "document_name": r.document_name,
                    "distance": float(len(self._session.rows) - i),
                }
            )
        return hits[:n]


@pytest.fixture
def cassandra_db():
    """A Cassandra adapter wired to the in-memory fake table + session."""
    session = _FakeSession()
    with patch("agno.vectordb.cassandra.cassandra.AgnoMetadataVectorCassandraTable", _FakeTable):
        db = Cassandra(
            table_name="vectors",
            keyspace="iso_test",
            embedder=_DeterministicEmbedder(),
            session=session,
        )
        assert isinstance(db.table, _FakeTable)
        yield db


def _doc(name: str, content: str, content_id: Optional[str] = None) -> Document:
    doc = Document(name=name, content=content)
    # Knowledge always assigns a stable id (derived from content) before insert.
    doc.id = hashlib.md5(content.encode()).hexdigest()
    doc.content_id = content_id
    return doc


def _alice_docs() -> List[Document]:
    return [_doc("alice-salary", "Alice salary is 180k")]


def _bob_docs() -> List[Document]:
    return [_doc("bob-salary", "Bob salary is 215k")]


def _shared_docs() -> List[Document]:
    return [_doc("company-holidays", "The office is closed Jan 1")]


def _owners(db) -> List[str]:
    """Owner sentinels actually written to the (fake) store."""
    return sorted(r.metadata_s.get(USER_ID_METADATA_KEY) for r in db.session.rows)


def _owners_for_content_id(db, content_id: str) -> List[str]:
    return sorted(
        r.metadata_s.get(USER_ID_METADATA_KEY) for r in db.session.rows if r.metadata_s.get("content_id") == content_id
    )


class TestStorageScheme:
    """Pin the storage contract. Changing these orphans previously written
    rows — the equality filter would stop matching them."""

    def test_constants(self, cassandra_db):
        assert USER_ID_METADATA_KEY == "user_id"
        assert SHARED_USER_ID_VALUE == "__shared__"

    def test_explicit_user_id_stamped_in_metadata(self, cassandra_db):
        cassandra_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")
        assert cassandra_db.table.put_calls[0]["metadata"][USER_ID_METADATA_KEY] == "alice"
        assert _owners(cassandra_db) == ["alice"]

    def test_none_user_id_stored_as_shared_sentinel(self, cassandra_db):
        """Shared chunks store the explicit sentinel so the shared-bucket
        equality query can find them."""
        cassandra_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)
        assert cassandra_db.table.put_calls[0]["metadata"][USER_ID_METADATA_KEY] == SHARED_USER_ID_VALUE
        assert _owners(cassandra_db) == [SHARED_USER_ID_VALUE]

    def test_user_id_omitted_defaults_to_shared(self, cassandra_db):
        cassandra_db.insert(content_hash="h1", documents=_shared_docs())
        assert _owners(cassandra_db) == [SHARED_USER_ID_VALUE]

    def test_caller_metadata_cannot_spoof_owner(self, cassandra_db):
        """A caller's own ``user_id`` key in meta_data must not override the owner."""
        doc = _doc("d", "c")
        doc.meta_data = {"user_id": "attacker"}
        cassandra_db.insert(content_hash="h1", documents=[doc], user_id="alice")
        assert cassandra_db.table.put_calls[0]["metadata"][USER_ID_METADATA_KEY] == "alice"


class TestRowIdFolding:
    """The owner is folded into the primary key so two users' identical content
    gets distinct rows; a shared row keeps the base id."""

    def test_two_owners_identical_content_get_distinct_row_ids(self, cassandra_db):
        cassandra_db.insert(content_hash="h", documents=[_doc("a", "same text")], user_id="alice")
        cassandra_db.insert(content_hash="h", documents=[_doc("b", "same text")], user_id="bob")
        alice_id = cassandra_db.table.put_calls[0]["row_id"]
        bob_id = cassandra_db.table.put_calls[1]["row_id"]
        assert alice_id != bob_id
        base_id = hashlib.md5(b"same text").hexdigest()
        assert alice_id == hash_string_sha256(f"{base_id}_alice")
        assert bob_id == hash_string_sha256(f"{base_id}_bob")

    def test_shared_row_keeps_base_id(self, cassandra_db):
        cassandra_db.insert(content_hash="h", documents=[_doc("s", "same text")], user_id=None)
        base_id = hashlib.md5(b"same text").hexdigest()
        assert cassandra_db.table.put_calls[0]["row_id"] == base_id

    def test_no_id_document_falls_back_to_content_hash_key(self, cassandra_db):
        """A document with no id must still get a deterministic key, never an
        empty/None row_id."""
        doc = Document(name="noid", content="unindexed body")
        assert doc.id is None
        cassandra_db.insert(content_hash="h", documents=[doc], user_id=None)
        assert cassandra_db.table.put_calls[0]["row_id"] == hashlib.md5(b"unindexed body").hexdigest()

    def test_no_id_document_scoped_key_folds_owner(self, cassandra_db):
        doc = Document(name="noid", content="unindexed body")
        cassandra_db.insert(content_hash="h", documents=[doc], user_id="alice")
        base_id = hashlib.md5(b"unindexed body").hexdigest()
        row_id = cassandra_db.table.put_calls[0]["row_id"]
        assert row_id == hash_string_sha256(f"{base_id}_alice")
        assert row_id


class TestSearchScopeFilter:
    """A scoped search issues TWO equality-filtered searches (own + shared) and
    merges; admin (user_id=None) issues ONE unfiltered search."""

    def test_scoped_search_issues_own_and_shared_filters(self, cassandra_db):
        cassandra_db.search("q", limit=5, user_id="alice")
        sent = [c["metadata"] for c in cassandra_db.table.search_calls]
        assert sent == [
            {USER_ID_METADATA_KEY: "alice"},
            {USER_ID_METADATA_KEY: SHARED_USER_ID_VALUE},
        ]
        # No search is ever issued for another owner's bucket.
        assert {USER_ID_METADATA_KEY: "bob"} not in sent

    def test_admin_search_is_single_unfiltered(self, cassandra_db):
        cassandra_db.search("q", limit=5, user_id=None)
        assert len(cassandra_db.table.search_calls) == 1
        assert cassandra_db.table.search_calls[0]["metadata"] is None


class TestSearchIsolationContract:
    """End-to-end: alice's search returns her chunks plus shared chunks, but
    never bob's."""

    @pytest.fixture
    def populated_db(self, cassandra_db):
        cassandra_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        cassandra_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        cassandra_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return cassandra_db

    def test_alice_sees_her_own_chunk(self, populated_db):
        names = {d.name for d in populated_db.search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in names

    def test_alice_sees_shared_chunk(self, populated_db):
        names = {d.name for d in populated_db.search("holidays", limit=10, user_id="alice")}
        assert "company-holidays" in names

    def test_alice_never_sees_bobs_chunk(self, populated_db):
        results = populated_db.search("salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "bob-salary" not in names
        for d in results:
            assert "Bob salary" not in d.content

    def test_bob_never_sees_alices_chunk(self, populated_db):
        names = {d.name for d in populated_db.search("salary", limit=10, user_id="bob")}
        assert "alice-salary" not in names

    def test_admin_sees_everything(self, populated_db):
        names = {d.name for d in populated_db.search("salary", limit=10, user_id=None)}
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names


class TestDeleteByContentIdIsolation:
    """``delete_by_content_id(content_id, user_id=...)`` must scope to the
    caller's chunks — otherwise a caller could guess someone else's content_id
    and wipe their (or the shared) chunks."""

    @pytest.fixture
    def populated_db(self, cassandra_db):
        cassandra_db.insert(content_hash="ha", documents=[_doc("alice-doc", "Alice secret", "doc-1")], user_id="alice")
        cassandra_db.insert(content_hash="hb", documents=[_doc("bob-doc", "Bob secret", "doc-1")], user_id="bob")
        cassandra_db.insert(content_hash="hs", documents=[_doc("shared-doc", "Shared note", "doc-1")], user_id=None)
        return cassandra_db

    def test_scoped_delete_only_removes_callers_chunks(self, populated_db):
        assert populated_db.delete_by_content_id("doc-1", user_id="bob") is True
        assert _owners_for_content_id(populated_db, "doc-1") == [SHARED_USER_ID_VALUE, "alice"]

    def test_alice_can_delete_her_own(self, populated_db):
        populated_db.delete_by_content_id("doc-1", user_id="alice")
        owners = _owners_for_content_id(populated_db, "doc-1")
        assert SHARED_USER_ID_VALUE in owners
        assert "alice" not in owners

    def test_unscoped_delete_wipes_everyone(self, populated_db):
        assert populated_db.delete_by_content_id("doc-1", user_id=None) is True
        assert _owners_for_content_id(populated_db, "doc-1") == []

    def test_scoped_delete_no_op_when_caller_owns_nothing(self, populated_db):
        assert populated_db.delete_by_content_id("doc-1", user_id="carol") is False
        assert len(_owners_for_content_id(populated_db, "doc-1")) == 3


class TestDeleteByContentHashIsolation:
    """``delete_by_content_hash`` scopes to the owner bucket when user_id is set;
    None scopes to the shared bucket only so it can't wipe every owner."""

    @pytest.fixture
    def populated_db(self, cassandra_db):
        cassandra_db.insert(content_hash="h", documents=[_doc("a", "alice text")], user_id="alice")
        cassandra_db.insert(content_hash="h", documents=[_doc("b", "bob text")], user_id="bob")
        cassandra_db.insert(content_hash="h", documents=[_doc("s", "shared text")], user_id=None)
        return cassandra_db

    def test_scoped_hash_delete_removes_only_owner(self, populated_db):
        assert populated_db.delete_by_content_hash("h", user_id="alice") is True
        assert _owners(populated_db) == [SHARED_USER_ID_VALUE, "bob"]

    def test_none_hash_delete_scopes_to_shared_only(self, populated_db):
        assert populated_db.delete_by_content_hash("h", user_id=None) is True
        assert _owners(populated_db) == ["alice", "bob"]


class TestUpsertDedupIsolation:
    """``upsert`` re-ingest dedups within the caller's bucket only, so two
    owners' copies of identical content never collide and a shared re-ingest
    can't steal an owned row."""

    def test_two_owners_identical_content_both_survive(self, cassandra_db):
        cassandra_db.upsert(content_hash="h", documents=[_doc("alice", "shared text")], user_id="alice")
        cassandra_db.upsert(content_hash="h", documents=[_doc("bob", "shared text")], user_id="bob")
        assert _owners(cassandra_db) == ["alice", "bob"]

    def test_same_owner_reupsert_dedups_to_one_row(self, cassandra_db):
        cassandra_db.upsert(content_hash="h", documents=[_doc("alice", "same text")], user_id="alice")
        cassandra_db.upsert(content_hash="h", documents=[_doc("alice", "same text")], user_id="alice")
        assert _owners(cassandra_db) == ["alice"]

    def test_shared_reupsert_does_not_wipe_owned_identical_content(self, cassandra_db):
        """Alice owns content X; an admin re-ingests identical shared content.
        The shared dedup delete must scope to the shared bucket and leave
        Alice's owned row intact."""
        cassandra_db.upsert(content_hash="h", documents=[_doc("alice", "same text")], user_id="alice")
        cassandra_db.upsert(content_hash="h", documents=[_doc("shared", "same text")], user_id=None)
        # Second shared re-ingest triggers the scoped dedup delete.
        cassandra_db.session.deleted_row_ids.clear()
        cassandra_db.upsert(content_hash="h", documents=[_doc("shared", "same text")], user_id=None)
        assert _owners(cassandra_db) == [SHARED_USER_ID_VALUE, "alice"]
        base_id = hashlib.md5(b"same text").hexdigest()
        alice_row_id = hash_string_sha256(f"{base_id}_alice")
        assert alice_row_id not in cassandra_db.session.deleted_row_ids
        assert cassandra_db.session.deleted_row_ids == [base_id]


class TestUpdateMetadataOwnershipGuard:
    """``update_metadata`` must drop an incoming ``user_id`` so a metadata write
    can never reassign ownership."""

    def test_incoming_user_id_is_stripped(self, cassandra_db):
        cassandra_db.insert(content_hash="h", documents=[_doc("a", "body", "doc-1")], user_id="alice")
        cassandra_db.update_metadata("doc-1", {"topic": "hr", "user_id": "attacker"})
        row = cassandra_db.session.rows[0]
        assert row.metadata_s[USER_ID_METADATA_KEY] == "alice"
        assert row.metadata_s["topic"] == "hr"
        # The UPDATE payload the adapter wrote never carried the attacker's owner.
        _, written_meta = cassandra_db.session.updates[0]
        assert written_meta[USER_ID_METADATA_KEY] == "alice"


class TestRowToDocumentHidesOwner:
    """``_row_to_document`` must never surface ``user_id`` as caller-visible
    metadata."""

    def test_user_id_not_in_returned_metadata(self, cassandra_db):
        row = {
            "row_id": "r1",
            "body_blob": "hello",
            "metadata": {"topic": "t", "content_id": "c1", USER_ID_METADATA_KEY: "alice"},
            "vector": [0.0] * DIM,
            "document_name": "doc",
        }
        doc = cassandra_db._row_to_document(row)
        assert USER_ID_METADATA_KEY not in doc.meta_data
        assert doc.meta_data["topic"] == "t"
        assert doc.content_id == "c1"


class TestAsyncIsolation:
    """The search and scoped dedup contracts hold through the async surface too."""

    async def test_async_alice_sees_own_and_shared_not_bob(self, cassandra_db):
        await cassandra_db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        await cassandra_db.async_insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        await cassandra_db.async_insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        alice = {d.name for d in await cassandra_db.async_search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in alice
        assert "company-holidays" in alice
        assert "bob-salary" not in alice

    async def test_async_shared_reupsert_does_not_wipe_owned(self, cassandra_db):
        await cassandra_db.async_upsert(content_hash="h", documents=[_doc("alice", "same text")], user_id="alice")
        await cassandra_db.async_upsert(content_hash="h", documents=[_doc("shared", "same text")], user_id=None)
        await cassandra_db.async_upsert(content_hash="h", documents=[_doc("shared", "same text")], user_id=None)
        assert _owners(cassandra_db) == [SHARED_USER_ID_VALUE, "alice"]
