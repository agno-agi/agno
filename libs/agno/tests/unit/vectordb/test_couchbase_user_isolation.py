import base64
import json
import os
import time
import urllib.error
import urllib.request
from datetime import timedelta
from typing import List, Optional

import pytest

pytest.importorskip("couchbase")

from couchbase.auth import PasswordAuthenticator  # noqa: E402
from couchbase.management.search import SearchIndex  # noqa: E402
from couchbase.options import ClusterOptions, KnownConfigProfiles  # noqa: E402
from couchbase.search import ConjunctionQuery, DisjunctionQuery, TermQuery  # noqa: E402

from agno.knowledge.document import Document  # noqa: E402
from agno.vectordb.couchbase.couchbase import CouchbaseSearch  # noqa: E402

# --- Live cluster connection parameters -----------------------------------
CB_HOST = os.getenv("COUCHBASE_HOST", "localhost")
CB_USER = os.getenv("COUCHBASE_USER", "Administrator")
CB_PASS = os.getenv("COUCHBASE_PASSWORD", "password123")
CB_CONN = os.getenv("COUCHBASE_CONNECTION_STRING", f"couchbase://{CB_HOST}")
CB_MGMT = f"http://{CB_HOST}:8091"
CB_FTS = f"http://{CB_HOST}:8094"

BUCKET = "iso_bucket"
SCOPE = "iso_scope"
COLLECTION = "iso_collection"
INDEX = "iso_index"
DIMS = 8


class _DeterministicEmbedder:
    """Hash-based embedder — no network, no API key. Content steers the vector
    so distinct documents land in distinct buckets, and it exposes a real async
    surface for the async insert/search paths."""

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


def _embedded(name: str, content: str) -> Document:
    """A Document with a precomputed deterministic embedding so direct
    ``insert`` calls work without an embedder round-trip."""
    doc = Document(name=name, content=content)
    doc.embedding = _DeterministicEmbedder().get_embedding(content)
    return doc


def _make_db(**overrides) -> CouchbaseSearch:
    """Construct a CouchbaseSearch with the deterministic embedder. Used by both
    the static (no .create()) and live tests."""
    params = dict(
        bucket_name=BUCKET,
        scope_name=SCOPE,
        collection_name=COLLECTION,
        couchbase_connection_string=CB_CONN,
        cluster_options=ClusterOptions(PasswordAuthenticator(CB_USER, CB_PASS)),
        search_index=INDEX,
        embedder=_DeterministicEmbedder(),
    )
    params.update(overrides)
    return CouchbaseSearch(**params)


# ===========================================================================
# STATIC tests — no server required. Pin the contract with the cluster mocked.
# ===========================================================================


class TestSignaturesAcceptUserId:
    """Knowledge passes ``user_id`` to every scoped method; missing it would
    raise TypeError at call time."""

    def test_scoped_methods_accept_user_id(self):
        import inspect

        for name in (
            "insert",
            "async_insert",
            "upsert",
            "async_upsert",
            "search",
            "async_search",
            "delete_by_content_id",
        ):
            sig = inspect.signature(getattr(CouchbaseSearch, name))
            assert "user_id" in sig.parameters, f"{name} is missing user_id"
            # user_id must be the LAST parameter.
            assert list(sig.parameters)[-1] == "user_id", f"{name}: user_id must be last"


