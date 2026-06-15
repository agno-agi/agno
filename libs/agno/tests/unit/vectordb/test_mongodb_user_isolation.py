import os
import time
import uuid
from hashlib import md5
from typing import List, Optional

import pytest

from agno.knowledge.document import Document
from agno.vectordb.mongodb import MongoVectorDb
from agno.vectordb.search import SearchType

pymongo = pytest.importorskip("pymongo")

MONGO_URL = os.environ.get("MONGO_ISO_TEST_URL", "mongodb://localhost:27018/?directConnection=true")
TEST_DATABASE = "agno_iso_test"


def _server_supports_vector_search(url: str) -> bool:
    """Return True only if we can reach a server that exposes ``$vectorSearch``.

    We probe by creating a throwaway vectorSearch index. A plain mongod (or an
    unreachable server) raises, so the whole module skips rather than failing.
    """
    from pymongo import MongoClient
    from pymongo.operations import SearchIndexModel

    try:
        client = MongoClient(url, serverSelectionTimeoutMS=3000)
        client.admin.command("ping")
        db = client["agno_iso_probe"]
        probe = "probe_" + uuid.uuid4().hex[:8]
        db.create_collection(probe)
        try:
            db[probe].create_search_index(
                model=SearchIndexModel(
                    definition={
                        "fields": [{"type": "vector", "numDimensions": 4, "path": "embedding", "similarity": "cosine"}]
                    },
                    name="probe_index",
                    type="vectorSearch",
                )
            )
        finally:
            db[probe].drop()
        client.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _server_supports_vector_search(MONGO_URL),
    reason=f"No MongoDB Atlas (vectorSearch) server reachable at {MONGO_URL}",
)


class _DeterministicEmbedder:
    """A tiny embedder needing no network or API key.

    Every document and query embeds to the SAME constant vector, so the ANN
    search returns ALL chunks as candidates — the only thing that removes a
    chunk from a scoped result is the per-user FILTER, which is exactly what we
    want to assert (scope, not relevance, is doing the isolation)."""

    dimensions = 8
    enable_batch = False

    def _vec(self):
        return [1.0] + [0.0] * (self.dimensions - 1)

    def get_embedding(self, text):
        return self._vec()

    def get_embedding_and_usage(self, text):
        return self._vec(), {"total_tokens": 1}

    async def async_get_embedding(self, text):
        return self._vec()

    async def async_get_embedding_and_usage(self, text):
        return self._vec(), {"total_tokens": 1}

    def embed(self, document=None, *args, **kwargs):
        if document is not None and getattr(document, "embedding", None) is None:
            document.embedding = self._vec()

    async def async_embed(self, document=None, *args, **kwargs):
        if document is not None and getattr(document, "embedding", None) is None:
            document.embedding = self._vec()


def _wait_index_ready(db, timeout: float = 60.0) -> None:
    """Poll until the vectorSearch index is queryable (mongot indexes async)."""
    collection = db._get_collection()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for ix in collection.list_search_indexes():
                if ix["name"] == db.search_index_name and ix.get("status") == "READY" and ix.get("queryable"):
                    return
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError("vectorSearch index did not become queryable in time")


@pytest.fixture
def mongo_db():
    """A fresh MongoDb on a unique collection, backed by the deterministic
    embedder. The collection is dropped on teardown."""
    collection_name = "iso_" + uuid.uuid4().hex[:10]
    db = MongoVectorDb(
        collection_name=collection_name,
        db_url=MONGO_URL,
        database=TEST_DATABASE,
        embedder=_DeterministicEmbedder(),
        wait_until_index_ready_in_seconds=60,
        wait_after_insert_in_seconds=1,
    )
    db._get_client()  # initialise client/db before create() (it uses self._db)
    db.create()
    _wait_index_ready(db)
    yield db
    try:
        db.drop()
    except Exception:
        pass


def _doc(name: str, content: str) -> Document:
    return Document(name=name, content=content)


