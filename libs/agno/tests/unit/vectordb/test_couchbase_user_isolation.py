"""Couchbase per-user RAG isolation, against a faked cluster."""

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from couchbase.options import ClusterOptions

from agno.knowledge.document import Document
from agno.vectordb.couchbase.couchbase import CouchbaseSearch

from .conftest import DeterministicEmbedder

MOD = "agno.vectordb.couchbase.couchbase."

BUCKET = "iso_bucket"
SCOPE = "iso_scope"
COLLECTION = "iso_collection"
INDEX = "iso_index"
DIMS = 8


def _embedded(name: str, content: str, **kwargs) -> Document:
    """Create a Document with a precomputed embedding"""
    doc = Document(name=name, content=content, **kwargs)
    doc.embedding = DeterministicEmbedder(dimensions=DIMS).get_embedding(content)
    return doc


def _named_params(options) -> Dict[str, Any]:
    # QueryOptions is a plain dict subclass, so named_parameters reads directly.
    return dict(options).get("named_parameters", {}) if options is not None else {}


class _Recorder:
    """Sink for everything the adapter sends at the faked cluster"""

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
        embedder=DeterministicEmbedder(dimensions=DIMS),
    )
    params.update(overrides)
    return CouchbaseSearch(**params)


@pytest.fixture
def couchbase_db():
    """Fixture to create a CouchbaseSearch with a faked cluster - the sink is on ``.recorder``"""
    recorder = _Recorder()
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
        db = _make_db()
        db.recorder = recorder
        yield db


class TestWriteStampsOwner:
    """``user_id`` is a top-level document field, not nested in filters; ``None`` maps to the shared sentinel"""

    def test_explicit_owner_stamped_top_level(self):
        prepared = _make_db().prepare_doc("h1", _embedded("d", "secret content"), user_id="alice")
        assert prepared[CouchbaseSearch.USER_ID_FIELD] == "alice"
        assert "filters" not in prepared

    def test_none_stores_shared_sentinel(self):
        prepared = _make_db().prepare_doc("h1", _embedded("d", "shared content"), user_id=None)
        assert prepared[CouchbaseSearch.USER_ID_FIELD] == CouchbaseSearch.SHARED_USER_ID

    def test_upsert_body_carries_owner(self, couchbase_db):
        couchbase_db.upsert(content_hash="h1", documents=[_embedded("d", "secret content")], user_id="alice")
        body = next(iter(couchbase_db.recorder.upserted[0].values()))
        assert body[CouchbaseSearch.USER_ID_FIELD] == "alice"

    def test_upsert_body_none_is_shared_sentinel(self, couchbase_db):
        couchbase_db.upsert(content_hash="h1", documents=[_embedded("d", "shared content")], user_id=None)
        body = next(iter(couchbase_db.recorder.upserted[0].values()))
        assert body[CouchbaseSearch.USER_ID_FIELD] == CouchbaseSearch.SHARED_USER_ID

    def test_insert_body_carries_owner(self, couchbase_db):
        couchbase_db.insert(content_hash="h1", documents=[_embedded("d", "secret")], user_id="alice")
        body = next(iter(couchbase_db.recorder.inserted[0].values()))
        assert body[CouchbaseSearch.USER_ID_FIELD] == "alice"

    def test_insert_body_none_is_shared_sentinel(self, couchbase_db):
        couchbase_db.insert(content_hash="h1", documents=[_embedded("d", "shared")], user_id=None)
        body = next(iter(couchbase_db.recorder.inserted[0].values()))
        assert body[CouchbaseSearch.USER_ID_FIELD] == CouchbaseSearch.SHARED_USER_ID