class TestDocFieldAndIdFolding:
    """``user_id`` is a top-level document field, and the document key folds in
    the owner for scoped rows while keeping the legacy key for shared rows."""

    def test_constants(self):
        assert CouchbaseSearch.USER_ID_FIELD == "user_id"
        assert CouchbaseSearch.SHARED_USER_ID == "__shared__"

    def test_prepare_doc_stamps_owner_top_level(self):
        db = _make_db()
        doc = _embedded("d", "secret content")
        prepared = db.prepare_doc("h1", doc, user_id="alice")
        assert prepared[CouchbaseSearch.USER_ID_FIELD] == "alice"
        # Owner is a first-class field, NOT inside the filters blob.
        assert "filters" not in prepared

    def test_prepare_doc_none_stores_shared_sentinel(self):
        db = _make_db()
        prepared = db.prepare_doc("h1", _embedded("d", "shared content"), user_id=None)
        assert prepared[CouchbaseSearch.USER_ID_FIELD] == CouchbaseSearch.SHARED_USER_ID

    def test_id_folds_in_user_for_scoped_rows(self):
        from hashlib import md5

        db = _make_db()
        content = "identical content"
        legacy = md5(content.encode("utf-8")).hexdigest()
        # Shared rows keep the legacy content-only id.
        assert db._doc_id(content, None) == legacy
        # Scoped rows fold in the owner, and two owners get distinct ids.
        assert db._doc_id(content, "alice") != legacy
        assert db._doc_id(content, "alice") != db._doc_id(content, "bob")

    def test_two_users_same_content_get_distinct_doc_ids(self):
        """The clobber regression at the id level: same content + same hash for
        two users must produce two different document keys."""
        db = _make_db()
        a = db.prepare_doc("SAME", _embedded("s", "The secret is 42."), user_id="alice")
        b = db.prepare_doc("SAME", _embedded("s", "The secret is 42."), user_id="bob")
        assert a["_id"] != b["_id"]


class TestScopeQueryBuilder:
    """The own-OR-shared scope builder is small enough to unit-test directly."""

    def test_none_returns_no_scope(self):
        db = _make_db()
        assert db._user_scope_query(None) is None

    def test_alice_scope_is_own_or_shared_disjunction(self):
        db = _make_db()
        q = db._user_scope_query("alice")
        assert isinstance(q, DisjunctionQuery)
        encoded = q.encodable
        terms = {d["term"] for d in encoded["disjuncts"]}
        assert terms == {"alice", CouchbaseSearch.SHARED_USER_ID}
        assert all(d["field"] == "user_id" for d in encoded["disjuncts"])

    def test_prefilter_none_when_admin_and_no_filters(self):
        db = _make_db()
        assert db._build_vector_prefilter(None, None) is None

    def test_prefilter_is_scope_only_when_no_filters(self):
        db = _make_db()
        pf = db._build_vector_prefilter(None, "alice")
        assert isinstance(pf, DisjunctionQuery)

    def test_prefilter_ands_filters_with_scope(self):
        db = _make_db()
        pf = db._build_vector_prefilter({"category": "x"}, "alice")
        # filters AND scope -> conjunction of [filter, scope].
        assert isinstance(pf, ConjunctionQuery)
        encoded = pf.encodable
        assert "conjuncts" in encoded
        assert len(encoded["conjuncts"]) == 2

    def test_prefilter_filters_only_when_admin(self):
        db = _make_db()
        pf = db._build_vector_prefilter({"category": "x"}, None)
        assert isinstance(pf, TermQuery)
        assert pf.encodable == {"field": "filters.category", "term": "x"}


class TestSearchRequestBuildsPrefilter:
    """The load-bearing static assertion: the SearchRequest's vector query
    carries the own-OR-shared scope as a PRE-filter."""

    def test_scoped_search_request_has_prefilter(self):
        db = _make_db()
        req = db._build_search_request([0.1] * DIMS, 5, None, "alice")
        vq = req.vector_search.queries[0]
        assert vq.prefilter is not None
        terms = {d["term"] for d in vq.prefilter.encodable["disjuncts"]}
        assert terms == {"alice", CouchbaseSearch.SHARED_USER_ID}

    def test_admin_search_request_has_no_prefilter(self):
        db = _make_db()
        req = db._build_search_request([0.1] * DIMS, 5, None, None)
        assert req.vector_search.queries[0].prefilter is None