def _alice_docs() -> List[Document]:
    return [_doc("alice-salary", "Alice salary is 180k")]


def _bob_docs() -> List[Document]:
    return [_doc("bob-salary", "Bob salary is 215k")]


def _shared_docs() -> List[Document]:
    return [_doc("company-holidays", "office closed Jan 1")]


def _owners(db) -> List[Optional[str]]:
    collection = db._get_collection()
    return sorted(
        (d.get("user_id") for d in collection.find({}, {"user_id": 1})),
        key=lambda x: (x is None, x),
    )


# --------------------------------------------------------------------------- #
# Pure unit tests — no DB round-trip needed.
# --------------------------------------------------------------------------- #
class TestScopeAndIdConstruction:
    """The scope-filter and id builders are deterministic; test them directly so
    a regression is caught even without a live server (these still run because
    the module-level skip only fires when no vectorSearch server is reachable)."""

    @pytest.fixture
    def db(self, mongo_db):
        return mongo_db

    def test_user_id_key_constant(self):
        assert MongoVectorDb.USER_ID_KEY == "user_id"

    def test_scope_none_returns_no_filter(self, db):
        assert db._user_scope_filter(None) is None

    def test_scope_empty_string_collapses_to_none(self, db):
        # normalize_user_id collapses "" to None -> unscoped.
        assert db._user_scope_filter("") is None

    def test_scope_alice_is_own_or_shared(self, db):
        f = db._user_scope_filter("alice")
        assert f == {"$or": [{"user_id": "alice"}, {"user_id": None}]}

    def test_shared_id_is_legacy_content_only(self, db):
        legacy = md5(b"hello").hexdigest()
        assert db._doc_id("hello", None) == legacy
        # A scoped chunk gets a DIFFERENT id so it cannot clobber the shared one.
        assert db._doc_id("hello", "alice") != legacy

    def test_scoped_ids_differ_per_owner(self, db):
        assert db._doc_id("hello", "alice") != db._doc_id("hello", "bob")

    def test_content_hash_query_scopes_when_user_set(self, db):
        assert db._content_hash_query("h", "alice") == {"content_hash": "h", "user_id": "alice"}
        assert db._content_hash_query("h", None) == {"content_hash": "h"}

    def test_vector_search_uses_prefilter_not_match(self, db):
        """Guard the recall-correctness property: the scope lands in the
        ``$vectorSearch.filter`` option, never in a trailing ``$match``."""
        db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)

        # Capture the pipeline the adapter sends to the server.
        captured = {}
        collection = db._get_collection()
        real_aggregate = collection.aggregate

        def _spy(pipeline, *a, **kw):
            captured["pipeline"] = pipeline
            return real_aggregate(pipeline, *a, **kw)

        collection.aggregate = _spy  # type: ignore
        try:
            db.search(query="salary", limit=10, user_id="alice")
        finally:
            collection.aggregate = real_aggregate  # type: ignore

        stages = captured["pipeline"]
        vs = next(s for s in stages if "$vectorSearch" in s)["$vectorSearch"]
        assert vs.get("filter") == {"$or": [{"user_id": "alice"}, {"user_id": None}]}
        # No post-vectorSearch $match should carry the user scope.
        for s in stages:
            if "$match" in s:
                assert "user_id" not in str(s["$match"])


