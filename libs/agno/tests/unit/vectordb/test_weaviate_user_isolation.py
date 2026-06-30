import uuid
from hashlib import md5
from typing import List

import pytest

weaviate = pytest.importorskip("weaviate")

from agno.knowledge.document import Document  # noqa: E402
from agno.vectordb.search import SearchType  # noqa: E402
from agno.vectordb.weaviate import Weaviate  # noqa: E402

TEST_COLLECTION = "IsolationTest"

# Non-default ports so we don't collide with a developer's local Weaviate.
EMBEDDED_PORT = 8079
EMBEDDED_GRPC_PORT = 50050
EMBEDDED_VERSION = "1.27.0"


class _DeterministicEmbedder:
    """A tiny embedder that needs no network or API key.

    The content steers the vector so distinct documents land in distinct
    buckets — that's all the isolation tests need, and it exposes a real async
    surface too."""

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
        document.usage = {"total_tokens": 1}

    async def async_embed(self, document, *args, **kwargs):
        document.embedding = self.get_embedding(document.content)
        document.usage = {"total_tokens": 1}


@pytest.fixture(scope="module")
def embedded_server():
    """Start one embedded Weaviate for the module and hold it open.

    The Weaviate class opens/closes its own local clients per operation; if the
    test owned a single shared client the class's ``close()`` calls would shut
    the embedded process down. Holding the server here keeps it alive."""
    try:
        server = weaviate.connect_to_embedded(
            version=EMBEDDED_VERSION,
            port=EMBEDDED_PORT,
            grpc_port=EMBEDDED_GRPC_PORT,
            # CI/dev disks can be tight; Weaviate flips a shard read-only at 90%
            # disk use by default, which fails index builds and vector search.
            # Raise the thresholds so the isolation tests can write and query.
            environment_variables={
                "DISK_USE_WARNING_PERCENTAGE": "99",
                "DISK_USE_READONLY_PERCENTAGE": "100",
            },
        )
    except Exception as e:  # pragma: no cover - environment dependent
        pytest.skip(f"Embedded Weaviate unavailable: {e}")

    # Make sure it actually came up before any test runs.
    try:
        if not server.is_ready():  # pragma: no cover
            server.close()
            pytest.skip("Embedded Weaviate did not become ready")
    except Exception as e:  # pragma: no cover
        pytest.skip(f"Embedded Weaviate not ready: {e}")

    yield server
    try:
        server.close()
    except Exception:
        pass


@pytest.fixture
def patched_local(monkeypatch, embedded_server):
    """Point the Weaviate class's local connectors at the embedded server.

    The class calls ``connect_to_local()`` / ``use_async_with_local()`` with no
    port; we redirect them to the embedded server's non-default ports so its
    open/close cycle reconnects to the running embedded instance."""
    real_local = weaviate.connect_to_local
    real_async_local = weaviate.use_async_with_local

    def _local(*args, **kwargs):
        kwargs.setdefault("port", EMBEDDED_PORT)
        kwargs.setdefault("grpc_port", EMBEDDED_GRPC_PORT)
        return real_local(**kwargs)

    def _async_local(*args, **kwargs):
        kwargs.setdefault("port", EMBEDDED_PORT)
        kwargs.setdefault("grpc_port", EMBEDDED_GRPC_PORT)
        return real_async_local(**kwargs)

    monkeypatch.setattr(weaviate, "connect_to_local", _local)
    monkeypatch.setattr(weaviate, "use_async_with_local", _async_local)
    yield


def _make_db(patched_local, search_type=SearchType.vector) -> Weaviate:
    db = Weaviate(
        collection=TEST_COLLECTION,
        local=True,
        embedder=_DeterministicEmbedder(),
        search_type=search_type,
    )
    # Always start from a clean collection so tests don't see each other's rows.
    try:
        db.drop()
    except Exception:
        pass
    db.create()
    return db


@pytest.fixture
def vector_db(patched_local):
    db = _make_db(patched_local, SearchType.vector)
    yield db
    try:
        db.drop()
    except Exception:
        pass


@pytest.fixture
def keyword_db(patched_local):
    db = _make_db(patched_local, SearchType.keyword)
    yield db
    try:
        db.drop()
    except Exception:
        pass


@pytest.fixture
def hybrid_db(patched_local):
    db = _make_db(patched_local, SearchType.hybrid)
    yield db
    try:
        db.drop()
    except Exception:
        pass


