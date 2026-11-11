"""MongoDB per-user RAG isolation contract.

Owner lives in a top-level ``user_id`` field; NULL is the shared bucket. Atlas
``$vectorSearch`` needs a cluster, so the client is patched with an in-memory fake.
"""

from hashlib import md5
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from agno.knowledge.document import Document
from agno.vectordb.mongodb import MongoVectorDb

from .conftest import DeterministicEmbedder

TEST_DATABASE = "agno_iso_test"
USER_ID_FIELD = "user_id"


def _match(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    """Minimal MongoDB query matcher: top-level equality plus ``$or``/``$and``/``$regex``."""
    import re as _re

    for key, cond in query.items():
        if key == "$or":
            if not any(_match(doc, sub) for sub in cond):
                return False
            continue
        if key == "$and":
            if not all(_match(doc, sub) for sub in cond):
                return False
            continue
        if isinstance(cond, dict) and "$regex" in cond:
            flags = _re.I if "i" in cond.get("$options", "") else 0
            if not _re.search(cond["$regex"], str(doc.get(key, "")), flags):
                return False
            continue
        if doc.get(key) != cond:
            return False
    return True


class _FakeCursor(list):
    """A list that also answers ``.limit()``, the one cursor method the adapter chains."""

    def limit(self, n):
        return _FakeCursor(self[:n])


def _set_dotted(doc: Dict[str, Any], dotted_key: str, value: Any) -> None:
    """Apply a ``$set`` of a dotted key (e.g. ``meta_data.team``) in place."""
    parts = dotted_key.split(".")
    cur = doc
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


class _FakeCollection:
    """Stores inserted docs in a list so the adapter's writes/reads are real."""

    def __init__(self) -> None:
        self.docs: List[Dict[str, Any]] = []
        self.last_pipeline: Optional[List[Dict[str, Any]]] = None

    def insert_many(self, docs, ordered=False):
        for d in docs:
            self.docs.append(dict(d))

    def update_one(self, flt, update, upsert=False):
        set_doc = update["$set"]
        for i, d in enumerate(self.docs):
            if _match(d, flt):
                self.docs[i] = {**d, **set_doc}
                return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)
        if upsert:
            self.docs.append(dict(set_doc))
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=set_doc.get("_id"))
        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

    def update_many(self, flt, update):
        set_doc = update["$set"]
        matched = 0
        for i, d in enumerate(self.docs):
            if _match(d, flt):
                nd = dict(d)
                for key, value in set_doc.items():
                    _set_dotted(nd, key, value)
                self.docs[i] = nd
                matched += 1
        return SimpleNamespace(matched_count=matched, modified_count=matched)

    def find(self, flt=None, projection=None):
        flt = flt or {}
        matched = [dict(d) for d in self.docs if _match(d, flt)]
        # pymongo returns a cursor: iterable, and .limit() chains off it
        return _FakeCursor(matched)

    def find_one(self, flt=None, projection=None):
        flt = flt or {}
        for d in self.docs:
            if _match(d, flt):
                return dict(d)
        return None

    def delete_many(self, flt):
        flt = flt or {}
        keep = [d for d in self.docs if not _match(d, flt)]
        removed = len(self.docs) - len(keep)
        self.docs = keep
        return SimpleNamespace(deleted_count=removed)

    def delete_one(self, flt):
        for i, d in enumerate(self.docs):
            if _match(d, flt):
                del self.docs[i]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    def count_documents(self, flt=None):
        flt = flt or {}
        return sum(1 for d in self.docs if _match(d, flt))

    def run_aggregate(self, pipeline):
        """Record the pipeline and apply the ``$vectorSearch`` scope filter."""
        self.last_pipeline = pipeline
        scope = None
        for stage in pipeline:
            if "$vectorSearch" in stage:
                scope = stage["$vectorSearch"].get("filter")
                break
        out = []
        for d in self.docs:
            if scope is None or _match(d, scope):
                row = {k: v for k, v in d.items() if k != "embedding"}
                row["score"] = 1.0
                out.append(row)
        return out

    def aggregate(self, pipeline):
        return self.run_aggregate(pipeline)


class _FakeDatabase:
    def __init__(self) -> None:
        self._collections: Dict[str, _FakeCollection] = {}

    def __getitem__(self, name):
        return self._collections.setdefault(name, _FakeCollection())

    def list_collection_names(self):
        return list(self._collections.keys())

    def create_collection(self, name):
        return self._collections.setdefault(name, _FakeCollection())


