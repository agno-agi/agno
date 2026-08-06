"""Couchbase per-user RAG isolation contract.

Isolation is a top-level ``user_id`` field on each document plus an own-OR-shared
scope prefilter on the FTS vector query. Shared/admin rows store the ``__shared__``
sentinel; scoped rows fold the owner into the document key so two users can hold
the same content without clobbering each other.

The ``Cluster`` / ``AsyncCluster`` constructors are patched with fakes that
capture the isolation-determining values — the N1QL WHERE text + named
parameters, the upserted document bodies and keys, the removed ids, and the
FTS prefilter query. No Couchbase server is contacted.
"""

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from couchbase.options import ClusterOptions

from agno.knowledge.document import Document
from agno.vectordb.couchbase.couchbase import CouchbaseSearch

MOD = "agno.vectordb.couchbase.couchbase."

BUCKET = "iso_bucket"
SCOPE = "iso_scope"
COLLECTION = "iso_collection"
INDEX = "iso_index"
DIMS = 8


class _DeterministicEmbedder:
    """A tiny embedder that needs no network or API key."""

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
    """A Document with a precomputed embedding so writes need no round-trip."""
    doc = Document(name=name, content=content, **kwargs)
    doc.embedding = _DeterministicEmbedder().get_embedding(content)
    return doc


def _named_params(options) -> Dict[str, Any]:
    # QueryOptions is a plain dict subclass, so named_parameters reads directly.
    return dict(options).get("named_parameters", {}) if options is not None else {}


class _Recorder:
    """Shared sink for everything the adapter routes at the (faked) cluster."""

    def __init__(self):
        self.queries: List[tuple] = []  # (n1ql_text, named_parameters)
        self.query_rows: List[Dict[str, Any]] = []  # rows the next scope.query() returns
        self.upserted: List[Dict[str, Any]] = []  # bodies passed to upsert_multi
        self.inserted: List[Dict[str, Any]] = []  # bodies passed to insert_multi
        self.removed: List[str] = []  # ids passed to collection.remove()
        self.prefilters: List[Any] = []  # prefilter objects handed to VectorQuery
        self.searches: List[tuple] = []  # (index, request) handed to scope.search


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
        self._rec.queries.append((n1ql, _named_params(options)))
        return _QueryResult(self._rec.query_rows)

    def search(self, index, request, options=None):
        self._rec.searches.append((index, request))
        return _QueryResult([])


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
def recorder():
    return _Recorder()


@pytest.fixture
def couchbase_db(recorder):
    """A CouchbaseSearch whose Cluster/AsyncCluster and FTS query builders are
    patched so nothing connects."""
    collection = _FakeCollection(recorder)
    scope = _FakeScope(recorder, collection)
    cluster = _FakeCluster(_FakeBucket(scope))

    async_scope = _FakeAsyncScope(recorder, collection)
    async_cluster = _FakeAsyncCluster(_FakeAsyncBucket(async_scope))

    fake_async_cls = MagicMock()

    async def _connect(conn, opts):
        return async_cluster

    fake_async_cls.connect = _connect

    def _capture_vector_query(**kwargs):
        recorder.prefilters.append(kwargs.get("prefilter"))
        return MagicMock()

    with (
        patch(MOD + "Cluster", return_value=cluster),
        patch(MOD + "AsyncCluster", fake_async_cls),
        patch(MOD + "VectorQuery", side_effect=_capture_vector_query),
        patch(MOD + "VectorSearch"),
        patch(MOD + "SearchRequest"),
    ):
        yield _make_db()


class TestOwnerPersistedOnWrite:
    """``user_id`` is a top-level document field (NOT nested in the filters
    blob); ``None`` maps to the shared sentinel."""

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

    def test_upsert_body_carries_owner(self, couchbase_db, recorder):
        couchbase_db.upsert(content_hash="h1", documents=[_embedded("d", "secret content")], user_id="alice")
        body = next(iter(recorder.upserted[0].values()))
        assert body[CouchbaseSearch.USER_ID_FIELD] == "alice"

    def test_upsert_body_none_is_shared_sentinel(self, couchbase_db, recorder):
        couchbase_db.upsert(content_hash="h1", documents=[_embedded("d", "shared content")], user_id=None)
        body = next(iter(recorder.upserted[0].values()))
        assert body[CouchbaseSearch.USER_ID_FIELD] == CouchbaseSearch.SHARED_USER_ID


