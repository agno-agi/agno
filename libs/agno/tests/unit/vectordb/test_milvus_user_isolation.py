from hashlib import md5
from typing import List, Optional

import pytest

from agno.knowledge.document import Document
from agno.vectordb.search import SearchType

try:
    import pymilvus  # noqa: F401

    MILVUS_AVAILABLE = True
except ImportError:
    MILVUS_AVAILABLE = False

try:
    import milvus_lite  # noqa: F401

    MILVUS_LITE_AVAILABLE = True
except ImportError:
    MILVUS_LITE_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not (MILVUS_AVAILABLE and MILVUS_LITE_AVAILABLE),
    reason="pymilvus and milvus-lite are required for the Milvus isolation tests",
)

if MILVUS_AVAILABLE and MILVUS_LITE_AVAILABLE:
    from agno.vectordb.milvus import Milvus

TEST_COLLECTION = "isolation_test"


class _DeterministicEmbedder:
    """A tiny embedder that needs no network or API key. The content steers the
    vector so distinct documents land in distinct buckets — all the isolation
    tests need — and it gives us a real async surface too."""

    dimensions = 8
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

    def embed(self, document, *args, **kwargs):
        document.embedding = self.get_embedding(document.content)

    async def async_embed(self, document, *args, **kwargs):
        document.embedding = self.get_embedding(document.content)


@pytest.fixture
def milvus_uri(tmp_path):
    """A fresh milvus-lite ``.db`` file per test so there is no shared state."""
    return str(tmp_path / "milvus_iso.db")


@pytest.fixture
def milvus_db(milvus_uri):
    """A fresh vector-mode Milvus backed by milvus-lite."""
    db = Milvus(collection=TEST_COLLECTION, uri=milvus_uri, embedder=_DeterministicEmbedder())
    db.create()
    yield db
    try:
        db.drop()
    except Exception:
        pass


@pytest.fixture
def milvus_hybrid_db(milvus_uri):
    """A fresh hybrid-mode Milvus backed by milvus-lite."""
    db = Milvus(
        collection=TEST_COLLECTION,
        uri=milvus_uri,
        embedder=_DeterministicEmbedder(),
        search_type=SearchType.hybrid,
    )
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
    """Raw rows via explicit output fields (milvus-lite honours these where it
    drops fields under ``output_fields=["*"]``)."""
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
    """Run the adapter search, then map the returned ids back to names via a raw
    query (milvus-lite drops ``name`` under the adapter's ``output_fields=["*"]``,
    but the result ids are reliable)."""
    results = db.search(query, limit=20, user_id=user_id)
    ids = {d.id for d in results}
    idmap = {r["id"]: r.get("name") for r in _rows(db)}
    return {idmap.get(i) for i in ids}


async def _async_search_names(db, query: str, user_id: Optional[str]) -> set:
    results = await db.async_search(query, limit=20, user_id=user_id)
    ids = {d.id for d in results}
    idmap = {r["id"]: r.get("name") for r in _rows(db)}
    return {idmap.get(i) for i in ids}


class TestUserIdFieldStorage:
    """Pin the contract: ``user_id`` is a top-level field, not nested in
    meta_data. The owner-scope filter relies on this."""

    def test_user_id_key_constant_is_user_id(self):
        # Storage compatibility marker. If this changes, every previously
        # persisted row's user_id stops being readable by the filter.
        assert Milvus.USER_ID_KEY == "user_id"

    def test_explicit_user_id_persisted_top_level(self, milvus_db):
        milvus_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")
        rows = _rows(milvus_db, fields=["id", "user_id", "meta_data"])
        assert len(rows) == 1
        assert rows[0].get("user_id") == "alice"
        # And NOT smuggled into the caller-controlled meta_data blob.
        assert "user_id" not in milvus_db._decode_json_field(rows[0].get("meta_data"), default={})

    def test_none_user_id_persisted_as_null(self, milvus_db):
        milvus_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)
        rows = _rows(milvus_db, fields=["id", "user_id"])
        assert len(rows) == 1
        assert rows[0].get("user_id") is None

    def test_user_id_omitted_defaults_to_null(self, milvus_db):
        """Backwards-compatible: callers that never pass ``user_id`` get NULL
        (shared) — they're effectively opting out of isolation."""
        milvus_db.insert(content_hash="h1", documents=_shared_docs())
        rows = _rows(milvus_db, fields=["id", "user_id"])
        assert rows[0].get("user_id") is None