class _FakeClient:
    def __init__(self, databases: Dict[str, _FakeDatabase]) -> None:
        self._databases = databases
        self.admin = SimpleNamespace(command=lambda *a, **k: {"ok": 1})

    def __getitem__(self, name):
        return self._databases.setdefault(name, _FakeDatabase())

    def append_metadata(self, *a, **k):
        return None


class _AsyncCursor:
    def __init__(self, data):
        self._data = data
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._data):
            raise StopAsyncIteration
        value = self._data[self._i]
        self._i += 1
        return value


class _AsyncFakeCollection:
    """Async facade over a shared sync ``_FakeCollection`` (same storage)."""

    def __init__(self, inner: _FakeCollection) -> None:
        self._inner = inner

    async def insert_many(self, docs, ordered=False):
        return self._inner.insert_many(docs, ordered=ordered)

    async def update_one(self, flt, update, upsert=False):
        return self._inner.update_one(flt, update, upsert=upsert)

    async def aggregate(self, pipeline):
        return _AsyncCursor(self._inner.run_aggregate(pipeline))

    @property
    def last_pipeline(self):
        return self._inner.last_pipeline


class _AsyncFakeDatabase:
    def __init__(self, sync_db: _FakeDatabase) -> None:
        self._sync_db = sync_db

    def __getitem__(self, name):
        return _AsyncFakeCollection(self._sync_db[name])


async def _async_ping(*a, **k):
    return {"ok": 1}


class _AsyncFakeClient:
    def __init__(self, databases: Dict[str, _FakeDatabase]) -> None:
        self._databases = databases
        self.admin = SimpleNamespace(command=_async_ping)

    def __getitem__(self, name):
        return _AsyncFakeDatabase(self._databases.setdefault(name, _FakeDatabase()))


@pytest.fixture
def mongo_db():
    """A MongoVectorDb whose sync + async clients are in-memory fakes."""
    databases: Dict[str, _FakeDatabase] = {}
    sync_client = _FakeClient(databases)
    async_client = _AsyncFakeClient(databases)
    with (
        patch("agno.vectordb.mongodb.mongodb.MongoClient", return_value=sync_client),
        patch("agno.vectordb.mongodb.mongodb.AsyncMongoClient", return_value=async_client),
    ):
        db = MongoVectorDb(
            collection_name="iso_test",
            db_url="mongodb://fake-host/",
            database=TEST_DATABASE,
            embedder=DeterministicEmbedder(),
            wait_until_index_ready_in_seconds=0,
            wait_after_insert_in_seconds=0,
        )
        yield db


def _doc(name: str, content: str, content_id: Optional[str] = None) -> Document:
    return Document(name=name, content=content, content_id=content_id)


def _alice_docs() -> List[Document]:
    return [_doc("alice-salary", "Alice salary is 180k")]


def _bob_docs() -> List[Document]:
    return [_doc("bob-salary", "Bob salary is 215k")]


def _shared_docs() -> List[Document]:
    return [_doc("company-holidays", "office closed Jan 1")]


def _owners(db) -> List[Optional[str]]:
    collection = db._get_collection()
    return sorted(
        (d.get(USER_ID_FIELD) for d in collection.find({}, {USER_ID_FIELD: 1})),
        key=lambda x: (x is None, x),
    )


def _vector_search_filter(pipeline) -> Any:
    """Return the ``$vectorSearch.filter`` from a captured pipeline, or a sentinel if the key is absent."""
    for stage in pipeline:
        if "$vectorSearch" in stage:
            return stage["$vectorSearch"].get("filter", "NO_FILTER_KEY")
    raise AssertionError("no $vectorSearch stage in pipeline")


class TestWriteStampsOwner:
    """user_id is persisted top-level (None -> the shared bucket)."""

    def test_explicit_user_id_persisted_top_level(self, mongo_db):
        mongo_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        doc = mongo_db._get_collection().find_one({"name": "alice-salary"})
        assert doc[USER_ID_FIELD] == "alice"
        # Owner must not leak into the caller-controlled meta_data blob.
        assert USER_ID_FIELD not in (doc.get("meta_data") or {})

    def test_none_user_id_persisted_as_null(self, mongo_db):
        mongo_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        doc = mongo_db._get_collection().find_one({"name": "company-holidays"})
        assert doc[USER_ID_FIELD] is None

    def test_omitted_user_id_defaults_to_null(self, mongo_db):
        mongo_db.insert(content_hash="hs", documents=_shared_docs())
        doc = mongo_db._get_collection().find_one({"name": "company-holidays"})
        assert doc[USER_ID_FIELD] is None


