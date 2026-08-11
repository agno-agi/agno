"""Milvus per-user RAG isolation contract.

Owner lives in a top-level ``user_id`` scalar field; the ``__shared__`` sentinel is the
shared bucket. Runs end-to-end against milvus-lite with a fresh ``.db`` file per test.
"""

import logging
from typing import List, Optional

import pytest

from agno.knowledge.document import Document

from .conftest import DeterministicEmbedder

# This handles some CI errors when running Milvus in GitHub Actions.
try:
    import pymilvus  # noqa: F401

    MILVUS_AVAILABLE = True
except (ImportError, TypeError):
    MILVUS_AVAILABLE = False

try:
    import milvus_lite  # noqa: F401

    MILVUS_LITE_AVAILABLE = True
except (ImportError, TypeError):
    MILVUS_LITE_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not (MILVUS_AVAILABLE and MILVUS_LITE_AVAILABLE),
    reason="pymilvus and milvus-lite are required for the Milvus isolation tests",
)

if MILVUS_AVAILABLE and MILVUS_LITE_AVAILABLE:
    from agno.vectordb.milvus import Milvus
    from agno.vectordb.milvus.milvus import SHARED_USER_ID_VALUE

# milvus-lite's embedded server does not implement the AllocTimestamp RPC and
# logs a NotImplementedError at ERROR on every connection; pymilvus handles the
# fallback, so keep that noise out of the test output.
logging.getLogger("grpc._server").setLevel(logging.CRITICAL)

TEST_COLLECTION = "isolation_test"


@pytest.fixture
def milvus_db(tmp_path):
    """A fresh vector-mode Milvus backed by a per-test milvus-lite ``.db`` file."""
    db = Milvus(collection=TEST_COLLECTION, uri=str(tmp_path / "milvus_iso.db"), embedder=DeterministicEmbedder())
    db.create()
    yield db
    try:
        db.drop()
    except Exception:
        pass


def _doc(name: str, content: str, content_id: Optional[str] = None) -> Document:
    doc = Document(name=name, content=content)
    if content_id is not None:
        doc.content_id = content_id
    return doc


def _alice_docs() -> List[Document]:
    return [_doc("alice-salary", "Alice salary one eighty")]


def _bob_docs() -> List[Document]:
    return [_doc("bob-salary", "Bob salary two fifteen")]


def _shared_docs() -> List[Document]:
    return [_doc("company-holidays", "salary office closed January")]


def _rows(db, fields=None):
    """Raw rows via explicit output fields (milvus-lite drops fields under the adapter's ``output_fields=["*"]``, so
    we name them)."""
    return db.client.query(
        collection_name=TEST_COLLECTION,
        filter="",
        output_fields=fields or ["id", "name", "user_id", "content_id", "content_hash"],
        limit=1000,
    )


def _owners(db) -> List:
    return sorted((str(r.get("user_id")) for r in _rows(db)))


def _count(db) -> int:
    return len(_rows(db))


def _search_names(db, query: str, user_id: Optional[str]) -> set:
    """Run the adapter search, then map result ids back to names via a raw query (milvus-lite drops ``name`` under
    the adapter's ``output_fields=["*"]``)."""
    results = db.search(query, limit=20, user_id=user_id)
    idmap = {r["id"]: r.get("name") for r in _rows(db)}
    return {idmap.get(d.id) for d in results}


class TestWriteStampsOwner:
    """Pin the contract: ``user_id`` is a top-level field, not nested in meta_data."""

    def test_explicit_user_id_persisted_top_level(self, milvus_db):
        milvus_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")
        rows = _rows(milvus_db, fields=["id", "user_id", "meta_data"])
        assert len(rows) == 1
        assert rows[0].get("user_id") == "alice"
        # And NOT smuggled into the caller-controlled meta_data blob.
        assert "user_id" not in milvus_db._decode_json_field(rows[0].get("meta_data"), default={})

    def test_none_user_id_persisted_as_shared_sentinel(self, milvus_db):
        milvus_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)
        rows = _rows(milvus_db, fields=["id", "user_id"])
        assert len(rows) == 1
        assert rows[0].get("user_id") == SHARED_USER_ID_VALUE

    def test_user_id_omitted_defaults_to_shared_sentinel(self, milvus_db):
        """Backwards-compatible: callers that never pass ``user_id`` get the shared sentinel — they're effectively
        opting out of isolation."""
        milvus_db.insert(content_hash="h1", documents=_shared_docs())
        rows = _rows(milvus_db, fields=["id", "user_id"])
        assert rows[0].get("user_id") == SHARED_USER_ID_VALUE


