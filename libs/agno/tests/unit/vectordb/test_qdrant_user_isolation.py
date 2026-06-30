from typing import List
from unittest.mock import patch

import pytest

from agno.knowledge.document import Document
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

TEST_COLLECTION = "isolation_test"


class _DeterministicEmbedder:
    """A tiny embedder that needs no network or API key.

    The content steers the vector so distinct documents land in distinct
    buckets — that's all the isolation tests need, and it gives us a real
    async surface too (the session ``mock_embedder`` is sync-only)."""

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

    def embed(self, *args, **kwargs):
        pass

    async def async_embed(self, *args, **kwargs):
        pass


class _FakeSparseEncoder:
    """Stand-in for fastembed's sparse encoder so hybrid tests don't need the
    fastembed extra or a model download. It returns one constant sparse vector,
    which makes every chunk a hybrid candidate — exactly what we want when
    asserting that the SCOPE (not relevance) is what filters out other users."""

    def embed(self, texts):
        class _SparseVec:
            def as_object(self):
                return {"indices": [0], "values": [1.0]}

        return [_SparseVec() for _ in texts]


@pytest.fixture
def qdrant_db(mock_embedder):
    """A fresh Qdrant per test, in-memory so no cleanup is required."""
    db = Qdrant(
        collection=TEST_COLLECTION,
        location=":memory:",
        embedder=mock_embedder,
    )
    db.create()
    yield db
    try:
        db.drop()
    except Exception:
        pass


@pytest.fixture
def qdrant_db_det():
    """A fresh in-memory Qdrant backed by the deterministic embedder so the
    async insert path (which calls ``async_embed``) and direct upserts work
    without mocking the DB itself."""
    db = Qdrant(
        collection=TEST_COLLECTION,
        location=":memory:",
        embedder=_DeterministicEmbedder(),
    )
    db.create()
    yield db
    try:
        db.drop()
    except Exception:
        pass


@pytest.fixture
def qdrant_hybrid_db():
    """A fresh in-memory hybrid Qdrant. The sparse encoder is patched at
    construction so no fastembed model is downloaded; the test asserts the
    scope filter — not relevance — is what isolates tenants."""
    pytest.importorskip("fastembed")
    with patch("fastembed.SparseTextEmbedding", return_value=_FakeSparseEncoder()):
        db = Qdrant(
            collection=TEST_COLLECTION,
            location=":memory:",
            embedder=_DeterministicEmbedder(),
            search_type=SearchType.hybrid,
        )
    db.sparse_encoder = _FakeSparseEncoder()
    db.create()
    yield db
    try:
        db.drop()
    except Exception:
        pass


def _embedded(name: str, content: str) -> Document:
    """A Document with a precomputed deterministic embedding so direct
    ``insert`` calls (which expect ``document.embedding`` for vector search)
    work without an embedder round-trip."""
    doc = Document(name=name, content=content)
    doc.embedding = _DeterministicEmbedder().get_embedding(content)
    return doc


def _owners(db) -> List:
    points, _ = db.client.scroll(collection_name=TEST_COLLECTION, limit=100, with_payload=True)
    return sorted((p.payload.get(Qdrant.USER_ID_KEY) for p in points), key=lambda x: (x is None, x))


async def _async_owners(db) -> List:
    # In ``:memory:`` mode the sync and async clients are independent stores,
    # so async tests must read through the async client they wrote with.
    points, _ = await db.async_client.scroll(collection_name=TEST_COLLECTION, limit=100, with_payload=True)
    return sorted((p.payload.get(Qdrant.USER_ID_KEY) for p in points), key=lambda x: (x is None, x))


async def _async_count(db) -> int:
    result = await db.async_client.count(collection_name=TEST_COLLECTION, exact=True)
    return result.count


def _alice_docs() -> List[Document]:
    return [Document(name="alice-salary", content="Alice's salary is $180k.")]


def _bob_docs() -> List[Document]:
    return [Document(name="bob-salary", content="Bob's salary is $215k.")]


def _shared_docs() -> List[Document]:
    return [Document(name="company-holidays", content="The office is closed Jan 1.")]