class TestQuoteEscaping:
    """``_quote`` renders the inner of a double-quoted Milvus filter literal. It
    must escape backslash and quote (injection guard) AND newline/CR/tab, which
    Milvus's lexer rejects raw ('unterminated string literal')."""

    def test_quote_escapes_backslash_and_quote(self):
        from agno.vectordb.milvus.milvus import _quote

        assert _quote("a\\b") == "a\\\\b"
        assert _quote('a"b') == 'a\\"b'

    def test_quote_escapes_control_chars(self):
        from agno.vectordb.milvus.milvus import _quote

        assert _quote("a\nb") == "a\\nb"
        assert _quote("a\rb") == "a\\rb"
        assert _quote("a\tb") == "a\\tb"


class TestScopeExpressionBuilder:
    """The scope-expression builders are small enough to unit-test directly,
    without spinning the DB at all."""

    def test_none_returns_no_scope(self, milvus_db):
        assert milvus_db._user_scope_expr(None) is None

    def test_alice_scope_is_own_or_null(self, milvus_db):
        assert milvus_db._user_scope_expr("alice") == '(user_id == "alice" or user_id is null)'

    def test_scoped_expr_none_with_no_filters_is_none(self, milvus_db):
        assert milvus_db._scoped_expr(None, None) is None

    def test_scoped_expr_admin_keeps_metadata_filter_only(self, milvus_db):
        # user_id=None means no scope; the metadata filter passes through unchanged.
        assert milvus_db._scoped_expr({"tag": "x"}, None) == 'meta_data["tag"] == "x"'

    def test_scoped_expr_ands_metadata_and_scope(self, milvus_db):
        expr = milvus_db._scoped_expr({"tag": "x"}, "alice")
        assert expr == '(meta_data["tag"] == "x") and (user_id == "alice" or user_id is null)'


class TestVectorSearchIsolation:
    """The load-bearing test: alice's search returns her chunks plus shared
    chunks, never bob's."""

    @pytest.fixture
    def populated_db(self, milvus_db):
        milvus_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        milvus_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        milvus_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return milvus_db

    def test_alice_sees_her_own_and_shared(self, populated_db):
        names = _search_names(populated_db, "salary", "alice")
        assert "alice-salary" in names
        assert "company-holidays" in names

    def test_alice_never_sees_bob(self, populated_db):
        """The isolation contract. If this fails the feature is broken — alice
        would be retrieving bob's confidential chunks."""
        names = _search_names(populated_db, "salary", "alice")
        assert "bob-salary" not in names

    def test_bob_never_sees_alice(self, populated_db):
        names = _search_names(populated_db, "salary", "bob")
        assert "alice-salary" not in names
        assert "bob-salary" in names

    def test_admin_sees_everything(self, populated_db):
        names = _search_names(populated_db, "salary", None)
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names

    async def test_async_alice_never_sees_bob(self, milvus_db):
        await milvus_db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        await milvus_db.async_insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        await milvus_db.async_insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        names = await _async_search_names(milvus_db, "salary", "alice")
        assert "alice-salary" in names
        assert "company-holidays" in names
        assert "bob-salary" not in names

    async def test_async_admin_sees_everything(self, milvus_db):
        await milvus_db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        await milvus_db.async_insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        names = await _async_search_names(milvus_db, "salary", None)
        assert {"alice-salary", "bob-salary"} <= names