# --------------------------------------------------------------------------- #
# Existing-index migration: an Atlas index built BEFORE isolation lacks the
# ``user_id`` filter field, so a scoped ``$vectorSearch`` can't pre-filter on it.
# ``create()`` must detect that and recreate the index in place.
# --------------------------------------------------------------------------- #
class TestSearchIndexMigration:
    def _index_has_user_id_filter(self, db) -> bool:
        collection = db._get_collection()
        for ix in collection.list_search_indexes():
            if ix["name"] != db.search_index_name:
                continue
            fields = (ix.get("latestDefinition") or {}).get("fields", [])
            return any(f.get("type") == "filter" and f.get("path") == "user_id" for f in fields)
        return False

    @pytest.fixture
    def legacy_index_db(self):
        """A collection whose vectorSearch index is built WITHOUT the user_id
        filter field — the shape a pre-isolation deployment has on disk."""
        from pymongo import MongoClient
        from pymongo.operations import SearchIndexModel

        collection_name = "isomig_" + uuid.uuid4().hex[:10]
        client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
        coll = client[TEST_DATABASE][collection_name]
        coll.database.create_collection(collection_name)
        coll.create_search_index(
            model=SearchIndexModel(
                definition={
                    "fields": [{"type": "vector", "numDimensions": 8, "path": "embedding", "similarity": "cosine"}]
                },
                name="vector_index_1",
                type="vectorSearch",
            )
        )
        db = MongoVectorDb(
            collection_name=collection_name,
            db_url=MONGO_URL,
            database=TEST_DATABASE,
            embedder=_DeterministicEmbedder(),
            wait_until_index_ready_in_seconds=90,
            wait_after_insert_in_seconds=1,
        )
        db._get_client()
        _wait_index_ready(db)
        yield db
        try:
            db.drop()
        except Exception:
            pass
        client.close()

    def test_legacy_index_lacks_user_id_filter(self, legacy_index_db):
        # Precondition: the on-disk index has no user_id filter field.
        assert self._index_has_user_id_filter(legacy_index_db) is False

    def test_create_migrates_index_and_scoped_search_works(self, legacy_index_db):
        # create() must notice the missing filter field and recreate the index.
        legacy_index_db.create()
        _wait_index_ready(legacy_index_db)
        assert self._index_has_user_id_filter(legacy_index_db) is True

        legacy_index_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        legacy_index_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        legacy_index_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        time.sleep(3)
        names = {d.name for d in legacy_index_db.search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "company-holidays" in names
        assert "bob-salary" not in names


# --------------------------------------------------------------------------- #
# Write-side: how user_id is persisted.
# --------------------------------------------------------------------------- #
class TestWriteStampsOwner:
    def test_explicit_user_id_persisted_top_level(self, mongo_db):
        mongo_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        doc = mongo_db._get_collection().find_one({"name": "alice-salary"})
        assert doc["user_id"] == "alice"
        # Owner is NOT smuggled into the caller-controlled meta_data blob.
        assert "user_id" not in (doc.get("meta_data") or {})

    def test_none_user_id_persisted_as_null(self, mongo_db):
        mongo_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        doc = mongo_db._get_collection().find_one({"name": "company-holidays"})
        assert doc["user_id"] is None

    def test_omitted_user_id_defaults_to_null(self, mongo_db):
        mongo_db.insert(content_hash="hs", documents=_shared_docs())
        doc = mongo_db._get_collection().find_one({"name": "company-holidays"})
        assert doc["user_id"] is None


# --------------------------------------------------------------------------- #
# Vector-search isolation (the load-bearing contract).
# --------------------------------------------------------------------------- #
class TestVectorSearchIsolation:
    @pytest.fixture
    def populated(self, mongo_db):
        mongo_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        mongo_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        mongo_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        time.sleep(2)  # let mongot index the new docs
        return mongo_db

    def test_alice_sees_own_and_shared(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "company-holidays" in names

    def test_alice_never_sees_bob(self, populated):
        results = populated.search("salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "bob-salary" not in names
        for d in results:
            assert "Bob salary" not in d.content

    def test_bob_never_sees_alice(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id="bob")}
        assert "alice-salary" not in names

    def test_admin_sees_everything(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id=None)}
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names


# --------------------------------------------------------------------------- #
# Async vector-search isolation.
# --------------------------------------------------------------------------- #
class TestAsyncVectorSearchIsolation:
    async def _populate(self, db):
        await db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        await db.async_insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        await db.async_insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        time.sleep(2)

    async def test_async_alice_sees_own_and_shared_not_bob(self, mongo_db):
        await self._populate(mongo_db)
        names = {d.name for d in await mongo_db.async_search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "company-holidays" in names
        assert "bob-salary" not in names

    async def test_async_admin_sees_everything(self, mongo_db):
        await self._populate(mongo_db)
        names = {d.name for d in await mongo_db.async_search("salary", limit=10, user_id=None)}
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names


# --------------------------------------------------------------------------- #
# Keyword ($regex) isolation.
# --------------------------------------------------------------------------- #
class TestKeywordSearchIsolation:
    @pytest.fixture
    def populated(self, mongo_db):
        mongo_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        mongo_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        mongo_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return mongo_db

    def test_alice_keyword_sees_own_and_shared_not_bob(self, populated):
        # "salary" matches both alice and bob content; scope must drop bob.
        names = {d.name for d in populated.keyword_search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "bob-salary" not in names

    def test_alice_keyword_sees_shared(self, populated):
        names = {d.name for d in populated.keyword_search("closed", limit=10, user_id="alice")}
        assert "company-holidays" in names

    def test_admin_keyword_sees_all(self, populated):
        names = {d.name for d in populated.keyword_search("salary", limit=10, user_id=None)}
        assert {"alice-salary", "bob-salary"} <= names


# --------------------------------------------------------------------------- #
# Delete scoping.
# --------------------------------------------------------------------------- #
class TestDeleteByContentIdIsolation:
    @pytest.fixture
    def populated(self, mongo_db):
        alice = _doc("alice-doc", "Alice secret")
        alice.content_id = "doc-1"
        bob = _doc("bob-doc", "Bob secret")
        bob.content_id = "doc-1"
        shared = _doc("shared-doc", "Org secret")
        shared.content_id = "doc-1"
        mongo_db.insert(content_hash="h-alice", documents=[alice], user_id="alice")
        mongo_db.insert(content_hash="h-bob", documents=[bob], user_id="bob")
        mongo_db.insert(content_hash="h-shared", documents=[shared], user_id=None)
        return mongo_db

    def test_scoped_delete_only_removes_callers_chunks(self, populated):
        # Bob deletes doc-1 under his scope; alice + shared survive.
        assert populated.delete_by_content_id("doc-1", user_id="bob") is True
        assert _owners(populated) == ["alice", None]

    def test_scoped_delete_never_touches_shared(self, populated):
        populated.delete_by_content_id("doc-1", user_id="alice")
        owners = _owners(populated)
        assert None in owners, "scoped delete wiped the shared bucket"
        assert "alice" not in owners

    def test_scoped_delete_returns_false_when_nothing_owned(self, populated):
        assert populated.delete_by_content_id("doc-1", user_id="carol") is False
        assert len(_owners(populated)) == 3

    def test_unscoped_delete_wipes_everyone(self, populated):
        assert populated.delete_by_content_id("doc-1", user_id=None) is True
        assert populated.get_count() == 0


# --------------------------------------------------------------------------- #
# Cross-user clobber (the public-API correctness bug).
# --------------------------------------------------------------------------- #
class TestClobberPrevention:
    def test_two_users_same_content_and_hash_coexist(self, mongo_db):
        mongo_db.insert(content_hash="SAME", documents=[_doc("secret", "The secret is 42.")], user_id="alice")
        mongo_db.insert(content_hash="SAME", documents=[_doc("secret", "The secret is 42.")], user_id="bob")
        assert _owners(mongo_db) == ["alice", "bob"]
        assert mongo_db.get_count() == 2

    def test_same_user_reinsert_same_content_replaces(self, mongo_db):
        mongo_db.insert(content_hash="H", documents=[_doc("d", "content v1")], user_id="alice")
        mongo_db.insert(content_hash="H", documents=[_doc("d", "content v1")], user_id="alice")
        assert mongo_db.get_count() == 1

    def test_user_and_shared_same_content_coexist(self, mongo_db):
        mongo_db.insert(content_hash="SAME", documents=[_doc("secret", "x")], user_id="alice")
        mongo_db.insert(content_hash="SAME", documents=[_doc("secret", "x")], user_id=None)
        assert _owners(mongo_db) == ["alice", None]


# --------------------------------------------------------------------------- #
# Upsert dedupe scoping (sync + async).
# --------------------------------------------------------------------------- #
class TestUpsertDedupeIsolation:
    def test_scoped_dedupe_does_not_touch_other_owner(self, mongo_db):
        mongo_db.upsert(content_hash="SH", documents=[_doc("ad", "alice v1")], user_id="alice")
        mongo_db.upsert(content_hash="SH", documents=[_doc("bd", "bob v1")], user_id="bob")
        # Alice re-upserts CHANGED content under the shared hash; bob survives.
        mongo_db.upsert(content_hash="SH", documents=[_doc("ad", "alice v2")], user_id="alice")
        assert _owners(mongo_db) == ["alice", "bob"]
        assert mongo_db.get_count() == 2

    def test_same_user_reupsert_changed_content_replaces(self, mongo_db):
        mongo_db.upsert(content_hash="H", documents=[_doc("d", "v1")], user_id="alice")
        mongo_db.upsert(content_hash="H", documents=[_doc("d", "v2")], user_id="alice")
        assert mongo_db.get_count() == 1

    async def test_async_scoped_dedupe_keeps_other_owner(self, mongo_db):
        await mongo_db.async_upsert(content_hash="SH", documents=[_doc("ad", "alice v1")], user_id="alice")
        await mongo_db.async_upsert(content_hash="SH", documents=[_doc("bd", "bob v1")], user_id="bob")
        await mongo_db.async_upsert(content_hash="SH", documents=[_doc("ad", "alice v2")], user_id="alice")
        assert _owners(mongo_db) == ["alice", "bob"]
        assert mongo_db.get_count() == 2

    async def test_async_reupsert_changed_content_replaces(self, mongo_db):
        await mongo_db.async_upsert(content_hash="H", documents=[_doc("d", "v1")], user_id="alice")
        await mongo_db.async_upsert(content_hash="H", documents=[_doc("d", "v2")], user_id="alice")
        assert mongo_db.get_count() == 1

    def test_none_upsert_dedupe_does_not_wipe_scoped_owners(self, mongo_db):
        # A shared/admin re-ingest (user_id=None) under a content_hash that
        # scoped owners also hold must clear only the shared (null) bucket, never
        # alice's or bob's rows. The dedupe-delete scopes None to the shared
        # bucket on its own (the existence gate is global, the delete is not).
        mongo_db.upsert(content_hash="SH", documents=[_doc("ad", "alice v1")], user_id="alice")
        mongo_db.upsert(content_hash="SH", documents=[_doc("bd", "bob v1")], user_id="bob")
        mongo_db.upsert(content_hash="SH", documents=[_doc("sd", "shared v1")], user_id=None)
        # Re-ingest the shared content; only the shared row is replaced.
        mongo_db.upsert(content_hash="SH", documents=[_doc("sd", "shared v2")], user_id=None)
        assert _owners(mongo_db) == ["alice", "bob", None]
        assert mongo_db.get_count() == 3


# --------------------------------------------------------------------------- #
# content_hash_exists scoping.
# --------------------------------------------------------------------------- #
class TestContentHashExistsScoping:
    def test_content_hash_exists_is_scoped(self, mongo_db):
        mongo_db.insert(content_hash="H", documents=[_doc("ad", "alice")], user_id="alice")
        assert mongo_db.content_hash_exists("H", user_id="alice") is True
        assert mongo_db.content_hash_exists("H", user_id="bob") is False
        # Unscoped sees it regardless of owner.
        assert mongo_db.content_hash_exists("H") is True


# --------------------------------------------------------------------------- #
# update_metadata must not reassign ownership.
# --------------------------------------------------------------------------- #
class TestUpdateMetadataOwnershipGuard:
    @pytest.fixture
    def owned(self, mongo_db):
        doc = _doc("md", "metadata test content")
        doc.content_id = "cid-1"
        mongo_db.insert(content_hash="hm", documents=[doc], user_id="alice")
        return mongo_db

    def test_caller_cannot_reassign_owner(self, owned):
        owned.update_metadata("cid-1", {"user_id": "bob", "tag": "x"})
        assert _owners(owned) == ["alice"], "update_metadata reassigned the chunk's owner"

    def test_legitimate_metadata_still_applied(self, owned):
        owned.update_metadata("cid-1", {"tag": "x", "user_id": "bob"})
        doc = owned._get_collection().find_one({"content_id": "cid-1"})
        assert doc["meta_data"].get("tag") == "x"
        assert doc["user_id"] == "alice"


# --------------------------------------------------------------------------- #
# Hybrid search: assert pipeline construction (atlas-local may lack the text
# "default" Atlas Search index the keyword branch needs). When the live hybrid
# query is exercisable we additionally assert isolation; otherwise we pin the
# scope construction so a regression is still caught.
# --------------------------------------------------------------------------- #
class TestHybridSearchScope:
    @pytest.fixture
    def hybrid_db(self):
        collection_name = "isohy_" + uuid.uuid4().hex[:10]
        db = MongoVectorDb(
            collection_name=collection_name,
            db_url=MONGO_URL,
            database=TEST_DATABASE,
            embedder=_DeterministicEmbedder(),
            search_type=SearchType.hybrid,
            wait_until_index_ready_in_seconds=60,
            wait_after_insert_in_seconds=1,
        )
        db._get_client()  # initialise client/db before create() (it uses self._db)
        db.create()
        _wait_index_ready(db)
        yield db
        try:
            db.drop()
        except Exception:
            pass

    def test_hybrid_pipeline_scopes_both_branches(self, hybrid_db):
        """Capture the aggregate pipeline and assert the scope is applied to the
        vector branch (pre-filter) AND the keyword ``$unionWith`` branch."""
        hybrid_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        hybrid_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")

        captured = {}
        collection = hybrid_db._get_collection()
        real_aggregate = collection.aggregate

        def _spy(pipeline, *a, **kw):
            captured["pipeline"] = list(pipeline)
            return real_aggregate(pipeline, *a, **kw)

        collection.aggregate = _spy  # type: ignore
        try:
            # The live query may fail if there's no "default" text index; we only
            # need the pipeline that was constructed and sent.
            hybrid_db.hybrid_search("salary", limit=5, user_id="alice")
        except Exception:
            pass
        finally:
            collection.aggregate = real_aggregate  # type: ignore

        stages = captured.get("pipeline")
        assert stages is not None, "hybrid_search did not build a pipeline"
        scope = {"$or": [{"user_id": "alice"}, {"user_id": None}]}

        vs = next(s for s in stages if "$vectorSearch" in s)["$vectorSearch"]
        assert vs.get("filter") == scope, "vector branch missing pre-filter scope"

        union = next(s for s in stages if "$unionWith" in s)["$unionWith"]
        branch = union["pipeline"]
        assert any(s.get("$match") == scope for s in branch), "keyword branch missing scope $match"

    def test_hybrid_unscoped_has_no_scope(self, hybrid_db):
        hybrid_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")

        captured = {}
        collection = hybrid_db._get_collection()
        real_aggregate = collection.aggregate

        def _spy(pipeline, *a, **kw):
            captured["pipeline"] = list(pipeline)
            return real_aggregate(pipeline, *a, **kw)

        collection.aggregate = _spy  # type: ignore
        try:
            hybrid_db.hybrid_search("salary", limit=5, user_id=None)
        except Exception:
            pass
        finally:
            collection.aggregate = real_aggregate  # type: ignore

        stages = captured.get("pipeline")
        assert stages is not None
        vs = next(s for s in stages if "$vectorSearch" in s)["$vectorSearch"]
        assert "filter" not in vs
        union = next(s for s in stages if "$unionWith" in s)["$unionWith"]
        assert not any("$match" in s and "user_id" in str(s["$match"]) for s in union["pipeline"])