class TestOwnerFoldedId:
    """The owner is folded into the KV key, so identical content for two owners lands on distinct keys"""

    def test_prepare_doc_folds_owner_into_id(self):
        db = _make_db()
        alice_id = db.prepare_doc("h", _embedded("d", "same content"), user_id="alice")["_id"]
        bob_id = db.prepare_doc("h", _embedded("d", "same content"), user_id="bob")["_id"]
        shared_id = db.prepare_doc("h", _embedded("d", "same content"), user_id=None)["_id"]
        assert alice_id != bob_id
        assert alice_id != shared_id
        assert bob_id != shared_id

    def test_upsert_keys_distinct_per_owner(self, couchbase_db):
        couchbase_db.upsert(content_hash="h", documents=[_embedded("d", "same content")], user_id="alice")
        alice_key = next(iter(couchbase_db.recorder.upserted[-1].keys()))
        couchbase_db.upsert(content_hash="h", documents=[_embedded("d", "same content")], user_id="bob")
        bob_key = next(iter(couchbase_db.recorder.upserted[-1].keys()))
        couchbase_db.upsert(content_hash="h", documents=[_embedded("d", "same content")], user_id=None)
        shared_key = next(iter(couchbase_db.recorder.upserted[-1].keys()))
        assert len({alice_key, bob_key, shared_key}) == 3


class TestSearchScope:
    """A scoped search matches the caller's own chunks or ``__shared__``; ``None`` applies no scope"""

    def test_user_scope_query_is_own_or_shared(self):
        db = _make_db()
        q = db._user_scope_query("alice")
        terms = {(d["field"], d["term"]) for d in q.encodable["disjuncts"]}
        assert terms == {("user_id", "alice"), ("user_id", "__shared__")}
        assert ("user_id", "bob") not in terms

    def test_admin_scope_query_is_none(self):
        assert _make_db()._user_scope_query(None) is None

    def test_search_feeds_own_or_shared_prefilter(self, couchbase_db):
        couchbase_db.search(query="q", user_id="alice")
        prefilter = couchbase_db.recorder.prefilters[-1]
        assert prefilter is not None
        terms = {(d["field"], d["term"]) for d in prefilter.encodable["disjuncts"]}
        assert terms == {("user_id", "alice"), ("user_id", "__shared__")}

    def test_admin_search_has_no_prefilter(self, couchbase_db):
        couchbase_db.search(query="q", user_id=None)
        assert couchbase_db.recorder.prefilters[-1] is None

    @pytest.mark.asyncio
    async def test_async_search_feeds_own_or_shared_prefilter(self, couchbase_db):
        await couchbase_db.async_search(query="q", user_id="alice")
        prefilter = couchbase_db.recorder.prefilters[-1]
        assert prefilter is not None
        terms = {(d["field"], d["term"]) for d in prefilter.encodable["disjuncts"]}
        assert terms == {("user_id", "alice"), ("user_id", "__shared__")}

    @pytest.mark.asyncio
    async def test_async_admin_search_has_no_prefilter(self, couchbase_db):
        await couchbase_db.async_search(query="q", user_id=None)
        assert couchbase_db.recorder.prefilters[-1] is None

    def test_caller_filters_do_not_replace_the_owner_scope(self, couchbase_db):
        """Test that caller-supplied filters do not suppress the owner scope"""
        couchbase_db.search(query="q", filters={"dept": "eng"}, user_id="alice")
        prefilter = couchbase_db.recorder.prefilters[-1]
        assert prefilter is not None, "filters must not suppress the owner scope"
        assert "alice" in str(prefilter.encodable)

    @pytest.mark.asyncio
    async def test_async_caller_filters_do_not_replace_the_owner_scope(self, couchbase_db):
        await couchbase_db.async_search(query="q", filters={"dept": "eng"}, user_id="alice")
        prefilter = couchbase_db.recorder.prefilters[-1]
        assert prefilter is not None, "filters must not suppress the owner scope"
        assert "alice" in str(prefilter.encodable)