class TestPayloadHasUserIdKey:
    """Pin the contract: ``user_id`` is a top-level payload key, not nested
    inside ``meta_data``. The payload index relies on this — moving it into
    a sub-dict would silently degrade reads from O(tenant) back to O(N)."""

    def test_user_id_key_constant_is_user_id(self):
        # Storage compatibility marker. If this changes, every previously
        # persisted row's user_id stops being readable by the filter.
        assert Qdrant.USER_ID_KEY == "user_id"

    def test_explicit_user_id_persisted_top_level(self, qdrant_db):
        qdrant_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")

        # Scroll the raw payload to verify the top-level key.
        points, _ = qdrant_db.client.scroll(collection_name=TEST_COLLECTION, limit=10, with_payload=True)
        assert len(points) == 1
        assert points[0].payload[Qdrant.USER_ID_KEY] == "alice"

    def test_none_user_id_persisted_as_null(self, qdrant_db):
        """Shared chunks store ``None`` in ``user_id``. The scope filter
        uses IsEmptyCondition, which matches both None and absent."""
        qdrant_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)

        points, _ = qdrant_db.client.scroll(collection_name=TEST_COLLECTION, limit=10, with_payload=True)
        assert len(points) == 1
        assert points[0].payload[Qdrant.USER_ID_KEY] is None

    def test_user_id_omitted_defaults_to_null(self, qdrant_db):
        """Backwards-compatible: callers that never pass ``user_id`` get
        NULL (shared) — they're effectively opting out of isolation."""
        qdrant_db.insert(content_hash="h1", documents=_shared_docs())

        points, _ = qdrant_db.client.scroll(collection_name=TEST_COLLECTION, limit=10, with_payload=True)
        assert points[0].payload[Qdrant.USER_ID_KEY] is None


class TestUserScopeFilter:
    """The scope-filter builder is small enough to unit-test directly. We
    catch the OR semantics and the shared-NULL pattern without spinning
    up the DB at all."""

    def test_none_returns_no_filter(self, qdrant_db):
        assert qdrant_db._user_scope_filter(None) is None

    def test_simple_alice_filter_has_should_with_two_conditions(self, qdrant_db):
        # OR ("should") between: user_id == alice  OR  is_empty(user_id).
        f = qdrant_db._user_scope_filter("alice")
        assert f is not None
        # Pydantic model — exercise via repr/dump to keep the test stable
        # across qdrant-client versions.
        dumped = f.model_dump(exclude_none=True)
        assert "should" in dumped
        assert len(dumped["should"]) == 2

    def test_merge_with_no_base_returns_scope_unchanged(self, qdrant_db):
        scope = qdrant_db._user_scope_filter("alice")
        assert qdrant_db._merge_filters(None, scope) is scope

    def test_merge_with_no_scope_returns_base_unchanged(self, qdrant_db):
        from qdrant_client.http import models

        base = models.Filter(must=[models.FieldCondition(key="meta_data.tag", match=models.MatchValue(value="x"))])
        assert qdrant_db._merge_filters(base, None) is base