class TestInjectionThroughUserId:
    """A user_id is interpolated into the Milvus filter expression, so it must be
    escaped (``_quote``). A crafted id must not break out of the string literal
    and widen the scope to other owners."""

    @pytest.fixture
    def populated_db(self, milvus_db):
        milvus_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        milvus_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        milvus_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return milvus_db

    def test_injection_user_id_leaks_no_foreign_chunks(self, populated_db):
        names = _search_names(populated_db, "salary", 'x" or user_id != "y')
        assert "alice-salary" not in names
        assert "bob-salary" not in names

    def test_user_id_with_quote_isolates(self, milvus_db):
        milvus_db.insert(content_hash="hq", documents=[_doc("quoted", "salary quoted")], user_id='wei"rd')
        milvus_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        names = _search_names(milvus_db, "salary", 'wei"rd')
        assert "quoted" in names
        assert "bob-salary" not in names

    def test_user_id_with_newline_does_not_break_scoped_search(self, milvus_db):
        """A literal newline (or tab/CR) in the id must be escaped: Milvus's
        filter lexer rejects a raw control char inside a quoted literal with
        'unterminated string literal', so an unescaped one turns the owner's
        own scoped search into a raised error rather than returning their rows."""
        owner = "line1\nline2"
        milvus_db.insert(content_hash="hn", documents=[_doc("nl-doc", "salary newline owner")], user_id=owner)
        milvus_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        # Must not raise, and must isolate.
        names = _search_names(milvus_db, "salary", owner)
        assert "nl-doc" in names
        assert "bob-salary" not in names

    def test_injection_through_delete_does_not_widen_scope(self, milvus_db):
        """A crafted user_id on a scoped delete must not break out of the literal
        and wipe other owners' (or the shared) chunks under the same content_id."""
        milvus_db.insert(content_hash="ha", documents=[_doc("ad", "x", "doc-1")], user_id="alice")
        milvus_db.insert(content_hash="hb", documents=[_doc("bd", "y", "doc-1")], user_id="bob")
        milvus_db.insert(content_hash="hs", documents=[_doc("sd", "z", "doc-1")], user_id=None)
        # The id is escaped, so it matches an owner nobody has: nothing deleted.
        result = milvus_db.delete_by_content_id(content_id="doc-1", user_id='x" or user_id != "x')
        assert result is False
        assert _count(milvus_db) == 3


class TestHybridSearchIsolation:
    """Hybrid search runs each modality as its own AnnSearchRequest. The owner
    scope must be set on EACH request (a pre-filter), not post-fusion, or scoped
    users get starved out of the per-branch top-k."""

    @pytest.fixture
    def populated_db(self, milvus_hybrid_db):
        milvus_hybrid_db.insert(content_hash="ha", documents=[_doc("alice-salary", "salary alice")], user_id="alice")
        milvus_hybrid_db.insert(content_hash="hb", documents=[_doc("bob-salary", "salary bob")], user_id="bob")
        milvus_hybrid_db.insert(content_hash="hs", documents=[_doc("company-holidays", "salary shared")], user_id=None)
        return milvus_hybrid_db

    def test_alice_sees_own_and_shared(self, populated_db):
        names = _search_names(populated_db, "salary", "alice")
        assert "alice-salary" in names
        assert "company-holidays" in names

    def test_alice_never_sees_bob_in_hybrid(self, populated_db):
        names = _search_names(populated_db, "salary", "alice")
        assert "bob-salary" not in names

    def test_admin_sees_all_in_hybrid(self, populated_db):
        names = _search_names(populated_db, "salary", None)
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names

    def test_injection_user_id_leaks_no_foreign_chunks(self, populated_db):
        """The owner scope is built into each AnnSearchRequest via the same
        ``_scoped_expr``; a crafted user_id must be escaped there too."""
        names = _search_names(populated_db, "salary", 'x" or user_id != "y')
        assert "alice-salary" not in names
        assert "bob-salary" not in names

    async def test_async_hybrid_no_leak(self, milvus_hybrid_db):
        await milvus_hybrid_db.async_insert(
            content_hash="ha", documents=[_doc("alice-salary", "salary alice")], user_id="alice"
        )
        await milvus_hybrid_db.async_insert(
            content_hash="hb", documents=[_doc("bob-salary", "salary bob")], user_id="bob"
        )
        names = await _async_search_names(milvus_hybrid_db, "salary", "alice")
        assert "alice-salary" in names
        assert "bob-salary" not in names