class TestSentinelImpersonation:
    """``__shared__`` is an ordinary field value a caller could pass, so every scoped entry point refuses it"""

    @pytest.mark.parametrize(
        "call",
        [
            lambda db: db.insert("h", [_embedded("a", "alice content")], user_id=CouchbaseSearch.SHARED_USER_ID),
            lambda db: db.upsert("h", [_embedded("a", "alice content")], user_id=CouchbaseSearch.SHARED_USER_ID),
            lambda db: db.search(query="q", user_id=CouchbaseSearch.SHARED_USER_ID),
            lambda db: db.content_hash_exists("h", user_id=CouchbaseSearch.SHARED_USER_ID),
            lambda db: db.delete_by_content_id("cid", user_id=CouchbaseSearch.SHARED_USER_ID),
        ],
        ids=["insert", "upsert", "search", "content_hash_exists", "delete_by_content_id"],
    )
    def test_every_scoped_entry_point_rejects(self, couchbase_db, call):
        with pytest.raises(ValueError, match="reserved to mark content shared"):
            call(couchbase_db)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "call",
        [
            lambda db: db.async_insert("h", [_embedded("a", "alice content")], user_id=CouchbaseSearch.SHARED_USER_ID),
            lambda db: db.async_upsert("h", [_embedded("a", "alice content")], user_id=CouchbaseSearch.SHARED_USER_ID),
            lambda db: db.async_search(query="q", user_id=CouchbaseSearch.SHARED_USER_ID),
        ],
        ids=["async_insert", "async_upsert", "async_search"],
    )
    async def test_every_async_entry_point_rejects(self, couchbase_db, call):
        with pytest.raises(ValueError, match="reserved to mark content shared"):
            await call(couchbase_db)

    def test_none_is_not_rejected(self, couchbase_db):
        """``None`` still reaches the shared bucket - only the literal sentinel is refused"""
        couchbase_db.insert("h", [_embedded("s", "shared content")], user_id=None)
        assert couchbase_db.recorder.inserted, "a shared write must still go through"


class TestDedupScope:
    """The dedup path keys on ``content_hash`` bound to the owner"""

    def test_delete_by_content_hash_binds_owner(self, couchbase_db):
        couchbase_db._delete_by_content_hash("h1", user_id="alice")
        n1ql, params = couchbase_db.recorder.queries[-1]
        assert "content_hash = $content_hash AND user_id = $user_id" in n1ql
        assert params == {"content_hash": "h1", "user_id": "alice"}

    def test_delete_by_content_hash_none_binds_shared_sentinel(self, couchbase_db):
        """``None`` binds the ``__shared__`` sentinel instead of clearing every owner's row"""
        couchbase_db._delete_by_content_hash("h1", user_id=None)
        n1ql, params = couchbase_db.recorder.queries[-1]
        assert "content_hash = $content_hash AND user_id = $user_id" in n1ql
        assert params == {"content_hash": "h1", "user_id": CouchbaseSearch.SHARED_USER_ID}

    def test_content_hash_exists_scoped_to_owner(self, couchbase_db):
        couchbase_db.content_hash_exists("h1", user_id="alice")
        n1ql, params = couchbase_db.recorder.queries[-1]
        assert "content_hash = $content_hash AND user_id = $user_id" in n1ql
        assert params == {"content_hash": "h1", "user_id": "alice"}

    def test_content_hash_exists_none_binds_shared_sentinel(self, couchbase_db):
        couchbase_db.content_hash_exists("h1", user_id=None)
        n1ql, params = couchbase_db.recorder.queries[-1]
        assert "content_hash = $content_hash AND user_id = $user_id" in n1ql
        assert params == {"content_hash": "h1", "user_id": CouchbaseSearch.SHARED_USER_ID}

    def test_the_bound_predicate_cannot_match_a_private_row(self, couchbase_db):
        """Test that the bound predicate cannot match alice's row - the hash arm matches, the owner arm does not"""
        couchbase_db.insert(content_hash="h1", documents=[_embedded("d", "secret")], user_id="alice")
        alice_row = next(iter(couchbase_db.recorder.inserted[-1].values()))

        couchbase_db.content_hash_exists("h1", user_id=None)
        _, params = couchbase_db.recorder.queries[-1]

        assert alice_row["content_hash"] == params["content_hash"]
        assert alice_row[CouchbaseSearch.USER_ID_FIELD] != params["user_id"]

    def test_upsert_dedup_delete_scoped_to_writing_owner(self, couchbase_db):
        """Test that the dedup pre-delete binds the writing owner only"""
        couchbase_db.recorder.query_rows = [{"doc_id": "stale-1"}]  # content_hash_exists -> True
        couchbase_db.upsert(content_hash="h1", documents=[_embedded("d", "same content")], user_id="bob")
        dedup_n1ql, dedup_params = couchbase_db.recorder.queries[0]
        assert dedup_params == {"content_hash": "h1", "user_id": "bob"}
        assert couchbase_db.recorder.removed == ["stale-1"]