class TestSearchIsolationContract:
    """alice's search returns her chunks plus shared chunks, but never bob's."""

    @pytest.fixture
    def populated_db(self, qdrant_db):
        """Three rows: one alice, one bob, one shared (NULL)."""
        qdrant_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        qdrant_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        qdrant_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return qdrant_db

    def test_alice_sees_her_own_chunk(self, populated_db):
        results = populated_db.search(query="salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "alice-salary" in names

    def test_alice_sees_shared_chunk(self, populated_db):
        results = populated_db.search(query="anything", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "company-holidays" in names

    def test_alice_never_sees_bobs_chunk(self, populated_db):
        """The isolation contract. If this fails the whole feature is
        broken — alice would be retrieving bob's confidential chunks."""
        results = populated_db.search(query="salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "bob-salary" not in names
        # Also check content.
        for d in results:
            assert "Bob's salary" not in d.content

    def test_bob_never_sees_alices_chunk(self, populated_db):
        results = populated_db.search(query="salary", limit=10, user_id="bob")
        names = {d.name for d in results}
        assert "alice-salary" not in names

    def test_admin_sees_everything(self, populated_db):
        """``user_id=None`` at search time means no scope — admin view."""
        results = populated_db.search(query="anything", limit=10, user_id=None)
        names = {d.name for d in results}
        assert "alice-salary" in names
        assert "bob-salary" in names
        assert "company-holidays" in names


class TestDeleteByContentIdIsolation:
    """``delete_by_content_id(content_id, user_id=...)`` must scope the
    delete to the caller's chunks — otherwise Bob could guess Alice's
    content_id and wipe her chunks.

    Qdrant scopes via a ``must`` filter combining ``content_id`` AND
    ``user_id`` on the server side.
    """

    @pytest.fixture
    def populated_db(self, qdrant_db):
        """Two users own chunks under the SAME content_id 'doc-1'. The
        adversarial scenario — Bob guesses the id and tries to delete it.
        Without ``user_id`` scoping he'd wipe Alice's row too."""
        alice_doc = Document(name="alice-doc", content="Alice's secret.")
        alice_doc.content_id = "doc-1"
        bob_doc = Document(name="bob-doc", content="Bob's secret.")
        bob_doc.content_id = "doc-1"

        qdrant_db.insert(content_hash="h-alice", documents=[alice_doc], user_id="alice")
        qdrant_db.insert(content_hash="h-bob", documents=[bob_doc], user_id="bob")
        return qdrant_db

    def _owners(self, db):
        points, _ = db.client.scroll(collection_name=TEST_COLLECTION, limit=100, with_payload=True)
        return sorted(p.payload[Qdrant.USER_ID_KEY] for p in points)

    def test_scoped_delete_only_removes_callers_chunks(self, populated_db):
        """Bob asks to delete 'doc-1' under his own scope — Alice's chunk
        must remain."""
        populated_db.delete_by_content_id("doc-1", user_id="bob")

        assert self._owners(populated_db) == ["alice"], "Isolation broken: bob's scoped delete touched alice's chunks"

    def test_alice_can_delete_her_own(self, populated_db):
        populated_db.delete_by_content_id("doc-1", user_id="alice")
        assert self._owners(populated_db) == ["bob"]

    def test_unscoped_delete_wipes_everyone(self, populated_db):
        """Legacy behaviour: ``user_id=None`` deletes across all owners.
        Pin it so we notice if the default semantics change."""
        populated_db.delete_by_content_id("doc-1", user_id=None)

        assert populated_db.get_count() == 0

    def test_scoped_delete_misses_when_user_does_not_own_anything(self, populated_db):
        """Carol has no chunks. Her scoped delete of doc-1 does nothing."""
        populated_db.delete_by_content_id("doc-1", user_id="carol")
        assert populated_db.get_count() == 2


class TestPointIdClobber:
    """A point's id must fold in the owner. Qdrant upserts by id, so without
    the owner two users inserting IDENTICAL content under the SAME
    ``content_hash`` collide on one id and one silently overwrites the other.

    The vector DB is a public API: it has to stay correct even when a caller
    hands it the same content_hash for two different users."""

    def test_two_users_same_content_and_hash_coexist(self, qdrant_db_det):
        """The clobber regression. Pre-fix this left exactly ONE point."""
        qdrant_db_det.insert(content_hash="SAME", documents=[_embedded("secret", "The secret is 42.")], user_id="alice")
        qdrant_db_det.insert(content_hash="SAME", documents=[_embedded("secret", "The secret is 42.")], user_id="bob")

        assert _owners(qdrant_db_det) == ["alice", "bob"], "Clobber: a user's point overwrote another's"

    def test_clobbered_points_stay_isolated_on_search(self, qdrant_db_det):
        qdrant_db_det.insert(content_hash="SAME", documents=[_embedded("secret", "The secret is 42.")], user_id="alice")
        qdrant_db_det.insert(content_hash="SAME", documents=[_embedded("secret", "The secret is 42.")], user_id="bob")

        alice = {d.name for d in qdrant_db_det.search("secret", limit=10, user_id="alice")}
        bob = {d.name for d in qdrant_db_det.search("secret", limit=10, user_id="bob")}
        # Each sees a chunk named "secret" — but it's their OWN point, and the
        # count proves the other's point still exists separately.
        assert alice == {"secret"}
        assert bob == {"secret"}
        assert qdrant_db_det.get_count() == 2

    def test_same_user_reinsert_same_hash_replaces(self, qdrant_db_det):
        """Same owner + same content + same hash is the SAME point id, so a
        re-insert replaces in place rather than duplicating."""
        qdrant_db_det.insert(content_hash="H", documents=[_embedded("d", "content v1")], user_id="alice")
        qdrant_db_det.insert(content_hash="H", documents=[_embedded("d", "content v1")], user_id="alice")
        assert qdrant_db_det.get_count() == 1

    def test_shared_bucket_keeps_legacy_id(self, qdrant_db_det):
        """``user_id=None`` chunks keep the two-part id so previously persisted
        shared points stay addressable."""
        legacy = __import__("hashlib").md5(b"x_H").hexdigest()
        assert qdrant_db_det._point_id("x", "H", None) == legacy
        assert qdrant_db_det._point_id("x", "H", "alice") != legacy


class TestUpsertDedupeIsolation:
    """``upsert`` dedupes by deleting prior chunks with the same content_hash
    before re-inserting. That delete must be SCOPED to the owner — otherwise
    Alice re-upserting her content wipes Bob's chunk that happens to carry the
    same content_hash (a public-API caller can pass any hash)."""

    def test_scoped_dedupe_does_not_touch_other_owner(self, qdrant_db_det):
        qdrant_db_det.upsert(content_hash="SH", documents=[_embedded("ad", "alice v1")], user_id="alice")
        qdrant_db_det.upsert(content_hash="SH", documents=[_embedded("bd", "bob v1")], user_id="bob")
        # Alice re-upserts under the shared hash. Bob's chunk must survive.
        qdrant_db_det.upsert(content_hash="SH", documents=[_embedded("ad", "alice v2")], user_id="alice")

        assert _owners(qdrant_db_det) == ["alice", "bob"]
        assert qdrant_db_det.get_count() == 2

    def test_same_user_reupsert_replaces(self, qdrant_db_det):
        qdrant_db_det.upsert(content_hash="H", documents=[_embedded("d", "v1")], user_id="alice")
        qdrant_db_det.upsert(content_hash="H", documents=[_embedded("d", "v2")], user_id="alice")
        assert qdrant_db_det.get_count() == 1

    def test_shared_upsert_does_not_wipe_scoped_owners(self, qdrant_db_det):
        """A shared/admin re-ingest (``user_id=None``) under a hash that scoped
        owners already uploaded must scope its dedupe-delete to the shared bucket
        only — pre-fix it wiped every scoped owner sharing that content_hash."""
        qdrant_db_det.upsert(content_hash="SAME", documents=[_embedded("ad", "alice v1")], user_id="alice")
        qdrant_db_det.upsert(content_hash="SAME", documents=[_embedded("bd", "bob v1")], user_id="bob")
        # The wipe trigger: a shared re-ingest of the SAME content_hash.
        qdrant_db_det.upsert(content_hash="SAME", documents=[_embedded("sd", "shared v1")], user_id=None)

        assert _owners(qdrant_db_det) == ["alice", "bob", None]
        assert qdrant_db_det.content_hash_exists("SAME", user_id="alice") is True
        assert qdrant_db_det.content_hash_exists("SAME", user_id="bob") is True


class TestAsyncUpsertDedupe:
    """``async_upsert`` historically skipped the dedupe-delete that sync
    ``upsert`` performs, so async re-upserts accumulated stale chunks. These
    pin it to the sync behaviour."""

    async def test_async_reupsert_replaces_not_accumulates(self, qdrant_db_det):
        await qdrant_db_det.async_create()
        await qdrant_db_det.async_upsert(content_hash="H", documents=[_embedded("d", "v1")], user_id="alice")
        await qdrant_db_det.async_upsert(content_hash="H", documents=[_embedded("d", "v2")], user_id="alice")
        assert await _async_count(qdrant_db_det) == 1

    async def test_async_scoped_dedupe_keeps_other_owner(self, qdrant_db_det):
        await qdrant_db_det.async_create()
        await qdrant_db_det.async_upsert(content_hash="SH", documents=[_embedded("ad", "alice v1")], user_id="alice")
        await qdrant_db_det.async_upsert(content_hash="SH", documents=[_embedded("bd", "bob v1")], user_id="bob")
        await qdrant_db_det.async_upsert(content_hash="SH", documents=[_embedded("ad", "alice v2")], user_id="alice")

        assert await _async_owners(qdrant_db_det) == ["alice", "bob"]
        assert await _async_count(qdrant_db_det) == 2

    async def test_async_clobber_coexist(self, qdrant_db_det):
        await qdrant_db_det.async_create()
        await qdrant_db_det.async_insert(
            content_hash="SAME", documents=[_embedded("secret", "The secret is 42.")], user_id="alice"
        )
        await qdrant_db_det.async_insert(
            content_hash="SAME", documents=[_embedded("secret", "The secret is 42.")], user_id="bob"
        )
        assert await _async_owners(qdrant_db_det) == ["alice", "bob"]


class TestHybridSearchScope:
    """Hybrid search runs each branch as a Prefetch. The scope filter must be
    set on EACH prefetch, not only the root query_filter: QdrantLocal does not
    propagate the root filter into prefetch branches, so a root-only filter
    leaked other users' chunks under local/in-memory mode."""

    @pytest.fixture
    def populated(self, qdrant_hybrid_db):
        qdrant_hybrid_db.insert(
            content_hash="ha", documents=[_embedded("alice-salary", "Alice salary 180k")], user_id="alice"
        )
        qdrant_hybrid_db.insert(
            content_hash="hb", documents=[_embedded("bob-salary", "Bob salary 215k")], user_id="bob"
        )
        qdrant_hybrid_db.insert(
            content_hash="hs", documents=[_embedded("company-holidays", "office closed Jan 1")], user_id=None
        )
        return qdrant_hybrid_db

    def test_alice_sees_own_and_shared(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "company-holidays" in names

    def test_alice_never_sees_bob_in_hybrid(self, populated):
        """The leak. Pre-fix bob-salary surfaced in alice's hybrid results
        under in-memory mode."""
        names = {d.name for d in populated.search("salary", limit=10, user_id="alice")}
        assert "bob-salary" not in names

    def test_admin_sees_all_in_hybrid(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id=None)}
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names

    async def test_async_hybrid_no_leak(self, qdrant_hybrid_db):
        await qdrant_hybrid_db.async_create()
        await qdrant_hybrid_db.async_insert(
            content_hash="ha", documents=[_embedded("alice-salary", "Alice salary")], user_id="alice"
        )
        await qdrant_hybrid_db.async_insert(
            content_hash="hb", documents=[_embedded("bob-salary", "Bob salary")], user_id="bob"
        )
        names = {d.name for d in await qdrant_hybrid_db.async_search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "bob-salary" not in names


class TestUpdateMetadataOwnershipGuard:
    """``update_metadata`` merges the caller's dict into the payload. It must
    NOT let metadata={"user_id": ...} flip a chunk's tenant — that would let a
    caller reassign ownership and either steal or leak the chunk."""

    @pytest.fixture
    def owned(self, qdrant_db_det):
        doc = _embedded("md", "metadata test content")
        doc.content_id = "cid-1"
        qdrant_db_det.insert(content_hash="hm", documents=[doc], user_id="alice")
        return qdrant_db_det

    def test_caller_cannot_reassign_owner(self, owned):
        owned.update_metadata("cid-1", {"user_id": "bob", "tag": "x"})
        assert _owners(owned) == ["alice"], "update_metadata reassigned the chunk's tenant"

    def test_owner_unchanged_alice_keeps_access(self, owned):
        owned.update_metadata("cid-1", {"user_id": "bob"})
        alice = {d.name for d in owned.search("metadata", limit=10, user_id="alice")}
        bob = {d.name for d in owned.search("metadata", limit=10, user_id="bob")}
        assert "md" in alice
        assert "md" not in bob

    def test_legitimate_metadata_still_applied(self, owned):
        owned.update_metadata("cid-1", {"tag": "x", "user_id": "bob"})
        points, _ = owned.client.scroll(collection_name=TEST_COLLECTION, limit=10, with_payload=True)
        assert points[0].payload.get("tag") == "x"