class TestOwnerFoldedIntoKey:
    """Byte-identical content for different owners yields distinct KV keys so
    one owner's write can't clobber another's; the shared bucket keeps the
    legacy id."""

    def test_prepare_doc_folds_owner_into_id(self):
        db = _make_db()
        alice_id = db.prepare_doc("h", _embedded("d", "same content"), user_id="alice")["_id"]
        bob_id = db.prepare_doc("h", _embedded("d", "same content"), user_id="bob")["_id"]
        shared_id = db.prepare_doc("h", _embedded("d", "same content"), user_id=None)["_id"]
        assert alice_id != bob_id
        assert alice_id != shared_id
        assert bob_id != shared_id

    def test_upsert_keys_distinct_per_owner(self, couchbase_db, recorder):
        couchbase_db.upsert(content_hash="h", documents=[_embedded("d", "same content")], user_id="alice")
        alice_key = next(iter(recorder.upserted[-1].keys()))
        couchbase_db.upsert(content_hash="h", documents=[_embedded("d", "same content")], user_id="bob")
        bob_key = next(iter(recorder.upserted[-1].keys()))
        couchbase_db.upsert(content_hash="h", documents=[_embedded("d", "same content")], user_id=None)
        shared_key = next(iter(recorder.upserted[-1].keys()))
        assert len({alice_key, bob_key, shared_key}) == 3


class TestReadScope:
    """A scoped search restricts to the caller's own chunks OR the
    ``__shared__`` bucket, and never another user's; admin (None) applies no
    scope. The prefilter the adapter feeds the FTS vector query IS the
    read-scope contract."""

    def test_user_scope_query_is_own_or_shared(self):
        db = _make_db()
        q = db._user_scope_query("alice")
        terms = {(d["field"], d["term"]) for d in q.encodable["disjuncts"]}
        assert terms == {("user_id", "alice"), ("user_id", "__shared__")}
        assert ("user_id", "bob") not in terms

    def test_admin_scope_query_is_none(self):
        assert _make_db()._user_scope_query(None) is None

    def test_search_feeds_own_or_shared_prefilter(self, couchbase_db, recorder):
        couchbase_db.search(query="q", user_id="alice")
        prefilter = recorder.prefilters[-1]
        assert prefilter is not None
        terms = {(d["field"], d["term"]) for d in prefilter.encodable["disjuncts"]}
        assert terms == {("user_id", "alice"), ("user_id", "__shared__")}

    def test_admin_search_has_no_prefilter(self, couchbase_db, recorder):
        couchbase_db.search(query="q", user_id=None)
        assert recorder.prefilters[-1] is None

    async def test_async_search_feeds_own_or_shared_prefilter(self, couchbase_db, recorder):
        await couchbase_db.async_search(query="q", user_id="alice")
        prefilter = recorder.prefilters[-1]
        assert prefilter is not None
        terms = {(d["field"], d["term"]) for d in prefilter.encodable["disjuncts"]}
        assert terms == {("user_id", "alice"), ("user_id", "__shared__")}

    async def test_async_admin_search_has_no_prefilter(self, couchbase_db, recorder):
        await couchbase_db.async_search(query="q", user_id=None)
        assert recorder.prefilters[-1] is None