class TestDeleteScope:
    """``delete_by_content_id`` scopes the delete to the caller's own rows"""

    def test_scoped_delete_ands_owner(self, couchbase_db):
        couchbase_db.recorder.query_rows = [{"doc_id": "d-alice"}]
        couchbase_db.delete_by_content_id("cid-1", user_id="alice")
        n1ql, params = couchbase_db.recorder.queries[-1]
        assert "AND user_id = $user_id" in n1ql
        assert params == {"content_id": "cid-1", "user_id": "alice"}
        assert couchbase_db.recorder.removed == ["d-alice"]

    def test_unscoped_delete_spans_all_owners(self, couchbase_db):
        couchbase_db.delete_by_content_id("cid-1", user_id=None)
        n1ql, params = couchbase_db.recorder.queries[-1]
        assert "user_id" not in n1ql
        assert params == {"content_id": "cid-1"}


def _keyword_field(analyzer="keyword"):
    return {"user_id": {"fields": [{"name": "user_id", "index": True, "type": "text", "analyzer": analyzer}]}}


class TestFtsMappingHonoursTheScopeFilter:
    """The scope filter is a TermQuery, so ``user_id`` has to be indexed as a whole value.

    The index definition is supplied by the user, so it may index the owner with the default
    analyzer — which splits it into word pieces and makes a search scoped to "123" match
    "team-123"'s chunks. Presence of the field is therefore not enough to accept it.
    """

    @pytest.mark.parametrize(
        "mapping,expected",
        [
            ({"types": {"s.c": {"properties": _keyword_field()}}}, True),
            ({"properties": _keyword_field()}, True),
            ({"default_mapping": {"properties": _keyword_field()}}, True),
            # Declared, but analyzed — a TermQuery would match this owner's tokens
            ({"types": {"s.c": {"properties": _keyword_field(analyzer="standard")}}}, False),
            # Declared with no analyzer at all, so the index default applies
            ({"types": {"s.c": {"properties": {"user_id": {"fields": [{"name": "user_id"}]}}}}}, False),
            # A dynamic mapping declares nothing; its values are analyzed
            ({"default_mapping": {"dynamic": True, "enabled": True}, "index_dynamic": True}, False),
            ({"types": {"s.c": {"properties": {"content": {"fields": []}}}}}, False),
        ],
    )
    def test_only_a_keyword_analyzer_is_accepted(self, couchbase_db, mapping, expected):
        index_def = MagicMock()
        index_def.params = {"mapping": mapping}
        manager = MagicMock()
        manager.get_index.return_value = index_def

        with patch.object(type(couchbase_db), "scope", property(lambda _: MagicMock(search_indexes=lambda: manager))):
            assert couchbase_db._fts_has_user_id_field() is expected

    def test_an_analyzed_owner_field_refuses_a_scoped_call(self, couchbase_db):
        index_def = MagicMock()
        index_def.params = {"mapping": {"types": {"s.c": {"properties": _keyword_field(analyzer="standard")}}}}
        manager = MagicMock()
        manager.get_index.return_value = index_def
        couchbase_db._owner_field_exists = None

        with patch.object(type(couchbase_db), "scope", property(lambda _: MagicMock(search_indexes=lambda: manager))):
            with pytest.raises(ValueError, match="does not"):
                couchbase_db._require_owner_field("123")
