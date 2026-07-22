"""Couchbase per-user RAG isolation contract (server-free unit test).

Isolation is a top-level ``user_id`` field on each document plus an own-OR-shared
scope prefilter on the FTS vector query. Shared/admin rows store the ``__shared__``
sentinel; scoped rows fold the owner into the document key so two users can hold
the same content without clobbering each other.

The adapter builds a ``Cluster`` and drives it through ``self.scope.query(n1ql,
QueryOptions(named_parameters=...))``, ``self.collection.upsert_multi(...)`` /
``insert_multi(...)`` / ``remove(...)``, and an FTS vector search whose prefilter
carries the scope. We patch the ``Cluster`` (and ``AsyncCluster``) constructor and
inject fakes that capture the isolation-determining values — the N1QL WHERE text +
named_parameters, the upserted document bodies and keys, the removed ids, and the
FTS prefilter query. No Couchbase server is contacted; the patch guarantees a real
connection can never be made, so the isolation logic itself is what is under test
(same mock approach as ``test_pineconedb_user_isolation.py`` /
``test_upstashdb_user_isolation.py``).
"""

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# Skip the whole module cleanly only if the optional dependency is absent.
pytest.importorskip("couchbase")

from couchbase.options import ClusterOptions  # noqa: E402

from agno.knowledge.document import Document  # noqa: E402
from agno.vectordb.couchbase.couchbase import CouchbaseSearch  # noqa: E402

MOD = "agno.vectordb.couchbase.couchbase."

BUCKET = "iso_bucket"
SCOPE = "iso_scope"
COLLECTION = "iso_collection"
INDEX = "iso_index"
DIMS = 8


class _DeterministicEmbedder:
    """Hash-based embedder — no network, no API key."""

    dimensions = DIMS
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

    def embed(self, *args, **kwargs):
        pass

    async def async_embed(self, *args, **kwargs):
        pass


def _embedded(name: str, content: str, **kwargs) -> Document:
    """A Document with a precomputed embedding so direct writes need no round-trip."""
    doc = Document(name=name, content=content, **kwargs)
    doc.embedding = _DeterministicEmbedder().get_embedding(content)
    return doc


# ===========================================================================
# Fakes that capture what the adapter sends to Couchbase.
# ===========================================================================


class _Recorder:
    """Shared sink for everything the adapter routes at the (faked) cluster."""

    def __init__(self):
        # Sync N1QL: list of (n1ql_text, named_parameters).
        self.queries: List[tuple] = []
        # Rows the next scope.query() call should return (settable per test).
        self.query_rows: List[Dict[str, Any]] = []
        # Bodies passed to upsert_multi / insert_multi: list of {doc_id: body}.
        self.upserted: List[Dict[str, Any]] = []
        self.inserted: List[Dict[str, Any]] = []
        # Ids passed to collection.remove().
        self.removed: List[str] = []
        # Prefilter query objects handed to VectorQuery (sync + async).
        self.prefilters: List[Any] = []
        # (index, request) tuples handed to scope.search / async scope.search.
        self.searches: List[tuple] = []

    @staticmethod
    def _named_params(options) -> Dict[str, Any]:
        # QueryOptions is a plain dict subclass, so named_parameters reads directly.
        return dict(options).get("named_parameters", {}) if options is not None else {}


class _MultiResult:
    all_ok = True
    exceptions: Dict[str, Any] = {}


class _QueryResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def rows(self):
        return list(self._rows)


class _FakeCollection:
    def __init__(self, rec: _Recorder):
        self._rec = rec

    def upsert_multi(self, docs):
        self._rec.upserted.append(dict(docs))
        return _MultiResult()

    def insert_multi(self, docs):
        self._rec.inserted.append(dict(docs))
        return _MultiResult()

    def remove(self, doc_id):
        self._rec.removed.append(doc_id)

    def exists(self, doc_id):
        return MagicMock(exists=True)


class _FakeScope:
    def __init__(self, rec: _Recorder, collection: _FakeCollection):
        self._rec = rec
        self._collection = collection

    def collection(self, name):
        return self._collection

    def query(self, n1ql, options=None):
        self._rec.queries.append((n1ql, self._rec._named_params(options)))
        return _QueryResult(self._rec.query_rows)

    def search(self, index, request, options=None):
        self._rec.searches.append((index, request))
        return _QueryResult([])  # empty hits -> search() returns []


class _FakeBucket:
    def __init__(self, scope: _FakeScope):
        self._scope = scope

    def scope(self, name):
        return self._scope