class TestScopeExpressionBuilder:
    """The scope-expression builder is small enough to unit-test directly, without spinning the DB at all."""

    def test_user_id_field_constant_is_user_id(self):
        # The field name is baked into every persisted row and into the scope
        # expression. If it drifts, retrieval silently stops matching what was
        # written - and an unmatched scope reads as "no rows", not as an error.
        from agno.vectordb.milvus.milvus import USER_ID_FIELD

        assert USER_ID_FIELD == "user_id"

    def test_none_user_id_applies_no_scope(self, milvus_db):
        # user_id=None is the admin view: the metadata filter passes through unchanged.
        assert milvus_db._scoped_filter_expr(None, None) is None
        assert milvus_db._scoped_filter_expr({"tag": "x"}, None) == 'meta_data["tag"] == "x"'

    def test_alice_scope_is_own_or_shared(self, milvus_db):
        assert milvus_db._scoped_filter_expr(None, "alice") == '(user_id == "alice" or user_id == "__shared__")'

    def test_scoped_filter_expr_ands_metadata_and_scope(self, milvus_db):
        expr = milvus_db._scoped_filter_expr({"tag": "x"}, "alice")
        assert expr == '(meta_data["tag"] == "x") and (user_id == "alice" or user_id == "__shared__")'

    def test_empty_string_is_a_scoped_tenant_not_unscoped(self, milvus_db):
        # "" is a real owner, not an admin bypass — it scopes to its own bucket plus shared.
        assert milvus_db._scoped_filter_expr(None, "") == '(user_id == "" or user_id == "__shared__")'

    def test_scoped_filter_expr_escapes_quotes_to_block_injection(self, milvus_db):
        # A quote in user_id cannot break out of the literal and widen the scope.
        expr = milvus_db._scoped_filter_expr(None, 'zzz" or user_id == "bob')
        assert expr == '(user_id == "zzz\\" or user_id == \\"bob" or user_id == "__shared__")'


class TestSearchScope:
    """The load-bearing test: alice's search returns her chunks plus shared chunks, never bob's."""

    @pytest.fixture
    def search_corpus(self, milvus_db):
        milvus_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        milvus_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        milvus_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return milvus_db

    def test_alice_sees_her_own_and_shared(self, search_corpus):
        names = _search_names(search_corpus, "salary", "alice")
        assert "alice-salary" in names
        assert "company-holidays" in names

    def test_alice_never_sees_bob(self, search_corpus):
        """The isolation contract."""
        names = _search_names(search_corpus, "salary", "alice")
        assert "bob-salary" not in names

    def test_bob_never_sees_alice(self, search_corpus):
        names = _search_names(search_corpus, "salary", "bob")
        assert "alice-salary" not in names
        assert "bob-salary" in names

    def test_admin_sees_everything(self, search_corpus):
        names = _search_names(search_corpus, "salary", None)
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names

    @pytest.mark.asyncio
    async def test_async_alice_never_sees_bob(self, milvus_db):
        await milvus_db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        await milvus_db.async_insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        await milvus_db.async_insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        results = await milvus_db.async_search("salary", limit=20, user_id="alice")
        idmap = {r["id"]: r.get("name") for r in _rows(milvus_db)}
        names = {idmap.get(d.id) for d in results}
        assert "alice-salary" in names
        assert "company-holidays" in names
        assert "bob-salary" not in names