class TestOwnerFoldedId:
    """Two owners with identical content keep distinct ``_id``; a shared write keeps the base content id."""

    def test_two_owners_identical_content_get_distinct_id(self, mongo_db):
        mongo_db.insert(content_hash="same", documents=[_doc("d", "identical text")], user_id="alice")
        mongo_db.insert(content_hash="same", documents=[_doc("d", "identical text")], user_id="bob")

        ids = [d["_id"] for d in mongo_db._get_collection().find({})]
        assert len(ids) == 2
        assert len(set(ids)) == 2
        assert _owners(mongo_db) == ["alice", "bob"]

    def test_shared_write_keeps_base_content_id(self, mongo_db):
        mongo_db.insert(content_hash="same", documents=[_doc("d", "identical text")], user_id=None)
        base_id = md5(b"identical text").hexdigest()
        doc = mongo_db._get_collection().find_one({"name": "d"})
        assert doc["_id"] == base_id


class TestSearchScope:
    """A scoped search pre-filters to the caller's chunks plus the shared bucket; ``None`` applies no filter."""

    @pytest.fixture
    def search_corpus(self, mongo_db):
        mongo_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        mongo_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        mongo_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return mongo_db

    def test_scoped_search_builds_own_or_shared_filter(self, search_corpus):
        results = search_corpus.search("salary", limit=10, user_id="alice")

        sent_filter = _vector_search_filter(search_corpus._get_collection().last_pipeline)
        assert sent_filter == {"$or": [{USER_ID_FIELD: "alice"}, {USER_ID_FIELD: None}]}

        names = {d.name for d in results}
        assert "alice-salary" in names
        assert "company-holidays" in names
        assert "bob-salary" not in names

    def test_bob_scope_excludes_alice(self, search_corpus):
        names = {d.name for d in search_corpus.search("salary", limit=10, user_id="bob")}
        assert "bob-salary" in names
        assert "company-holidays" in names
        assert "alice-salary" not in names

    def test_admin_search_has_no_filter(self, search_corpus):
        names = {d.name for d in search_corpus.search("salary", limit=10, user_id=None)}

        sent_filter = _vector_search_filter(search_corpus._get_collection().last_pipeline)
        assert sent_filter == "NO_FILTER_KEY"
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names


class TestKeywordSearchScope:
    """``keyword_search`` is public, so it carries the owner scope itself.

    A caller reaching it directly rather than through ``search()`` would otherwise read every
    owner's chunks — the method took no user_id at all.
    """

    @pytest.fixture
    def search_corpus(self, mongo_db):
        mongo_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        mongo_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        mongo_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return mongo_db

    def test_keyword_search_accepts_a_user_id(self):
        import inspect

        assert "user_id" in inspect.signature(MongoVectorDb.keyword_search).parameters

    def test_scoped_keyword_search_never_returns_another_owner(self, search_corpus):
        names = {d.name for d in search_corpus.keyword_search("salary", limit=10, user_id="alice")}

        assert "alice-salary" in names
        assert "bob-salary" not in names

    def test_scoped_keyword_search_still_sees_shared(self, search_corpus):
        names = {d.name for d in search_corpus.keyword_search("office", limit=10, user_id="alice")}

        assert "company-holidays" in names

    def test_unscoped_keyword_search_sees_every_owner(self, search_corpus):
        names = {d.name for d in search_corpus.keyword_search("salary", limit=10, user_id=None)}

        assert {"alice-salary", "bob-salary"} <= names

    def test_vector_search_accepts_a_user_id(self):
        import inspect

        assert "user_id" in inspect.signature(MongoVectorDb.vector_search).parameters


class TestUpsertDedupScope:
    """An upsert scopes to the writing owner's row: identical content from another owner cannot overwrite it."""

    def test_two_owners_identical_content_both_survive(self, mongo_db):
        mongo_db.upsert(content_hash="same", documents=[_doc("d", "identical text")], user_id="alice")
        mongo_db.upsert(content_hash="same", documents=[_doc("d", "identical text")], user_id="bob")
        assert _owners(mongo_db) == ["alice", "bob"]
        assert mongo_db.get_count() == 2

    def test_shared_reingest_does_not_wipe_owned_row(self, mongo_db):
        mongo_db.upsert(content_hash="same", documents=[_doc("d", "identical text")], user_id="alice")
        mongo_db.upsert(content_hash="same", documents=[_doc("d", "identical text")], user_id=None)
        assert _owners(mongo_db) == ["alice", None]
        assert mongo_db.get_count() == 2

    def test_same_owner_reupsert_is_idempotent(self, mongo_db):
        mongo_db.upsert(content_hash="same", documents=[_doc("d", "identical text")], user_id="alice")
        mongo_db.upsert(content_hash="same", documents=[_doc("d", "identical text")], user_id="alice")
        assert mongo_db.get_count() == 1