class _FakeCluster:
    def __init__(self, bucket: _FakeBucket):
        self._bucket = bucket

    def wait_until_ready(self, timeout=None):
        return None

    def bucket(self, name):
        return self._bucket


# --- async fakes -----------------------------------------------------------


class _FakeAsyncResult:
    def __init__(self, rows):
        self._rows = list(rows)

    async def _agen(self):
        for row in self._rows:
            yield row

    def rows(self):
        return self._agen()


class _FakeAsyncScope:
    def __init__(self, rec: _Recorder, collection):
        self._rec = rec
        self._collection = collection

    def collection(self, name):
        return self._collection

    def search(self, index, request, options=None):
        self._rec.searches.append((index, request))
        return _FakeAsyncResult([])


class _FakeAsyncBucket:
    def __init__(self, scope):
        self._scope = scope

    def scope(self, name):
        return self._scope


class _FakeAsyncCluster:
    def __init__(self, bucket):
        self._bucket = bucket

    def bucket(self, name):
        return self._bucket


def _make_db(**overrides) -> CouchbaseSearch:
    params = dict(
        bucket_name=BUCKET,
        scope_name=SCOPE,
        collection_name=COLLECTION,
        couchbase_connection_string="couchbase://localhost",
        cluster_options=MagicMock(spec=ClusterOptions),
        search_index=INDEX,
        embedder=_DeterministicEmbedder(),
    )
    params.update(overrides)
    return CouchbaseSearch(**params)


@pytest.fixture
def db_and_rec():
    """A CouchbaseSearch whose Cluster/AsyncCluster and FTS query builders are
    patched so nothing connects. Yields (db, recorder)."""
    rec = _Recorder()
    collection = _FakeCollection(rec)
    scope = _FakeScope(rec, collection)
    cluster = _FakeCluster(_FakeBucket(scope))

    async_scope = _FakeAsyncScope(rec, collection)
    async_cluster = _FakeAsyncCluster(_FakeAsyncBucket(async_scope))

    fake_async_cls = MagicMock()

    async def _connect(conn, opts):
        return async_cluster

    fake_async_cls.connect = _connect

    def _capture_vector_query(**kwargs):
        rec.prefilters.append(kwargs.get("prefilter"))
        return MagicMock()

    with (
        patch(MOD + "Cluster", return_value=cluster),
        patch(MOD + "AsyncCluster", fake_async_cls),
        patch(MOD + "VectorQuery", side_effect=_capture_vector_query),
        patch(MOD + "VectorSearch"),
        patch(MOD + "SearchRequest"),
    ):
        yield _make_db(), rec


# ===========================================================================
# 1. Owner persisted on write (static prepare_doc + captured upsert body).
# ===========================================================================


class TestOwnerPersistedOnWrite:
    """``user_id`` is a top-level document field (NOT nested in the filters blob);
    ``None`` maps to the shared sentinel. Verified both on the pure ``prepare_doc``
    contract and on the actual body handed to ``collection.upsert_multi``."""

    def test_constants(self):
        assert CouchbaseSearch.USER_ID_FIELD == "user_id"
        assert CouchbaseSearch.SHARED_USER_ID == "__shared__"

    def test_explicit_owner_stamped_top_level(self):
        prepared = _make_db().prepare_doc("h1", _embedded("d", "secret content"), user_id="alice")
        assert prepared[CouchbaseSearch.USER_ID_FIELD] == "alice"
        assert "filters" not in prepared

    def test_none_stores_shared_sentinel(self):
        prepared = _make_db().prepare_doc("h1", _embedded("d", "shared content"), user_id=None)
        assert prepared[CouchbaseSearch.USER_ID_FIELD] == CouchbaseSearch.SHARED_USER_ID

    def test_upsert_body_carries_owner(self, db_and_rec):
        """The document body actually written for a scoped user carries the real
        owner in USER_ID_FIELD (content_hash_exists returns no rows -> no dedup delete)."""
        db, rec = db_and_rec
        db.upsert(content_hash="h1", documents=[_embedded("d", "secret content")], user_id="alice")
        body = next(iter(rec.upserted[0].values()))
        assert body[CouchbaseSearch.USER_ID_FIELD] == "alice"

    def test_upsert_body_none_is_shared_sentinel(self, db_and_rec):
        db, rec = db_and_rec
        db.upsert(content_hash="h1", documents=[_embedded("d", "shared content")], user_id=None)
        body = next(iter(rec.upserted[0].values()))
        assert body[CouchbaseSearch.USER_ID_FIELD] == CouchbaseSearch.SHARED_USER_ID