def _alice_docs() -> List[Document]:
    return [Document(name="alice-salary", content="Alice salary is 180k secret")]


def _bob_docs() -> List[Document]:
    return [Document(name="bob-salary", content="Bob salary is 215k secret")]


def _shared_docs() -> List[Document]:
    return [Document(name="company-holidays", content="The office salary policy is shared")]


def _owners(db) -> List:
    """Read the raw ``user_id`` property of every stored object via a fresh
    client, sorted with NULLs last for stable assertions."""
    client = weaviate.connect_to_local(port=EMBEDDED_PORT, grpc_port=EMBEDDED_GRPC_PORT)
    try:
        collection = client.collections.get(TEST_COLLECTION)
        objs = collection.query.fetch_objects(limit=100).objects
        return sorted(
            (o.properties.get(Weaviate.USER_ID_KEY) for o in objs),
            key=lambda x: (x is None, x),
        )
    finally:
        client.close()


def _count(db) -> int:
    client = weaviate.connect_to_local(port=EMBEDDED_PORT, grpc_port=EMBEDDED_GRPC_PORT)
    try:
        collection = client.collections.get(TEST_COLLECTION)
        return len(collection.query.fetch_objects(limit=1000).objects)
    finally:
        client.close()


class TestSchema:
    """The schema must expose ``user_id`` as a first-class property."""

    def test_collection_has_user_id_property(self, vector_db):
        client = weaviate.connect_to_local(port=EMBEDDED_PORT, grpc_port=EMBEDDED_GRPC_PORT)
        try:
            config = client.collections.get(TEST_COLLECTION).config.get()
            names = {p.name for p in config.properties}
            assert Weaviate.USER_ID_KEY in names
        finally:
            client.close()

    def test_user_id_key_constant(self):
        # Storage-compatibility marker: changing this orphans previously
        # written rows from the scope filter.
        assert Weaviate.USER_ID_KEY == "user_id"


class TestWriteStampsOwner:
    """Inserts must stamp the owner on the top-level ``user_id`` property."""

    def test_explicit_user_id_persisted(self, vector_db):
        vector_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")
        assert _owners(vector_db) == ["alice"]

    def test_none_user_id_persisted_as_null(self, vector_db):
        vector_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)
        assert _owners(vector_db) == [None]

    def test_user_id_omitted_defaults_to_null(self, vector_db):
        vector_db.insert(content_hash="h1", documents=_shared_docs())
        assert _owners(vector_db) == [None]


class TestVectorSearchIsolation:
    """The load-bearing test: alice sees her own + shared, never bob's."""

    @pytest.fixture
    def populated(self, vector_db):
        vector_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        vector_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        vector_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return vector_db

    def test_alice_sees_her_own(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in names

    def test_alice_sees_shared(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id="alice")}
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


class TestOwnerTokenizationIsolation:
    """A user_id that tokenizes (e.g. an Auth0 provider|sub) must match its owner
    exactly. With the default WORD tokenization the scope filter matches any owner
    whose id shares a token, leaking across users; the user_id property is declared
    with FIELD tokenization to prevent this."""

    @pytest.fixture
    def populated(self, vector_db):
        vector_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        vector_db.insert(
            content_hash="hx",
            documents=[Document(name="impostor-salary", content="Impostor salary is 999k secret")],
            user_id="auth0|alice",
        )
        return vector_db

    def test_alice_does_not_see_token_neighbor(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "impostor-salary" not in names

    def test_token_neighbor_does_not_see_alice(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id="auth0|alice")}
        assert "impostor-salary" in names
        assert "alice-salary" not in names


class TestKeywordSearchIsolation:
    """The scope filter must be applied to BM25 keyword search too."""

    @pytest.fixture
    def populated(self, keyword_db):
        keyword_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        keyword_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        keyword_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return keyword_db

    def test_alice_sees_own_and_shared(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "company-holidays" in names

    def test_alice_never_sees_bob(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id="alice")}
        assert "bob-salary" not in names

    def test_admin_sees_all(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id=None)}
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names


class TestHybridSearchIsolation:
    """The scope filter must be applied to hybrid search too."""

    @pytest.fixture
    def populated(self, hybrid_db):
        hybrid_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        hybrid_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        hybrid_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return hybrid_db

    def test_alice_sees_own_and_shared(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "company-holidays" in names

    def test_alice_never_sees_bob(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id="alice")}
        assert "bob-salary" not in names

    def test_admin_sees_all(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id=None)}
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names


