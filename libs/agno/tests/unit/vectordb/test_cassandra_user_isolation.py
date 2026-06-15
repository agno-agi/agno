import uuid
from typing import List, Optional

import pytest

cassio = pytest.importorskip("cassio")
cassandra_cluster = pytest.importorskip("cassandra.cluster")

from cassandra.cluster import Cluster  # noqa: E402

from agno.knowledge.document import Document  # noqa: E402
from agno.vectordb.cassandra import Cassandra  # noqa: E402
from agno.vectordb.cassandra.cassandra import SHARED_USER_ID_VALUE, USER_ID_METADATA_KEY  # noqa: E402

# The adapter hardcodes a 1024-dim vector column, so the fake embedder must
# match — otherwise cassio rejects the insert.
DIM = 1024

# Connection target. A throwaway Cassandra is expected at this host/port (the
# isolation suite boots one on 9043 to avoid clashing with the default 9042).
CASSANDRA_HOST = "127.0.0.1"
CASSANDRA_PORT = 9043


class _DeterministicEmbedder:
    """A tiny embedder that needs no network or API key.

    The content steers the vector so distinct documents land in distinct
    buckets — that's all the isolation tests need, and it gives us a real async
    surface too. ``embed``/``async_embed`` set the embedding on the Document the
    way the adapter expects."""

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


def _server_available() -> bool:
    try:
        cluster = Cluster([CASSANDRA_HOST], port=CASSANDRA_PORT, connect_timeout=5)
        session = cluster.connect()
        session.shutdown()
        cluster.shutdown()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _server_available(),
    reason=f"No Cassandra reachable at {CASSANDRA_HOST}:{CASSANDRA_PORT}",
)


@pytest.fixture(scope="module")
def session():
    cluster = Cluster([CASSANDRA_HOST], port=CASSANDRA_PORT)
    sess = cluster.connect()
    yield sess
    sess.shutdown()
    cluster.shutdown()


@pytest.fixture
def cassandra_db(session):
    """A fresh keyspace + table per test, so each test's top-k is uncontended.

    cassio's global ``init`` is pointed at this keyspace before the adapter
    builds its table."""
    keyspace = f"iso_test_{uuid.uuid4().hex[:8]}"
    session.execute(
        f"CREATE KEYSPACE IF NOT EXISTS {keyspace} "
        "WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}"
    )
    cassio.init(session=session, keyspace=keyspace)
    db = Cassandra(
        table_name="vectors",
        keyspace=keyspace,
        embedder=_DeterministicEmbedder(),
        session=session,
    )
    yield db
    try:
        session.execute(f"DROP KEYSPACE IF EXISTS {keyspace}")
    except Exception:
        pass


def _doc(name: str, content: str, content_id: Optional[str] = None) -> Document:
    doc = Document(name=name, content=content)
    doc.content_id = content_id
    return doc


def _alice_docs() -> List[Document]:
    return [_doc("alice-salary", "Alice salary is 180k")]


def _bob_docs() -> List[Document]:
    return [_doc("bob-salary", "Bob salary is 215k")]


def _shared_docs() -> List[Document]:
    return [_doc("company-holidays", "The office is closed Jan 1")]


def _owners(db) -> List[str]:
    rows = db.session.execute(f"SELECT metadata_s FROM {db.keyspace}.{db.table_name} ALLOW FILTERING")
    return sorted(r.metadata_s.get(USER_ID_METADATA_KEY) for r in rows)


def _count(db) -> int:
    return db.session.execute(f"SELECT COUNT(*) FROM {db.keyspace}.{db.table_name}").one()[0]


def _owners_for_content_id(db, content_id: str) -> List[str]:
    rows = db.session.execute(f"SELECT metadata_s FROM {db.keyspace}.{db.table_name} ALLOW FILTERING")
    return sorted(r.metadata_s.get(USER_ID_METADATA_KEY) for r in rows if r.metadata_s.get("content_id") == content_id)


class TestStorageScheme:
    """Pin the storage contract. Changing these orphans previously written
    rows — the equality filter would stop matching them."""

    def test_constants(self, cassandra_db):
        assert USER_ID_METADATA_KEY == "user_id"
        assert SHARED_USER_ID_VALUE == "__shared__"

    def test_explicit_user_id_stamped_in_metadata(self, cassandra_db):
        cassandra_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")
        assert _owners(cassandra_db) == ["alice"]

    def test_none_user_id_stored_as_shared_sentinel(self, cassandra_db):
        """Shared chunks store the explicit sentinel (not an omitted key) so the
        shared-bucket equality query can find them."""
        cassandra_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)
        assert _owners(cassandra_db) == [SHARED_USER_ID_VALUE]

    def test_user_id_omitted_defaults_to_shared(self, cassandra_db):
        cassandra_db.insert(content_hash="h1", documents=_shared_docs())
        assert _owners(cassandra_db) == [SHARED_USER_ID_VALUE]

    def test_caller_cannot_spoof_owner_via_metadata(self, cassandra_db):
        """A caller's own ``user_id`` key in meta_data must not become the
        owner — the adapter strips it and sets the owner itself."""
        doc = _doc("spoof", "trying to spoof")
        doc.meta_data = {"user_id": "bob"}
        cassandra_db.insert(content_hash="h1", documents=[doc], user_id="alice")
        assert _owners(cassandra_db) == ["alice"]

    def test_user_id_not_surfaced_in_search_metadata(self, cassandra_db):
        cassandra_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")
        results = cassandra_db.search("salary", limit=10, user_id="alice")
        assert results
        assert all(USER_ID_METADATA_KEY not in d.meta_data for d in results)