class TestDeleteByContentIdIsolation:
    """``delete_by_content_id(content_id, user_id=...)`` must scope the delete to
    the caller's chunks — otherwise Bob could guess Alice's content_id and wipe
    her chunks, or a scoped caller could wipe the org's shared chunks."""

    @pytest.fixture
    def populated_db(self, milvus_db):
        milvus_db.insert(content_hash="ha", documents=[_doc("alice-doc", "Alice secret", "doc-1")], user_id="alice")
        milvus_db.insert(content_hash="hb", documents=[_doc("bob-doc", "Bob secret", "doc-1")], user_id="bob")
        milvus_db.insert(content_hash="hs", documents=[_doc("shared-doc", "Shared", "doc-1")], user_id=None)
        return milvus_db

    def test_scoped_delete_only_removes_callers_chunks(self, populated_db):
        """Bob deletes 'doc-1' under his own scope — alice's AND the shared chunk
        must remain."""
        assert populated_db.delete_by_content_id("doc-1", user_id="bob") is True
        assert _owners(populated_db) == ["None", "alice"]

    def test_scoped_delete_does_not_touch_shared(self, populated_db):
        """A scoped caller must never delete the shared (NULL-owned) bucket."""
        populated_db.delete_by_content_id("doc-1", user_id="alice")
        owners = _owners(populated_db)
        assert "None" in owners  # shared survived
        assert "alice" not in owners

    def test_unscoped_delete_wipes_everyone(self, populated_db):
        """Legacy behaviour: ``user_id=None`` deletes across all owners."""
        assert populated_db.delete_by_content_id("doc-1", user_id=None) is True
        assert _count(populated_db) == 0

    def test_scoped_delete_returns_false_when_nothing_owned(self, populated_db):
        """Carol owns nothing; her scoped delete deletes nothing and reports False."""
        assert populated_db.delete_by_content_id("doc-1", user_id="carol") is False
        assert _count(populated_db) == 3


class TestDocIdClobber:
    """A chunk's primary key must fold in the owner. Milvus upserts by primary
    key, so without the owner two users inserting IDENTICAL content under the
    SAME content_hash collide on one id and one silently overwrites the other."""

    def test_two_users_same_content_and_hash_coexist(self, milvus_db):
        """The clobber regression. Pre-fix this left exactly ONE row."""
        milvus_db.insert(content_hash="SAME", documents=[_doc("secret", "The secret is 42.")], user_id="alice")
        milvus_db.insert(content_hash="SAME", documents=[_doc("secret", "The secret is 42.")], user_id="bob")
        assert _owners(milvus_db) == ["alice", "bob"]

    def test_clobbered_rows_stay_isolated_on_search(self, milvus_db):
        milvus_db.insert(content_hash="SAME", documents=[_doc("secret", "The secret is 42.")], user_id="alice")
        milvus_db.insert(content_hash="SAME", documents=[_doc("secret", "The secret is 42.")], user_id="bob")
        # Each sees exactly one row (their own), proving the other's still exists.
        assert len(milvus_db.search("secret", limit=20, user_id="alice")) == 1
        assert len(milvus_db.search("secret", limit=20, user_id="bob")) == 1
        assert _count(milvus_db) == 2

    def test_same_user_reinsert_same_hash_replaces(self, milvus_db):
        """Same owner + same content + same hash is the SAME id, so a re-insert
        replaces in place rather than duplicating."""
        milvus_db.insert(content_hash="H", documents=[_doc("d", "content v1")], user_id="alice")
        milvus_db.insert(content_hash="H", documents=[_doc("d", "content v1")], user_id="alice")
        assert _count(milvus_db) == 1

    def test_shared_bucket_keeps_legacy_id(self, milvus_db):
        """``user_id=None`` chunks keep the two-part id so previously persisted
        shared rows stay addressable."""
        legacy = md5(b"x_H").hexdigest()
        assert milvus_db._doc_id("x", "H", None) == legacy
        assert milvus_db._doc_id("x", "H", "alice") != legacy
        assert milvus_db._doc_id("x", "H", "alice") == md5(b"x_H_alice").hexdigest()