class TestDeleteScope:
    """delete_by_content_id must scope to the caller; unscoped wipes all owners."""

    @pytest.fixture
    def content_id_corpus(self, mongo_db):
        mongo_db.insert(content_hash="h-alice", documents=[_doc("alice-doc", "Alice secret", "doc-1")], user_id="alice")
        mongo_db.insert(content_hash="h-bob", documents=[_doc("bob-doc", "Bob secret", "doc-1")], user_id="bob")
        mongo_db.insert(content_hash="h-shared", documents=[_doc("shared-doc", "Org secret", "doc-1")], user_id=None)
        return mongo_db

    def test_scoped_delete_only_removes_callers_chunks(self, content_id_corpus):
        assert content_id_corpus.delete_by_content_id("doc-1", user_id="bob") is True
        assert _owners(content_id_corpus) == ["alice", None]

    def test_scoped_delete_never_touches_shared(self, content_id_corpus):
        content_id_corpus.delete_by_content_id("doc-1", user_id="alice")
        owners = _owners(content_id_corpus)
        assert None in owners, "scoped delete wiped the shared bucket"
        assert "alice" not in owners

    def test_scoped_delete_by_foreign_owner_is_a_noop(self, content_id_corpus):
        assert content_id_corpus.delete_by_content_id("doc-1", user_id="carol") is True
        assert len(_owners(content_id_corpus)) == 3

    def test_unscoped_delete_wipes_everyone(self, content_id_corpus):
        assert content_id_corpus.delete_by_content_id("doc-1", user_id=None) is True
        assert content_id_corpus.get_count() == 0


class TestContentHashExistsScope:
    """content_hash_exists is scoped: identical content from another owner is not a duplicate."""

    def test_hash_scoped_to_owner(self, mongo_db):
        mongo_db.insert(content_hash="hx", documents=_alice_docs(), user_id="alice")
        assert mongo_db.content_hash_exists("hx", user_id="alice") is True
        assert mongo_db.content_hash_exists("hx", user_id="bob") is False

    def test_none_check_sees_the_shared_row(self, mongo_db):
        mongo_db.insert(content_hash="hx", documents=_shared_docs(), user_id=None)
        assert mongo_db.content_hash_exists("hx") is True

    def test_none_check_does_not_see_a_privately_owned_row(self, mongo_db):
        mongo_db.insert(content_hash="hx", documents=_alice_docs(), user_id="alice")
        assert mongo_db.content_hash_exists("hx") is False


class TestUpdateMetadataOwnership:
    """update_metadata must not let caller-supplied metadata reassign the top-level owner field."""

    def test_owner_field_is_not_reassignable_via_metadata(self, mongo_db):
        mongo_db.insert(content_hash="ha", documents=[_doc("alice-doc", "Alice secret", "doc-1")], user_id="alice")

        mongo_db.update_metadata("doc-1", {USER_ID_FIELD: "bob", "team": "eng"})

        doc = mongo_db._get_collection().find_one({"content_id": "doc-1"})
        assert doc[USER_ID_FIELD] == "alice"
        assert doc["meta_data"]["team"] == "eng"


class TestAsyncIsolation:
    """Async write/read path stamps the owner and scopes reads identically."""

    @pytest.mark.asyncio
    async def test_async_insert_stamps_owner_and_search_scopes(self, mongo_db):
        await mongo_db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        await mongo_db.async_insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        await mongo_db.async_insert(content_hash="hs", documents=_shared_docs(), user_id=None)

        results = await mongo_db.async_search("salary", limit=10, user_id="alice")

        sent_filter = _vector_search_filter(mongo_db._async_collection.last_pipeline)
        assert sent_filter == {"$or": [{USER_ID_FIELD: "alice"}, {USER_ID_FIELD: None}]}

        names = {d.name for d in results}
        assert "alice-salary" in names
        assert "company-holidays" in names
        assert "bob-salary" not in names

    @pytest.mark.asyncio
    async def test_async_admin_search_has_no_filter(self, mongo_db):
        await mongo_db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        await mongo_db.async_insert(content_hash="hb", documents=_bob_docs(), user_id="bob")

        names = {d.name for d in await mongo_db.async_search("salary", limit=10, user_id=None)}

        sent_filter = _vector_search_filter(mongo_db._async_collection.last_pipeline)
        assert sent_filter == "NO_FILTER_KEY"
        assert {"alice-salary", "bob-salary"} <= names