class TestIndexUserIdWarning:
    """A user-supplied FTS index that omits ``user_id`` makes the scope prefilter
    match nothing, so scoped searches return empty. The adapter must warn rather
    than fail silently — but only when it's confident the field is missing."""

    def test_string_index_name_does_not_warn(self):
        # A bare index name can't be introspected; assume it's set up correctly.
        db = _make_db(search_index=INDEX)
        assert db._definition_indexes_user_id() is True

    def test_definition_indexing_user_id_does_not_warn(self):
        db = _make_db(search_index=_search_index_def())
        assert db._definition_indexes_user_id() is True

    def test_dynamic_default_mapping_does_not_warn(self):
        idx = SearchIndex(
            name=INDEX,
            source_name=BUCKET,
            params={"mapping": {"default_mapping": {"dynamic": True, "enabled": True}}},
        )
        db = _make_db(search_index=idx)
        assert db._definition_indexes_user_id() is True

    def test_dynamic_type_mapping_does_not_warn(self):
        idx = SearchIndex(
            name=INDEX,
            source_name=BUCKET,
            params={"mapping": {"types": {f"{SCOPE}.{COLLECTION}": {"dynamic": True, "enabled": True}}}},
        )
        db = _make_db(search_index=idx)
        assert db._definition_indexes_user_id() is True

    def test_non_dynamic_index_missing_user_id_warns(self):
        idx = SearchIndex(
            name=INDEX,
            source_name=BUCKET,
            params={
                "mapping": {
                    "default_mapping": {"dynamic": False, "enabled": False},
                    "types": {
                        f"{SCOPE}.{COLLECTION}": {
                            "dynamic": False,
                            "enabled": True,
                            "properties": {"content": {"enabled": True}, "embedding": {"enabled": True}},
                        }
                    },
                }
            },
        )
        db = _make_db(search_index=idx)
        assert db._definition_indexes_user_id() is False


class TestUpdateMetadataOwnershipGuard:
    """``update_metadata`` must not let caller metadata flip a chunk's owner."""

    def test_user_id_is_stripped_from_metadata(self):
        from unittest.mock import MagicMock

        db = _make_db()
        # Mock the read so update_metadata finds one matching chunk owned by alice,
        # then capture the doc the adapter actually upserts back to the collection.
        db._cluster = MagicMock()
        db._cluster.query.return_value = iter(
            [{"doc_id": "doc-1", "meta_data": {"tag": "old"}, "filters": {"tag": "old"}}]
        )

        captured = {}

        def fake_upsert(doc_id, doc_content):
            captured["doc_content"] = doc_content
            return MagicMock()

        collection = MagicMock()
        fetched = MagicMock()
        fetched.content_as = {dict: {"user_id": "alice", "meta_data": {"tag": "old"}, "filters": {"tag": "old"}}}
        collection.get.return_value = fetched
        collection.upsert.side_effect = fake_upsert
        db._collection = collection

        db.update_metadata("cid-1", {"user_id": "bob", "tag": "x"})

        # The adapter must strip the caller's user_id before merging — neither the
        # merged meta_data nor filters the adapter writes may carry user_id, so a
        # caller can't reassign the chunk's owner.
        written = captured["doc_content"]
        assert CouchbaseSearch.USER_ID_FIELD not in written["meta_data"]
        assert CouchbaseSearch.USER_ID_FIELD not in written["filters"]
        assert written["meta_data"]["tag"] == "x"