class TestContentHashDedupScope:
    """The per-user dedup path keys on ``content_hash`` bound to the owner. A
    scoped delete touches only that owner's rows; ``None`` binds the
    ``__shared__`` sentinel (never every owner's rows)."""

    def test_delete_by_content_hash_binds_owner(self, couchbase_db, recorder):
        couchbase_db._delete_by_content_hash("h1", user_id="alice")
        n1ql, params = recorder.queries[-1]
        assert "content_hash = $content_hash AND user_id = $user_id" in n1ql
        assert params == {"content_hash": "h1", "user_id": "alice"}

    def test_delete_by_content_hash_none_binds_shared_sentinel(self, couchbase_db, recorder):
        """None must NOT clear every owner's row — it binds the __shared__
        sentinel, so only the shared bucket's stale chunk is removed."""
        couchbase_db._delete_by_content_hash("h1", user_id=None)
        n1ql, params = recorder.queries[-1]
        assert "content_hash = $content_hash AND user_id = $user_id" in n1ql
        assert params == {"content_hash": "h1", "user_id": CouchbaseSearch.SHARED_USER_ID}

    def test_content_hash_exists_scoped_to_owner(self, couchbase_db, recorder):
        couchbase_db.content_hash_exists("h1", user_id="alice")
        n1ql, params = recorder.queries[-1]
        assert "content_hash = $content_hash AND user_id = $user_id" in n1ql
        assert params == {"content_hash": "h1", "user_id": "alice"}

    def test_content_hash_exists_none_binds_shared_sentinel(self, couchbase_db, recorder):
        """The regression. ``None`` used to drop the owner predicate entirely and
        match any owner, so a hash alice privately held read as a duplicate and a
        later shared publish under ``skip_if_exists`` was swallowed. It binds the
        ``__shared__`` sentinel now — the same bucket ``_delete_by_content_hash``
        clears for ``None``, which is the other half of this pair."""
        couchbase_db.content_hash_exists("h1", user_id=None)
        n1ql, params = recorder.queries[-1]
        assert "content_hash = $content_hash AND user_id = $user_id" in n1ql
        assert params == {"content_hash": "h1", "user_id": CouchbaseSearch.SHARED_USER_ID}

    def test_the_bound_predicate_cannot_match_a_private_row(self, couchbase_db, recorder):
        """The behaviour behind the shape, evaluated against the body alice's
        write really stored: the content_hash arm matches, the owner arm does
        not, so the gate answers False and the shared publish goes ahead."""
        couchbase_db.insert(content_hash="h1", documents=[_embedded("d", "secret")], user_id="alice")
        alice_row = next(iter(recorder.inserted[-1].values()))

        couchbase_db.content_hash_exists("h1", user_id=None)
        _, params = recorder.queries[-1]

        assert alice_row["content_hash"] == params["content_hash"]
        assert alice_row[CouchbaseSearch.USER_ID_FIELD] != params["user_id"]

    def test_upsert_dedup_delete_scoped_to_writing_owner(self, couchbase_db, recorder):
        """When the writer's own chunk already exists, the pre-delete binds
        that owner only, so another owner's identical-content row is left
        intact."""
        recorder.query_rows = [{"doc_id": "stale-1"}]  # content_hash_exists -> True
        couchbase_db.upsert(content_hash="h1", documents=[_embedded("d", "same content")], user_id="bob")
        dedup_n1ql, dedup_params = recorder.queries[0]
        assert dedup_params == {"content_hash": "h1", "user_id": "bob"}
        # And only the row that scoped query returned is removed.
        assert recorder.removed == ["stale-1"]


class TestDeleteByContentIdScope:
    """``delete_by_content_id(content_id, user_id=...)`` scopes the delete to
    the caller's rows so Bob can't wipe Alice's chunks by guessing her
    content_id. Admin (None) spans all owners."""

    def test_scoped_delete_ands_owner(self, couchbase_db, recorder):
        recorder.query_rows = [{"doc_id": "d-alice"}]
        couchbase_db.delete_by_content_id("cid-1", user_id="alice")
        n1ql, params = recorder.queries[-1]
        assert "AND user_id = $user_id" in n1ql
        assert params == {"content_id": "cid-1", "user_id": "alice"}
        # Removes only what the owner-scoped query returned.
        assert recorder.removed == ["d-alice"]

    def test_unscoped_delete_spans_all_owners(self, couchbase_db, recorder):
        couchbase_db.delete_by_content_id("cid-1", user_id=None)
        n1ql, params = recorder.queries[-1]
        assert "user_id" not in n1ql
        assert params == {"content_id": "cid-1"}


class TestInsertPersistsOwner:
    """``insert`` stamps the owner into the body handed to
    ``collection.insert_multi`` exactly like ``upsert``."""

    def test_insert_body_carries_owner(self, couchbase_db, recorder):
        couchbase_db.insert(content_hash="h1", documents=[_embedded("d", "secret")], user_id="alice")
        body = next(iter(recorder.inserted[0].values()))
        assert body[CouchbaseSearch.USER_ID_FIELD] == "alice"

    def test_insert_body_none_is_shared_sentinel(self, couchbase_db, recorder):
        couchbase_db.insert(content_hash="h1", documents=[_embedded("d", "shared")], user_id=None)
        body = next(iter(recorder.inserted[0].values()))
        assert body[CouchbaseSearch.USER_ID_FIELD] == CouchbaseSearch.SHARED_USER_ID