# ===========================================================================
# 2. Owner folded into the KV key (steal / clobber prevention).
# ===========================================================================


class TestOwnerFoldedIntoKey:
    """Byte-identical content for different owners yields distinct KV keys so one
    owner's write can't clobber another's; the shared bucket keeps the legacy id."""

    def test_prepare_doc_folds_owner_into_id(self):
        db = _make_db()
        alice_id = db.prepare_doc("h", _embedded("d", "same content"), user_id="alice")["_id"]
        bob_id = db.prepare_doc("h", _embedded("d", "same content"), user_id="bob")["_id"]
        shared_id = db.prepare_doc("h", _embedded("d", "same content"), user_id=None)["_id"]
        assert alice_id != bob_id
        assert alice_id != shared_id
        assert bob_id != shared_id

    def test_upsert_keys_distinct_per_owner(self, db_and_rec):
        """The keys actually handed to upsert_multi differ per owner for identical
        content, so bob's upsert lands on a different key than alice's."""
        db, rec = db_and_rec
        db.upsert(content_hash="h", documents=[_embedded("d", "same content")], user_id="alice")
        alice_key = next(iter(rec.upserted[-1].keys()))
        db.upsert(content_hash="h", documents=[_embedded("d", "same content")], user_id="bob")
        bob_key = next(iter(rec.upserted[-1].keys()))
        db.upsert(content_hash="h", documents=[_embedded("d", "same content")], user_id=None)
        shared_key = next(iter(rec.upserted[-1].keys()))
        assert len({alice_key, bob_key, shared_key}) == 3


# ===========================================================================
# 3. Read scope: own-OR-shared prefilter; admin (None) unscoped.
# ===========================================================================


class TestReadScope:
    """A scoped search restricts to the caller's own chunks OR the ``__shared__``
    bucket, and never another user's; admin (None) applies no scope. The prefilter
    the adapter feeds the FTS vector query IS the read-scope contract."""

    def test_user_scope_query_is_own_or_shared(self):
        db = _make_db()
        q = db._user_scope_query("alice")
        terms = {(d["field"], d["term"]) for d in q.encodable["disjuncts"]}
        # Own-OR-shared: matches alice's chunks OR the shared bucket, never bob's.
        assert terms == {("user_id", "alice"), ("user_id", "__shared__")}
        assert ("user_id", "bob") not in terms

    def test_admin_scope_query_is_none(self):
        assert _make_db()._user_scope_query(None) is None

    def test_search_feeds_own_or_shared_prefilter(self, db_and_rec):
        """search() wires _user_scope_query(user_id) into the FTS vector prefilter."""
        db, rec = db_and_rec
        db.search(query="q", user_id="alice")
        prefilter = rec.prefilters[-1]
        assert prefilter is not None
        terms = {(d["field"], d["term"]) for d in prefilter.encodable["disjuncts"]}
        assert terms == {("user_id", "alice"), ("user_id", "__shared__")}

    def test_admin_search_has_no_prefilter(self, db_and_rec):
        """user_id=None -> no scope predicate on the vector query; admin sees all."""
        db, rec = db_and_rec
        db.search(query="q", user_id=None)
        assert rec.prefilters[-1] is None

    async def test_async_search_feeds_own_or_shared_prefilter(self, db_and_rec):
        """The async path (real acouchbase impl) scopes identically to sync."""
        db, rec = db_and_rec
        await db.async_search(query="q", user_id="alice")
        prefilter = rec.prefilters[-1]
        assert prefilter is not None
        terms = {(d["field"], d["term"]) for d in prefilter.encodable["disjuncts"]}
        assert terms == {("user_id", "alice"), ("user_id", "__shared__")}

    async def test_async_admin_search_has_no_prefilter(self, db_and_rec):
        db, rec = db_and_rec
        await db.async_search(query="q", user_id=None)
        assert rec.prefilters[-1] is None


# ===========================================================================
# 4. Scoped dedup: the upsert dedupe-delete is bound to the writing owner.
# ===========================================================================