class TestDeleteAndDedupeScopingSql:
    """The scoped delete / dedupe SQL must AND the owner in. We assert on the
    generated N1QL with the scope query mocked."""

    def _capture_query(self, db):
        from unittest.mock import MagicMock

        captured = {}

        def fake_query(query, options=None):
            captured["query"] = query
            result = MagicMock()
            result.rows.return_value = []
            return result

        scope = MagicMock()
        scope.query.side_effect = fake_query
        db._scope = scope
        return captured

    def test_delete_by_content_id_scoped_ands_owner(self):
        db = _make_db()
        cap = self._capture_query(db)
        db.delete_by_content_id("cid-1", user_id="alice")
        assert "user_id = $user_id" in cap["query"]

    def test_delete_by_content_id_unscoped_has_no_owner_clause(self):
        db = _make_db()
        cap = self._capture_query(db)
        db.delete_by_content_id("cid-1", user_id=None)
        assert "user_id" not in cap["query"]

    def test_delete_by_content_hash_scoped_ands_owner(self):
        db = _make_db()
        cap = self._capture_query(db)
        db._delete_by_content_hash("h1", user_id="alice")
        assert "user_id = $user_id" in cap["query"]

    def test_content_hash_exists_scoped_ands_owner(self):
        db = _make_db()
        cap = self._capture_query(db)
        db.content_hash_exists("h1", user_id="alice")
        assert "user_id = $user_id" in cap["query"]

    def test_content_hash_exists_unscoped_has_no_owner_clause(self):
        db = _make_db()
        cap = self._capture_query(db)
        db.content_hash_exists("h1", user_id=None)
        assert "user_id" not in cap["query"]

    def test_shared_dedupe_binds_shared_sentinel_not_every_owner(self):
        """A shared/admin re-ingest (``user_id=None``) dedupe-delete must bind the
        ``__shared__`` sentinel so it clears only the shared bucket — pre-fix the
        None case had no owner clause and wiped every scoped owner sharing the
        content_hash. The delete remains owner-scoped; only the BOUND value
        changes for the shared bucket."""
        from unittest.mock import MagicMock

        captured = {}

        def fake_query(query, options=None):
            captured["query"] = query
            # QueryOptions is a dict subclass; the shared sentinel is BOUND under
            # named_parameters, never interpolated into the N1QL.
            captured["params"] = (options or {}).get("named_parameters", {})
            result = MagicMock()
            result.rows.return_value = []
            return result

        scope = MagicMock()
        scope.query.side_effect = fake_query
        db = _make_db()
        db._scope = scope

        db._delete_by_content_hash("h1", user_id=None)
        assert "user_id = $user_id" in captured["query"]
        assert captured["params"].get("user_id") == CouchbaseSearch.SHARED_USER_ID


# ===========================================================================
# LIVE tests — require a reachable Couchbase Enterprise cluster.
# ===========================================================================


def _server_reachable() -> bool:
    try:
        token = base64.b64encode(f"{CB_USER}:{CB_PASS}".encode()).decode()
        req = urllib.request.Request(f"{CB_MGMT}/pools/default", headers={"Authorization": f"Basic {token}"})
        data = json.loads(urllib.request.urlopen(req, timeout=3).read())
        # Vector FTS needs Enterprise.
        pools_req = urllib.request.Request(f"{CB_MGMT}/pools", headers={"Authorization": f"Basic {token}"})
        pools = json.loads(urllib.request.urlopen(pools_req, timeout=3).read())
        return data["nodes"][0]["status"] == "healthy" and pools.get("isEnterprise", False)
    except Exception:
        return False


live = pytest.mark.skipif(not _server_reachable(), reason="Couchbase Enterprise server not reachable on localhost")