class TestSearchIsolationContract:
    """The load-bearing test: alice's search returns her chunks plus shared
    chunks, but never bob's."""

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
        """The isolation contract. If this fails alice is retrieving bob's
        confidential chunks."""
        results = populated_db.search("salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "bob-salary" not in names
        for d in results:
            assert "Bob salary" not in d.content

    def test_bob_never_sees_alices_chunk(self, populated_db):
        names = {d.name for d in populated_db.search("salary", limit=10, user_id="bob")}
        assert "alice-salary" not in names

    def test_admin_sees_everything(self, populated_db):
        """``user_id=None`` at search time means no scope — admin view."""
        names = {d.name for d in populated_db.search("salary", limit=10, user_id=None)}
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names

    def test_union_only_returns_own_and_shared(self, populated_db):
        """The two-query union must return exactly own + shared and nothing
        else — proving it never reaches into another user's bucket."""
        names = {d.name for d in populated_db.search("salary", limit=10, user_id="alice")}
        assert names == {"alice-salary", "company-holidays"}


class TestUnionMergeOrdering:
    """The own + shared union re-sorts the two ANN result lists by cosine
    distance and truncates to ``limit``. A relevant own chunk must outrank an
    irrelevant shared chunk even when both buckets are populated."""

    def test_limit_is_respected_across_buckets(self, cassandra_db):
        for i in range(3):
            cassandra_db.insert(content_hash=f"a{i}", documents=[_doc(f"alice-{i}", f"alice doc {i}")], user_id="alice")
        for i in range(3):
            cassandra_db.insert(content_hash=f"s{i}", documents=[_doc(f"shared-{i}", f"shared doc {i}")], user_id=None)
        results = cassandra_db.search("alice doc 0", limit=2, user_id="alice")
        assert len(results) == 2

    def test_relevant_own_chunk_ranks_first(self, cassandra_db):
        cassandra_db.insert(
            content_hash="ha", documents=[_doc("alice-target", "the magic word zebra")], user_id="alice"
        )
        cassandra_db.insert(content_hash="hs", documents=[_doc("shared-noise", "unrelated content")], user_id=None)
        results = cassandra_db.search("the magic word zebra", limit=2, user_id="alice")
        assert results[0].name == "alice-target"


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
        """Bob deletes 'doc-1' under his scope — alice's and the shared chunk
        must survive."""
        assert populated_db.delete_by_content_id("doc-1", user_id="bob") is True
        assert _owners_for_content_id(populated_db, "doc-1") == [SHARED_USER_ID_VALUE, "alice"]

    def test_scoped_delete_does_not_touch_shared(self, populated_db):
        """A scoped delete must never remove shared (org-wide) content."""
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


class TestRowIdClobber:
    """The primary key must fold in the owner. The key is unique, so without the
    owner two users inserting IDENTICAL content under the SAME content_hash
    collide on one row and one silently overwrites (clobbers) the other."""

    def test_two_users_same_content_and_hash_coexist(self, cassandra_db):
        cassandra_db.insert(content_hash="SAME", documents=[_doc("secret", "The secret is 42")], user_id="alice")
        cassandra_db.insert(content_hash="SAME", documents=[_doc("secret", "The secret is 42")], user_id="bob")
        assert _owners(cassandra_db) == ["alice", "bob"]

    def test_clobbered_rows_stay_isolated_on_search(self, cassandra_db):
        cassandra_db.insert(content_hash="SAME", documents=[_doc("secret", "The secret is 42")], user_id="alice")
        cassandra_db.insert(content_hash="SAME", documents=[_doc("secret", "The secret is 42")], user_id="bob")
        alice = {d.name for d in cassandra_db.search("secret", limit=10, user_id="alice")}
        bob = {d.name for d in cassandra_db.search("secret", limit=10, user_id="bob")}
        assert alice == {"secret"}
        assert bob == {"secret"}
        assert _count(cassandra_db) == 2

    def test_shared_bucket_keeps_legacy_row_id(self, cassandra_db):
        """``user_id=None`` chunks keep the original doc id so previously
        persisted shared rows stay addressable; scoped rows get a folded id."""
        doc = _doc("d", "content")
        doc.id = "legacy-id"
        assert cassandra_db._row_id(doc, "H", None) == "legacy-id"
        assert cassandra_db._row_id(doc, "H", "alice") != "legacy-id"


class TestUpsertDedupeIsolation:
    """``upsert`` dedupes by deleting prior chunks with the same content_hash
    before re-inserting. That delete must be SCOPED to the owner — otherwise
    alice re-upserting wipes bob's chunk that shares the same content_hash."""

    def test_scoped_dedupe_does_not_touch_other_owner(self, cassandra_db):
        cassandra_db.upsert(content_hash="SH", documents=[_doc("ad", "alice v1")], user_id="alice")
        cassandra_db.upsert(content_hash="SH", documents=[_doc("bd", "bob v1")], user_id="bob")
        cassandra_db.upsert(content_hash="SH", documents=[_doc("ad", "alice v2")], user_id="alice")
        assert _owners(cassandra_db) == ["alice", "bob"]
        assert _count(cassandra_db) == 2

    def test_same_user_reupsert_replaces(self, cassandra_db):
        cassandra_db.upsert(content_hash="H", documents=[_doc("d", "v1")], user_id="alice")
        cassandra_db.upsert(content_hash="H", documents=[_doc("d", "v2")], user_id="alice")
        assert _count(cassandra_db) == 1

    def test_shared_reupsert_does_not_touch_scoped(self, cassandra_db):
        """A shared (None) re-upsert dedupes only shared rows, never a user's."""
        cassandra_db.upsert(content_hash="SH", documents=[_doc("ad", "alice v1")], user_id="alice")
        cassandra_db.upsert(content_hash="SH", documents=[_doc("sd", "shared v1")], user_id=None)
        cassandra_db.upsert(content_hash="SH", documents=[_doc("sd", "shared v2")], user_id=None)
        assert _owners(cassandra_db) == [SHARED_USER_ID_VALUE, "alice"]


class TestContentHashExistsScope:
    def test_scoped_exists_only_sees_owner(self, cassandra_db):
        cassandra_db.insert(content_hash="H", documents=[_doc("ad", "alice")], user_id="alice")
        assert cassandra_db.content_hash_exists("H", user_id="alice") is True
        assert cassandra_db.content_hash_exists("H", user_id="bob") is False
        # Unscoped sees it regardless of owner.
        assert cassandra_db.content_hash_exists("H") is True


class TestUpdateMetadataOwnershipGuard:
    """``update_metadata`` merges the caller's dict into the row. It must NOT
    let metadata={'user_id': ...} flip a chunk's owner."""

    def test_caller_cannot_reassign_owner(self, cassandra_db):
        doc = _doc("md", "metadata content", "cid-1")
        cassandra_db.insert(content_hash="hm", documents=[doc], user_id="alice")
        cassandra_db.update_metadata("cid-1", {"user_id": "bob", "tag": "x"})
        assert _owners(cassandra_db) == ["alice"]

    def test_owner_unchanged_alice_keeps_bob_locked_out(self, cassandra_db):
        doc = _doc("md", "metadata content", "cid-1")
        cassandra_db.insert(content_hash="hm", documents=[doc], user_id="alice")
        cassandra_db.update_metadata("cid-1", {"user_id": "bob"})
        alice = {d.name for d in cassandra_db.search("metadata content", limit=10, user_id="alice")}
        bob = {d.name for d in cassandra_db.search("metadata content", limit=10, user_id="bob")}
        assert "md" in alice
        assert "md" not in bob


class TestAsyncIsolation:
    """The async adapter wraps the sync paths in threads — verify the contract
    holds through the async surface too."""

    async def test_async_alice_sees_own_and_shared_not_bob(self, cassandra_db):
        await cassandra_db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        await cassandra_db.async_insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        await cassandra_db.async_insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        alice = {d.name for d in await cassandra_db.async_search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in alice
        assert "company-holidays" in alice
        assert "bob-salary" not in alice

    async def test_async_admin_sees_all(self, cassandra_db):
        await cassandra_db.async_insert(content_hash="ha", documents=[_doc("ax", "alice")], user_id="alice")
        await cassandra_db.async_insert(content_hash="hb", documents=[_doc("bx", "bob")], user_id="bob")
        await cassandra_db.async_insert(content_hash="hs", documents=[_doc("sx", "shared")], user_id=None)
        names = {d.name for d in await cassandra_db.async_search("anything", limit=10, user_id=None)}
        assert names == {"ax", "bx", "sx"}

    async def test_async_clobber_coexist(self, cassandra_db):
        await cassandra_db.async_insert(
            content_hash="SAME", documents=[_doc("secret", "The secret is 42")], user_id="alice"
        )
        await cassandra_db.async_insert(
            content_hash="SAME", documents=[_doc("secret", "The secret is 42")], user_id="bob"
        )
        assert _owners(cassandra_db) == ["alice", "bob"]

    async def test_async_scoped_reupsert_keeps_other_owner(self, cassandra_db):
        await cassandra_db.async_upsert(content_hash="SH", documents=[_doc("ad", "alice v1")], user_id="alice")
        await cassandra_db.async_upsert(content_hash="SH", documents=[_doc("bd", "bob v1")], user_id="bob")
        await cassandra_db.async_upsert(content_hash="SH", documents=[_doc("ad", "alice v2")], user_id="alice")
        assert _owners(cassandra_db) == ["alice", "bob"]
        assert _count(cassandra_db) == 2