class TestDedupScope:
    """Steal-prevention: the owner is folded into the deterministic doc id, so two users uploading byte-identical
    content (same content_hash) land on distinct primary keys."""

    def test_two_owners_identical_content_both_survive(self, milvus_db):
        milvus_db.insert(content_hash="h", documents=[_doc("a", "same secret", "c1")], user_id="alice")
        milvus_db.insert(content_hash="h", documents=[_doc("b", "same secret", "c1")], user_id="bob")
        rows = _rows(milvus_db)
        assert len(rows) == 2
        assert len({r["id"] for r in rows}) == 2  # distinct primary keys
        assert _owners(milvus_db) == ["alice", "bob"]

    def test_shared_reingest_does_not_wipe_owned(self, milvus_db):
        """A shared re-ingest of content a user already owns must not clobber the owned row — the two rows are keyed
        independently."""
        milvus_db.insert(content_hash="h", documents=[_doc("a", "same secret", "c1")], user_id="alice")
        milvus_db.insert(content_hash="h", documents=[_doc("s", "same secret", "c1")], user_id=None)
        assert _owners(milvus_db) == [SHARED_USER_ID_VALUE, "alice"]

    @pytest.mark.asyncio
    async def test_async_two_owners_identical_content_both_survive(self, milvus_db):
        await milvus_db.async_insert(content_hash="h", documents=[_doc("a", "same secret", "c1")], user_id="alice")
        await milvus_db.async_insert(content_hash="h", documents=[_doc("b", "same secret", "c1")], user_id="bob")
        assert _owners(milvus_db) == ["alice", "bob"]


class TestUpdateMetadataOwnership:
    """``update_metadata`` writes into the caller-controlled meta_data blob; it must never reassign the top-level
    owner, even if a ``user_id`` key is smuggled in."""

    def test_update_metadata_cannot_reassign_owner(self, milvus_db):
        milvus_db.insert(content_hash="h", documents=[_doc("a", "Alice secret", "c1")], user_id="alice")
        milvus_db.update_metadata("c1", {"user_id": "bob", "tag": "x"})
        rows = _rows(milvus_db, fields=["id", "user_id", "meta_data"])
        assert rows[0].get("user_id") == "alice"  # owner untouched
        meta = milvus_db._decode_json_field(rows[0].get("meta_data"), default={})
        assert "user_id" not in meta  # stripped from the metadata blob too
        assert meta.get("tag") == "x"  # legitimate keys still applied


class TestDeleteScope:
    """A scoped delete removes the caller's chunks alone - never another owner's, never the shared bucket."""

    @pytest.fixture
    def content_id_corpus(self, milvus_db):
        milvus_db.insert(content_hash="ha", documents=[_doc("alice-doc", "Alice secret", "doc-1")], user_id="alice")
        milvus_db.insert(content_hash="hb", documents=[_doc("bob-doc", "Bob secret", "doc-1")], user_id="bob")
        milvus_db.insert(content_hash="hs", documents=[_doc("shared-doc", "Shared", "doc-1")], user_id=None)
        return milvus_db

    def test_scoped_delete_only_removes_callers_chunks(self, content_id_corpus):
        """Bob deletes 'doc-1' under his own scope — alice's AND the shared chunk must remain."""
        assert content_id_corpus.delete_by_content_id("doc-1", user_id="bob") is True
        assert _owners(content_id_corpus) == [SHARED_USER_ID_VALUE, "alice"]

    def test_scoped_delete_does_not_touch_shared(self, content_id_corpus):
        """A scoped caller must never delete the shared bucket."""
        content_id_corpus.delete_by_content_id("doc-1", user_id="alice")
        owners = _owners(content_id_corpus)
        assert SHARED_USER_ID_VALUE in owners  # shared survived
        assert "alice" not in owners

    def test_unscoped_delete_wipes_everyone(self, content_id_corpus):
        """Legacy behaviour: ``user_id=None`` deletes across all owners."""
        assert content_id_corpus.delete_by_content_id("doc-1", user_id=None) is True
        assert _count(content_id_corpus) == 0

    def test_scoped_delete_is_no_op_when_nothing_owned(self, content_id_corpus):
        """Carol owns nothing; her scoped delete of doc-1 removes no rows."""
        content_id_corpus.delete_by_content_id("doc-1", user_id="carol")
        assert _count(content_id_corpus) == 3