class TestAsyncSearchIsolation:
    """Async paths must isolate identically across all three search modes.

    Embedded mode is a single real server, so the documents inserted via the
    sync path here are visible to the async search path."""

    @pytest.fixture
    def populated(self, vector_db):
        vector_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        vector_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        vector_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return vector_db

    async def test_async_vector_alice_isolated(self, populated):
        names = {d.name for d in await populated.async_search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "company-holidays" in names
        assert "bob-salary" not in names

    async def test_async_vector_admin_sees_all(self, populated):
        names = {d.name for d in await populated.async_search("salary", limit=10, user_id=None)}
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names

    async def test_async_keyword_alice_isolated(self, keyword_db):
        keyword_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        keyword_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        names = {d.name for d in await keyword_db.async_search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "bob-salary" not in names

    async def test_async_hybrid_alice_isolated(self, hybrid_db):
        hybrid_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        hybrid_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        names = {d.name for d in await hybrid_db.async_search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "bob-salary" not in names

    async def test_async_insert_stamps_owner(self, vector_db):
        await vector_db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        await vector_db.async_insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        assert _owners(vector_db) == ["alice", None]


class TestDeleteByContentIdIsolation:
    """``delete_by_content_id(content_id, user_id=...)`` must scope to the owner
    so a caller can't wipe another user's (or shared) chunks by guessing the id."""

    @pytest.fixture
    def populated(self, vector_db):
        alice_doc = Document(name="alice-doc", content="Alice secret content")
        alice_doc.content_id = "doc-1"
        bob_doc = Document(name="bob-doc", content="Bob secret content")
        bob_doc.content_id = "doc-1"
        shared_doc = Document(name="shared-doc", content="Shared content here")
        shared_doc.content_id = "doc-1"
        vector_db.insert(content_hash="ha", documents=[alice_doc], user_id="alice")
        vector_db.insert(content_hash="hb", documents=[bob_doc], user_id="bob")
        vector_db.insert(content_hash="hs", documents=[shared_doc], user_id=None)
        return vector_db

    def test_scoped_delete_only_removes_callers_chunks(self, populated):
        populated.delete_by_content_id("doc-1", user_id="bob")
        # Bob's chunk gone; alice's and the shared chunk survive.
        assert _owners(populated) == ["alice", None]

    def test_scoped_delete_does_not_touch_shared(self, populated):
        populated.delete_by_content_id("doc-1", user_id="alice")
        assert _owners(populated) == ["bob", None]

    def test_unscoped_delete_wipes_everyone(self, populated):
        populated.delete_by_content_id("doc-1", user_id=None)
        assert _count(populated) == 0

    def test_scoped_delete_no_owner_deletes_nothing(self, populated):
        populated.delete_by_content_id("doc-1", user_id="carol")
        assert _count(populated) == 3


class TestRecordUuidClobber:
    """The object UUID must fold in the owner. Weaviate upserts by UUID, so
    without the owner two users inserting IDENTICAL content under the SAME
    content_hash collide on one UUID and one silently overwrites the other."""

    def test_two_users_same_content_and_hash_coexist(self, vector_db):
        doc1 = Document(name="secret", content="The secret is 42")
        doc2 = Document(name="secret", content="The secret is 42")
        vector_db.insert(content_hash="SAME", documents=[doc1], user_id="alice")
        vector_db.insert(content_hash="SAME", documents=[doc2], user_id="bob")
        assert _owners(vector_db) == ["alice", "bob"]

    def test_clobbered_points_stay_isolated_on_search(self, vector_db):
        doc1 = Document(name="secret", content="The secret is 42")
        doc2 = Document(name="secret", content="The secret is 42")
        vector_db.insert(content_hash="SAME", documents=[doc1], user_id="alice")
        vector_db.insert(content_hash="SAME", documents=[doc2], user_id="bob")
        alice = {d.name for d in vector_db.search("secret", limit=10, user_id="alice")}
        bob = {d.name for d in vector_db.search("secret", limit=10, user_id="bob")}
        assert alice == {"secret"}
        assert bob == {"secret"}
        assert _count(vector_db) == 2

    def test_same_user_reupsert_same_hash_replaces(self, vector_db):
        # Weaviate's data.insert is create-only (a duplicate UUID errors), so
        # the same-content replace semantic belongs to upsert, which
        # dedupe-deletes the owner's prior chunks before re-inserting.
        doc1 = Document(name="d", content="content v1")
        doc2 = Document(name="d", content="content v1")
        vector_db.upsert(content_hash="H", documents=[doc1], user_id="alice")
        vector_db.upsert(content_hash="H", documents=[doc2], user_id="alice")
        assert _count(vector_db) == 1

    def test_shared_bucket_keeps_legacy_uuid(self, vector_db):
        legacy = uuid.UUID(hex=md5(b"x_H").hexdigest()[:32])
        assert vector_db._record_uuid("x", "H", None) == legacy
        assert vector_db._record_uuid("x", "H", "alice") != legacy


class TestUpsertDedupeIsolation:
    """``upsert`` dedupes by deleting prior chunks with the same content_hash
    before re-inserting. That delete must be SCOPED to the owner — otherwise
    Alice re-upserting wipes Bob's chunk that shares the same content_hash."""

    def test_scoped_dedupe_does_not_touch_other_owner(self, vector_db):
        vector_db.upsert(content_hash="SH", documents=[Document(name="ad", content="alice v1")], user_id="alice")
        vector_db.upsert(content_hash="SH", documents=[Document(name="bd", content="bob v1")], user_id="bob")
        vector_db.upsert(content_hash="SH", documents=[Document(name="ad", content="alice v2")], user_id="alice")
        assert _owners(vector_db) == ["alice", "bob"]
        assert _count(vector_db) == 2

    def test_same_user_reupsert_replaces(self, vector_db):
        vector_db.upsert(content_hash="H", documents=[Document(name="d", content="v1")], user_id="alice")
        vector_db.upsert(content_hash="H", documents=[Document(name="d", content="v2")], user_id="alice")
        assert _count(vector_db) == 1

    def test_shared_upsert_does_not_wipe_scoped_owners(self, vector_db):
        """A shared/admin re-ingest (``user_id=None``) under a hash that scoped
        owners already uploaded must scope its dedupe-delete to the shared bucket
        only — pre-fix it wiped every scoped owner sharing that content_hash."""
        vector_db.upsert(content_hash="SAME", documents=[Document(name="ad", content="alice v1")], user_id="alice")
        vector_db.upsert(content_hash="SAME", documents=[Document(name="bd", content="bob v1")], user_id="bob")
        # The wipe trigger: a shared re-ingest of the SAME content_hash.
        vector_db.upsert(content_hash="SAME", documents=[Document(name="sd", content="shared v1")], user_id=None)
        assert _owners(vector_db) == ["alice", "bob", None]
        assert vector_db.content_hash_exists("SAME", user_id="alice") is True
        assert vector_db.content_hash_exists("SAME", user_id="bob") is True

    async def test_async_scoped_dedupe_keeps_other_owner(self, vector_db):
        await vector_db.async_upsert(
            content_hash="SH", documents=[Document(name="ad", content="alice v1")], user_id="alice"
        )
        await vector_db.async_upsert(
            content_hash="SH", documents=[Document(name="bd", content="bob v1")], user_id="bob"
        )
        await vector_db.async_upsert(
            content_hash="SH", documents=[Document(name="ad", content="alice v2")], user_id="alice"
        )
        assert _owners(vector_db) == ["alice", "bob"]
        assert _count(vector_db) == 2


class TestUpdateMetadataOwnershipGuard:
    """``update_metadata`` must NOT let metadata={"user_id": ...} reassign a
    chunk's tenant — that would let a caller steal or leak the chunk."""

    @pytest.fixture
    def owned(self, vector_db):
        doc = Document(name="md", content="metadata test content")
        doc.content_id = "cid-1"
        vector_db.insert(content_hash="hm", documents=[doc], user_id="alice")
        return vector_db

    def test_caller_cannot_reassign_owner(self, owned):
        owned.update_metadata("cid-1", {"user_id": "bob", "tag": "x"})
        assert _owners(owned) == ["alice"]

    def test_owner_unchanged_alice_keeps_access(self, owned):
        owned.update_metadata("cid-1", {"user_id": "bob"})
        alice = {d.name for d in owned.search("metadata", limit=10, user_id="alice")}
        bob = {d.name for d in owned.search("metadata", limit=10, user_id="bob")}
        assert "md" in alice
        assert "md" not in bob


def test_port_constants_distinct():
    """Defensive: the embedded ports must not be the Weaviate defaults so a
    developer's running instance is never touched."""
    assert EMBEDDED_PORT != 8080
    assert EMBEDDED_GRPC_PORT != 50051