class TestContentHashDedupScope:
    """The per-user dedup path keys on ``content_hash`` bound to the owner. A scoped
    delete touches only that owner's rows; ``None`` binds the ``__shared__`` sentinel
    (never every owner's rows). The N1QL WHERE + named_parameters IS the contract."""

    def test_delete_by_content_hash_binds_owner(self, db_and_rec):
        db, rec = db_and_rec
        db._delete_by_content_hash("h1", user_id="alice")
        n1ql, params = rec.queries[-1]
        assert "content_hash = $content_hash AND user_id = $user_id" in n1ql
        assert params == {"content_hash": "h1", "user_id": "alice"}

    def test_delete_by_content_hash_none_binds_shared_sentinel(self, db_and_rec):
        """None must NOT clear every owner's row — it binds the __shared__ sentinel,
        so only the shared bucket's stale chunk is removed."""
        db, rec = db_and_rec
        db._delete_by_content_hash("h1", user_id=None)
        n1ql, params = rec.queries[-1]
        assert "content_hash = $content_hash AND user_id = $user_id" in n1ql
        assert params == {"content_hash": "h1", "user_id": CouchbaseSearch.SHARED_USER_ID}

    def test_content_hash_exists_scoped_to_owner(self, db_and_rec):
        db, rec = db_and_rec
        db.content_hash_exists("h1", user_id="alice")
        n1ql, params = rec.queries[-1]
        assert "content_hash = $content_hash AND user_id = $user_id" in n1ql
        assert params == {"content_hash": "h1", "user_id": "alice"}

    def test_content_hash_exists_unscoped_matches_any_owner(self, db_and_rec):
        """None is the unscoped existence gate — no user_id predicate, matches any owner."""
        db, rec = db_and_rec
        db.content_hash_exists("h1", user_id=None)
        n1ql, params = rec.queries[-1]
        assert "content_hash = $content_hash" in n1ql
        assert "user_id" not in n1ql
        assert params == {"content_hash": "h1"}

    def test_upsert_dedup_delete_scoped_to_writing_owner(self, db_and_rec):
        """When the writer's own chunk already exists, the pre-delete binds that
        owner only, so another owner's identical-content row is left intact."""
        db, rec = db_and_rec
        rec.query_rows = [{"doc_id": "stale-1"}]  # content_hash_exists -> True, dedup runs
        db.upsert(content_hash="h1", documents=[_embedded("d", "same content")], user_id="bob")
        # The dedupe-delete query (first query issued) is scoped to bob.
        dedup_n1ql, dedup_params = rec.queries[0]
        assert dedup_params == {"content_hash": "h1", "user_id": "bob"}
        # And only the row that scoped query returned is removed.
        assert rec.removed == ["stale-1"]


# ===========================================================================
# 5. Scoped delete_by_content_id: owner-scoped vs unscoped (admin) wipe.
# ===========================================================================


class TestDeleteByContentIdScope:
    """``delete_by_content_id(content_id, user_id=...)`` scopes the delete to the
    caller's rows so Bob can't wipe Alice's chunks by guessing her content_id.
    Admin (None) spans all owners."""

    def test_scoped_delete_ands_owner(self, db_and_rec):
        db, rec = db_and_rec
        rec.query_rows = [{"doc_id": "d-alice"}]
        db.delete_by_content_id("cid-1", user_id="alice")
        n1ql, params = rec.queries[-1]
        assert "AND user_id = $user_id" in n1ql
        assert params == {"content_id": "cid-1", "user_id": "alice"}
        # Removes only what the owner-scoped query returned.
        assert rec.removed == ["d-alice"]

    def test_unscoped_delete_spans_all_owners(self, db_and_rec):
        db, rec = db_and_rec
        db.delete_by_content_id("cid-1", user_id=None)
        n1ql, params = rec.queries[-1]
        # No owner predicate -> matches the content_id across every owner.
        assert "user_id" not in n1ql
        assert params == {"content_id": "cid-1"}


# ===========================================================================
# 6. Insert path stamps the owner into the written body too.
# ===========================================================================


class TestInsertPersistsOwner:
    """``insert`` (the ingestion path) stamps the owner into the body handed to
    ``collection.insert_multi`` exactly like ``upsert``."""

    def test_insert_body_carries_owner(self, db_and_rec):
        db, rec = db_and_rec
        db.insert(content_hash="h1", documents=[_embedded("d", "secret")], user_id="alice")
        body = next(iter(rec.inserted[0].values()))
        assert body[CouchbaseSearch.USER_ID_FIELD] == "alice"

    def test_insert_body_none_is_shared_sentinel(self, db_and_rec):
        db, rec = db_and_rec
        db.insert(content_hash="h1", documents=[_embedded("d", "shared")], user_id=None)
        body = next(iter(rec.inserted[0].values()))
        assert body[CouchbaseSearch.USER_ID_FIELD] == CouchbaseSearch.SHARED_USER_ID