class TestUpsertDedupeIsolation:
    """``upsert`` dedupes by deleting prior chunks with the same content_hash
    before re-inserting. That delete must be SCOPED to the owner — otherwise
    Alice re-upserting her content wipes Bob's chunk that happens to carry the
    same content_hash (a public-API caller can pass any hash)."""

    def test_scoped_dedupe_does_not_touch_other_owner(self, milvus_db):
        milvus_db.upsert(content_hash="SH", documents=[_doc("ad", "alice v1")], user_id="alice")
        milvus_db.upsert(content_hash="SH", documents=[_doc("bd", "bob v1")], user_id="bob")
        # Alice re-upserts under the shared hash. Bob's chunk must survive.
        milvus_db.upsert(content_hash="SH", documents=[_doc("ad", "alice v2")], user_id="alice")
        assert _owners(milvus_db) == ["alice", "bob"]
        assert _count(milvus_db) == 2

    def test_same_user_reupsert_replaces(self, milvus_db):
        milvus_db.upsert(content_hash="H", documents=[_doc("d", "v1")], user_id="alice")
        milvus_db.upsert(content_hash="H", documents=[_doc("d", "v2")], user_id="alice")
        assert _count(milvus_db) == 1

    def test_content_hash_exists_is_owner_scoped(self, milvus_db):
        milvus_db.insert(content_hash="CH", documents=[_doc("a", "alice")], user_id="alice")
        assert milvus_db.content_hash_exists("CH", user_id="alice") is True
        # Bob has no chunk under CH, so the scoped check must miss.
        assert milvus_db.content_hash_exists("CH", user_id="bob") is False
        # Unscoped (admin) check sees it.
        assert milvus_db.content_hash_exists("CH") is True

    def test_shared_upsert_does_not_wipe_scoped_owners(self, milvus_db):
        """A shared/admin re-ingest (``user_id=None``) under a hash that scoped
        owners already uploaded must scope its dedupe-delete to the shared bucket
        only — pre-fix it wiped every scoped owner sharing that content_hash."""
        milvus_db.upsert(content_hash="SAME", documents=[_doc("ad", "alice v1")], user_id="alice")
        milvus_db.upsert(content_hash="SAME", documents=[_doc("bd", "bob v1")], user_id="bob")
        # The wipe trigger: a shared re-ingest of the SAME content_hash.
        milvus_db.upsert(content_hash="SAME", documents=[_doc("sd", "shared v1")], user_id=None)
        assert _owners(milvus_db) == ["None", "alice", "bob"]
        assert milvus_db.content_hash_exists("SAME", user_id="alice") is True
        assert milvus_db.content_hash_exists("SAME", user_id="bob") is True

    async def test_async_reupsert_replaces_not_accumulates(self, milvus_db):
        await milvus_db.async_upsert(content_hash="H", documents=[_doc("d", "v1")], user_id="alice")
        await milvus_db.async_upsert(content_hash="H", documents=[_doc("d", "v2")], user_id="alice")
        assert _count(milvus_db) == 1

    async def test_async_scoped_dedupe_keeps_other_owner(self, milvus_db):
        await milvus_db.async_upsert(content_hash="SH", documents=[_doc("ad", "alice v1")], user_id="alice")
        await milvus_db.async_upsert(content_hash="SH", documents=[_doc("bd", "bob v1")], user_id="bob")
        await milvus_db.async_upsert(content_hash="SH", documents=[_doc("ad", "alice v2")], user_id="alice")
        assert _owners(milvus_db) == ["alice", "bob"]
        assert _count(milvus_db) == 2


class TestUpdateMetadataOwnershipGuard:
    """``update_metadata`` merges the caller's dict into the row. It must NOT let
    metadata={"user_id": ...} flip a chunk's owner — that would let a caller
    reassign ownership and either steal or leak the chunk."""

    def test_caller_cannot_reassign_owner(self, milvus_db):
        doc = _doc("md", "metadata test content", content_id="cid-1")
        milvus_db.insert(content_hash="hm", documents=[doc], user_id="alice")
        milvus_db.update_metadata("cid-1", {"user_id": "bob", "tag": "x"})
        assert _owners(milvus_db) == ["alice"]