def _rest(method: str, url: str, data: Optional[bytes] = None, headers=None):
    token = base64.b64encode(f"{CB_USER}:{CB_PASS}".encode()).decode()
    hdrs = {"Authorization": f"Basic {token}"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        return urllib.request.urlopen(req, timeout=10).read()
    except urllib.error.HTTPError as e:
        return e.read()


def _provision_via_rest():
    """Create scope + collection via REST.

    The couchbase 4.6.x SDK's collection-management calls hit an
    ``UnboundLocalError`` in ``forward_args`` when invoked with no keyword
    options, so we provision the scope/collection over the REST API (which is
    rock-solid) and let the adapter own only the FTS index + data path.
    """
    # Drop a stale collection/index from a previous run so each run is clean.
    _rest("DELETE", f"{CB_FTS}/api/bucket/{BUCKET}/scope/{SCOPE}/index/{INDEX}")
    _rest("DELETE", f"{CB_MGMT}/pools/default/buckets/{BUCKET}/scopes/{SCOPE}/collections/{COLLECTION}")
    time.sleep(1)
    _rest("POST", f"{CB_MGMT}/pools/default/buckets/{BUCKET}/scopes", data=b"name=" + SCOPE.encode())
    _rest(
        "POST",
        f"{CB_MGMT}/pools/default/buckets/{BUCKET}/scopes/{SCOPE}/collections",
        data=b"name=" + COLLECTION.encode(),
    )
    time.sleep(2)


def _search_index_def() -> SearchIndex:
    """Scope-level FTS vector index that indexes content, the ``user_id``
    keyword (the isolation primitive) and the embedding."""
    return SearchIndex(
        name=INDEX,
        source_type="gocbcore",
        idx_type="fulltext-index",
        source_name=BUCKET,
        plan_params={"index_partitions": 1, "num_replicas": 0},
        params={
            "doc_config": {
                "docid_prefix_delim": "",
                "docid_regexp": "",
                "mode": "scope.collection.type_field",
                "type_field": "type",
            },
            "mapping": {
                "default_analyzer": "standard",
                "default_datetime_parser": "dateTimeOptional",
                "index_dynamic": True,
                "store_dynamic": True,
                "default_mapping": {"dynamic": True, "enabled": False},
                "types": {
                    f"{SCOPE}.{COLLECTION}": {
                        "dynamic": False,
                        "enabled": True,
                        "properties": {
                            "content": {
                                "enabled": True,
                                "fields": [
                                    {
                                        "docvalues": True,
                                        "include_in_all": False,
                                        "include_term_vectors": False,
                                        "index": True,
                                        "name": "content",
                                        "store": True,
                                        "type": "text",
                                    }
                                ],
                            },
                            "user_id": {
                                "enabled": True,
                                "fields": [
                                    {
                                        "docvalues": True,
                                        "include_in_all": False,
                                        "include_term_vectors": False,
                                        "index": True,
                                        "name": "user_id",
                                        "store": True,
                                        "analyzer": "keyword",
                                        "type": "text",
                                    }
                                ],
                            },
                            "embedding": {
                                "enabled": True,
                                "dynamic": False,
                                "fields": [
                                    {
                                        "vector_index_optimized_for": "recall",
                                        "docvalues": True,
                                        "dims": DIMS,
                                        "include_in_all": False,
                                        "include_term_vectors": False,
                                        "index": True,
                                        "name": "embedding",
                                        "similarity": "dot_product",
                                        "store": True,
                                        "type": "vector",
                                    }
                                ],
                            },
                        },
                    }
                },
            },
        },
    )


def _cluster_options() -> ClusterOptions:
    opts = ClusterOptions(PasswordAuthenticator(CB_USER, CB_PASS))
    opts.apply_profile(KnownConfigProfiles.WanDevelopment)
    return opts


def _flush_collection():
    """Empty the collection between tests without dropping it (the SDK drop is
    buggy). Uses N1QL DELETE so each test starts from a clean slate."""
    from couchbase.cluster import Cluster
    from couchbase.n1ql import QueryScanConsistency
    from couchbase.options import QueryOptions

    cluster = Cluster(CB_CONN, _cluster_options())
    cluster.wait_until_ready(timedelta(seconds=30))
    scope = cluster.bucket(BUCKET).scope(SCOPE)
    scope.query(
        f"DELETE FROM {COLLECTION}",
        QueryOptions(scan_consistency=QueryScanConsistency.REQUEST_PLUS),
    ).execute()


@pytest.fixture(scope="module")
def live_index():
    """Provision the scope/collection (REST) and the FTS vector index (adapter)
    once for the module."""
    _provision_via_rest()
    db = _make_db(
        search_index=_search_index_def(),
        embedder=_DeterministicEmbedder(),
        wait_until_index_ready=60,
    )
    db._create_fts_index()
    # Give the index a moment to come online.
    time.sleep(2)
    yield
    _rest("DELETE", f"{CB_FTS}/api/bucket/{BUCKET}/scope/{SCOPE}/index/{INDEX}")
    _rest("DELETE", f"{CB_MGMT}/pools/default/buckets/{BUCKET}/scopes/{SCOPE}/collections/{COLLECTION}")


@pytest.fixture
def live_db(live_index):
    """A clean CouchbaseSearch per test against the live index."""
    _flush_collection()
    db = _make_db(embedder=_DeterministicEmbedder())
    yield db


def _names_after_index(db, query: str, user_id, retries: int = 8):
    """Search with a few retries to let FTS catch up with just-written docs."""
    for _ in range(retries):
        results = db.search(query, limit=20, user_id=user_id)
        names = {d.name for d in results}
        if names:
            return names
        time.sleep(1)
    return set()


def _stored_owners(db) -> List[str]:
    from couchbase.cluster import Cluster
    from couchbase.n1ql import QueryScanConsistency
    from couchbase.options import QueryOptions

    cluster = Cluster(CB_CONN, _cluster_options())
    cluster.wait_until_ready(timedelta(seconds=30))
    scope = cluster.bucket(BUCKET).scope(SCOPE)
    result = scope.query(
        f"SELECT user_id FROM {COLLECTION}",
        QueryOptions(scan_consistency=QueryScanConsistency.REQUEST_PLUS),
    )
    return sorted(row["user_id"] for row in result.rows())


@live
class TestLiveSearchIsolationSync:
    """alice/bob mutual invisibility, admin-sees-all — the load-bearing live
    test on the real FTS vector index."""

    @pytest.fixture
    def populated(self, live_db):
        live_db.insert(content_hash="ha", documents=[_embedded("alice-salary", "Alice salary 180k")], user_id="alice")
        live_db.insert(content_hash="hb", documents=[_embedded("bob-salary", "Bob salary 215k")], user_id="bob")
        live_db.insert(
            content_hash="hs", documents=[_embedded("company-holidays", "office closed Jan 1")], user_id=None
        )
        time.sleep(3)
        return live_db

    def test_alice_sees_own_and_shared(self, populated):
        names = _names_after_index(populated, "salary", "alice")
        assert "alice-salary" in names
        assert "company-holidays" in names

    def test_alice_never_sees_bob(self, populated):
        names = _names_after_index(populated, "salary", "alice")
        assert "bob-salary" not in names

    def test_bob_never_sees_alice(self, populated):
        names = _names_after_index(populated, "salary", "bob")
        assert "bob-salary" in names
        assert "alice-salary" not in names

    def test_admin_sees_everything(self, populated):
        names = _names_after_index(populated, "salary", None)
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names


@live
class TestLiveDeleteScoping:
    """A scoped delete must remove only the caller's chunks and never the
    shared bucket."""

    def test_scoped_delete_only_removes_callers_chunks(self, live_db):
        alice = _embedded("alice-doc", "Alice's secret.")
        alice.content_id = "doc-1"
        bob = _embedded("bob-doc", "Bob's secret.")
        bob.content_id = "doc-1"
        live_db.insert(content_hash="h-alice", documents=[alice], user_id="alice")
        live_db.insert(content_hash="h-bob", documents=[bob], user_id="bob")
        time.sleep(2)

        # Bob deletes 'doc-1' under his own scope — Alice's chunk must survive.
        live_db.delete_by_content_id("doc-1", user_id="bob")
        time.sleep(1)
        assert _stored_owners(live_db) == ["alice"]

    def test_scoped_delete_does_not_touch_shared(self, live_db):
        shared = _embedded("shared-doc", "Org-wide content.")
        shared.content_id = "doc-2"
        owned = _embedded("alice-doc", "Alice content.")
        owned.content_id = "doc-2"
        live_db.insert(content_hash="h-shared", documents=[shared], user_id=None)
        live_db.insert(content_hash="h-alice", documents=[owned], user_id="alice")
        time.sleep(2)

        # Alice deletes 'doc-2' under her scope — the shared chunk must remain.
        live_db.delete_by_content_id("doc-2", user_id="alice")
        time.sleep(1)
        assert _stored_owners(live_db) == [CouchbaseSearch.SHARED_USER_ID]


@live
class TestLiveClobberAndDedupe:
    """The clobber regression and scoped upsert dedupe on the real cluster."""

    def test_two_users_same_content_and_hash_coexist(self, live_db):
        live_db.insert(content_hash="SAME", documents=[_embedded("secret", "The secret is 42.")], user_id="alice")
        live_db.insert(content_hash="SAME", documents=[_embedded("secret", "The secret is 42.")], user_id="bob")
        time.sleep(1)
        assert _stored_owners(live_db) == ["alice", "bob"]

    def test_scoped_dedupe_keeps_other_owner(self, live_db):
        live_db.upsert(content_hash="SH", documents=[_embedded("ad", "alice v1")], user_id="alice")
        live_db.upsert(content_hash="SH", documents=[_embedded("bd", "bob v1")], user_id="bob")
        # Alice re-upserts under the shared hash. Bob's chunk must survive.
        live_db.upsert(content_hash="SH", documents=[_embedded("ad", "alice v2")], user_id="alice")
        time.sleep(1)
        assert _stored_owners(live_db) == ["alice", "bob"]

    def test_same_user_reupsert_replaces(self, live_db):
        live_db.upsert(content_hash="H", documents=[_embedded("d", "content v1")], user_id="alice")
        live_db.upsert(content_hash="H", documents=[_embedded("d", "content v1")], user_id="alice")
        time.sleep(1)
        assert _stored_owners(live_db) == ["alice"]


@live
class TestLiveSearchIsolationAsync:
    """The async path has a real implementation (acouchbase) — verify it
    isolates exactly like the sync path."""

    async def test_async_alice_isolated(self, live_db):
        await live_db.async_insert(
            content_hash="ha", documents=[_embedded("alice-salary", "Alice salary 180k")], user_id="alice"
        )
        await live_db.async_insert(
            content_hash="hb", documents=[_embedded("bob-salary", "Bob salary 215k")], user_id="bob"
        )
        await live_db.async_insert(
            content_hash="hs", documents=[_embedded("company-holidays", "office closed Jan 1")], user_id=None
        )
        time.sleep(4)

        names = set()
        for _ in range(8):
            results = await live_db.async_search("salary", limit=20, user_id="alice")
            names = {d.name for d in results}
            if names:
                break
            time.sleep(1)
        assert "alice-salary" in names
        assert "company-holidays" in names
        assert "bob-salary" not in names

    async def test_async_admin_sees_all(self, live_db):
        await live_db.async_insert(
            content_hash="ha", documents=[_embedded("alice-salary", "Alice salary 180k")], user_id="alice"
        )
        await live_db.async_insert(
            content_hash="hb", documents=[_embedded("bob-salary", "Bob salary 215k")], user_id="bob"
        )
        time.sleep(4)

        names = set()
        for _ in range(8):
            results = await live_db.async_search("salary", limit=20, user_id=None)
            names = {d.name for d in results}
            if {"alice-salary", "bob-salary"} <= names:
                break
            time.sleep(1)
        assert {"alice-salary", "bob-salary"} <= names

    async def test_async_scoped_dedupe_keeps_other_owner(self, live_db):
        await live_db.async_upsert(content_hash="SH", documents=[_embedded("ad", "alice v1")], user_id="alice")
        await live_db.async_upsert(content_hash="SH", documents=[_embedded("bd", "bob v1")], user_id="bob")
        await live_db.async_upsert(content_hash="SH", documents=[_embedded("ad", "alice v2")], user_id="alice")
        time.sleep(1)
        assert _stored_owners(live_db) == ["alice", "bob"]
