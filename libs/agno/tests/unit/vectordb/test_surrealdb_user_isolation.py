import os
import uuid

import pytest

pytest.importorskip("surrealdb")

from surrealdb import AsyncSurreal, Surreal  # noqa: E402

from agno.knowledge.document import Document  # noqa: E402
from agno.vectordb.surrealdb import SurrealDb  # noqa: E402

SURREALDB_URL = os.environ.get("SURREALDB_TEST_URL", "ws://localhost:8001/rpc")
SURREALDB_USER = os.environ.get("SURREALDB_TEST_USER", "root")
SURREALDB_PASSWORD = os.environ.get("SURREALDB_TEST_PASSWORD", "root")
SURREALDB_NAMESPACE = "isolation_test_ns"
SURREALDB_DATABASE = "isolation_test_db"


def _server_reachable() -> bool:
    """Probe the configured SurrealDB so the whole module skips when it's down."""
    try:
        client = Surreal(SURREALDB_URL)
        client.signin({"username": SURREALDB_USER, "password": SURREALDB_PASSWORD})
        client.use(SURREALDB_NAMESPACE, SURREALDB_DATABASE)
        client.query("RETURN 1;")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _server_reachable(), reason="SurrealDB server not reachable")


class _DeterministicEmbedder:
    """A tiny embedder that needs no network or API key.

    The content steers the vector so distinct documents land in distinct
    buckets — that's all the isolation tests need, and it gives us a real async
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

    def embed(self, *args, **kwargs):
        pass

    async def async_embed(self, *args, **kwargs):
        pass


def _unique_collection() -> str:
    return "iso_" + uuid.uuid4().hex[:10]


@pytest.fixture
def surreal_db():
    """A fresh sync SurrealDb on a per-test table, dropped on teardown."""
    client = Surreal(SURREALDB_URL)
    client.signin({"username": SURREALDB_USER, "password": SURREALDB_PASSWORD})
    client.use(SURREALDB_NAMESPACE, SURREALDB_DATABASE)
    collection = _unique_collection()
    db = SurrealDb(client=client, collection=collection, embedder=_DeterministicEmbedder())
    db.create()
    yield db
    try:
        db.drop()
    except Exception:
        pass


@pytest.fixture
async def async_surreal_db():
    """A fresh async SurrealDb on a per-test table, dropped on teardown."""
    client = AsyncSurreal(SURREALDB_URL)
    await client.signin({"username": SURREALDB_USER, "password": SURREALDB_PASSWORD})
    await client.use(SURREALDB_NAMESPACE, SURREALDB_DATABASE)
    collection = _unique_collection()
    db = SurrealDb(async_client=client, collection=collection, embedder=_DeterministicEmbedder())
    await db.async_create()
    yield db
    try:
        await db.async_drop()
    except Exception:
        pass


def _doc(content: str) -> Document:
    return Document(content=content)


def _raw_owners(db) -> list:
    """Read the raw ``user_id`` of every row through the sync client."""
    rows = db.client.query(f"SELECT user_id FROM {db.collection} ORDER BY user_id;")
    return sorted((r.get("user_id") for r in rows), key=lambda x: (x is None, x))


def _count(db) -> int:
    rows = db.client.query(f"SELECT count() AS n FROM {db.collection} GROUP ALL;")
    return rows[0]["n"] if rows else 0


async def _async_raw_owners(db) -> list:
    rows = await db.async_client.query(f"SELECT user_id FROM {db.collection} ORDER BY user_id;")
    return sorted((r.get("user_id") for r in rows), key=lambda x: (x is None, x))


async def _async_count(db) -> int:
    rows = await db.async_client.query(f"SELECT count() AS n FROM {db.collection} GROUP ALL;")
    return rows[0]["n"] if rows else 0


# ---------------------------------------------------------------------------
# Pure-function contract (no server needed beyond import)
# ---------------------------------------------------------------------------
class TestScopeConditionBuilder:
    """The scope/id builders are small enough to unit-test directly."""

    def test_none_user_id_yields_no_scope(self):
        assert SurrealDb._user_scope_condition(None) == ""
        assert SurrealDb._user_scope_condition("") == ""

    def test_scoped_user_id_is_own_or_shared(self):
        # OR-ed: caller's own chunks OR the shared (NONE-owned) bucket.
        cond = SurrealDb._user_scope_condition("alice")
        assert cond == "AND (user_id = $scope_user_id OR user_id = NONE)"
        # The value is bound — never interpolated.
        assert "alice" not in cond

    def test_owner_exact_condition_excludes_shared(self):
        # Dedupe/delete scope is EXACT — it must not include the NONE bucket.
        cond = SurrealDb._owner_exact_condition("alice")
        assert cond == "AND user_id = $user_id"
        assert "NONE" not in cond
        assert SurrealDb._owner_exact_condition(None) == ""

    def test_record_id_folds_owner_and_keeps_legacy_shared(self):
        from hashlib import md5

        legacy = md5(b"base_H").hexdigest()
        # Shared bucket keeps the legacy two-part id so old rows stay addressable.
        assert SurrealDb._record_id("base", "H", None) == legacy
        # Scoped rows fold the owner in, so they differ from the shared id...
        assert SurrealDb._record_id("base", "H", "alice") != legacy
        # ...and from each other.
        assert SurrealDb._record_id("base", "H", "alice") != SurrealDb._record_id("base", "H", "bob")


# ---------------------------------------------------------------------------
# Storage: user_id is a first-class field, not nested in meta_data
# ---------------------------------------------------------------------------
class TestUserIdStoredAsField:
    def test_explicit_user_id_stored_top_level(self, surreal_db):
        surreal_db.insert(content_hash="h1", documents=[_doc("alice content")], user_id="alice")
        rows = surreal_db.client.query(f"SELECT user_id, meta_data FROM {surreal_db.collection};")
        assert rows[0]["user_id"] == "alice"
        # Not smuggled into the caller-controlled metadata blob.
        assert rows[0]["meta_data"].get("user_id") is None

    def test_none_user_id_stored_as_none(self, surreal_db):
        surreal_db.insert(content_hash="h1", documents=[_doc("shared content")], user_id=None)
        rows = surreal_db.client.query(f"SELECT user_id FROM {surreal_db.collection};")
        assert rows[0]["user_id"] is None

    def test_omitted_user_id_defaults_to_shared(self, surreal_db):
        surreal_db.insert(content_hash="h1", documents=[_doc("shared content")])
        rows = surreal_db.client.query(f"SELECT user_id FROM {surreal_db.collection};")
        assert rows[0]["user_id"] is None

    def test_empty_string_user_id_normalized_to_shared(self, surreal_db):
        surreal_db.insert(content_hash="h1", documents=[_doc("shared content")], user_id="")
        rows = surreal_db.client.query(f"SELECT user_id FROM {surreal_db.collection};")
        assert rows[0]["user_id"] is None


# ---------------------------------------------------------------------------
# The load-bearing isolation contract
# ---------------------------------------------------------------------------
class TestSearchIsolationContract:
    @pytest.fixture
    def populated(self, surreal_db):
        surreal_db.insert(content_hash="ha", documents=[_doc("Alice salary is 180k")], user_id="alice")
        surreal_db.insert(content_hash="hb", documents=[_doc("Bob salary is 215k")], user_id="bob")
        surreal_db.insert(content_hash="hs", documents=[_doc("Office closed Jan 1")], user_id=None)
        return surreal_db

    def test_alice_sees_her_own_chunk(self, populated):
        contents = {d.content for d in populated.search("salary", limit=10, user_id="alice")}
        assert "Alice salary is 180k" in contents

    def test_alice_sees_shared_chunk(self, populated):
        contents = {d.content for d in populated.search("office", limit=10, user_id="alice")}
        assert "Office closed Jan 1" in contents

    def test_alice_never_sees_bobs_chunk(self, populated):
        contents = {d.content for d in populated.search("salary", limit=10, user_id="alice")}
        assert "Bob salary is 215k" not in contents

    def test_bob_never_sees_alices_chunk(self, populated):
        contents = {d.content for d in populated.search("salary", limit=10, user_id="bob")}
        assert "Alice salary is 180k" not in contents

    def test_admin_sees_everything(self, populated):
        contents = {d.content for d in populated.search("salary", limit=10, user_id=None)}
        assert {"Alice salary is 180k", "Bob salary is 215k", "Office closed Jan 1"} <= contents

    def test_metadata_filter_still_scoped(self, surreal_db):
        # The user scope and a metadata filter must AND together: a filter must
        # never widen visibility back to another owner's chunks.
        surreal_db.insert(content_hash="ha", documents=[_doc("alice tagged")], user_id="alice", filters={"tag": "x"})
        surreal_db.insert(content_hash="hb", documents=[_doc("bob tagged")], user_id="bob", filters={"tag": "x"})
        contents = {d.content for d in surreal_db.search("tagged", limit=10, filters={"tag": "x"}, user_id="alice")}
        assert "alice tagged" in contents
        assert "bob tagged" not in contents


# ---------------------------------------------------------------------------
# Clobber prevention
# ---------------------------------------------------------------------------
class TestRecordIdClobber:
    def test_two_users_same_content_and_hash_coexist(self, surreal_db):
        """The clobber regression: identical content under the SAME content_hash
        for two users must produce TWO records, not one."""
        surreal_db.insert(content_hash="SAME", documents=[_doc("The secret is 42.")], user_id="alice")
        surreal_db.insert(content_hash="SAME", documents=[_doc("The secret is 42.")], user_id="bob")
        assert _raw_owners(surreal_db) == ["alice", "bob"]
        assert _count(surreal_db) == 2

    def test_clobbered_records_stay_isolated_on_search(self, surreal_db):
        surreal_db.insert(content_hash="SAME", documents=[_doc("The secret is 42.")], user_id="alice")
        surreal_db.insert(content_hash="SAME", documents=[_doc("The secret is 42.")], user_id="bob")
        alice = surreal_db.search("secret", limit=10, user_id="alice")
        bob = surreal_db.search("secret", limit=10, user_id="bob")
        # Each sees exactly their own single record; the other's still exists.
        assert len(alice) == 1
        assert len(bob) == 1
        assert _count(surreal_db) == 2

    def test_same_user_reinsert_same_hash_replaces(self, surreal_db):
        surreal_db.insert(content_hash="H", documents=[_doc("content v1")], user_id="alice")
        surreal_db.insert(content_hash="H", documents=[_doc("content v1")], user_id="alice")
        assert _count(surreal_db) == 1

    def test_shared_bucket_keeps_legacy_id(self, surreal_db):
        # A shared insert lands on the legacy id; a scoped insert of the same
        # content+hash lands on a different id — so they coexist.
        surreal_db.insert(content_hash="H", documents=[_doc("doc")], user_id=None)
        surreal_db.insert(content_hash="H", documents=[_doc("doc")], user_id="alice")
        assert _raw_owners(surreal_db) == ["alice", None]


# ---------------------------------------------------------------------------
# Upsert dedupe must be owner-scoped
# ---------------------------------------------------------------------------
class TestUpsertDedupeIsolation:
    def test_scoped_dedupe_does_not_touch_other_owner(self, surreal_db):
        surreal_db.upsert(content_hash="SH", documents=[_doc("alice v1")], user_id="alice")
        surreal_db.upsert(content_hash="SH", documents=[_doc("bob v1")], user_id="bob")
        # Alice re-upserts under the shared hash. Bob's chunk must survive.
        surreal_db.upsert(content_hash="SH", documents=[_doc("alice v2")], user_id="alice")
        assert _raw_owners(surreal_db) == ["alice", "bob"]
        assert _count(surreal_db) == 2
        alice = {d.content for d in surreal_db.search("v", limit=10, user_id="alice")}
        assert "alice v2" in alice
        assert "bob v1" not in alice

    def test_same_user_reupsert_replaces(self, surreal_db):
        surreal_db.upsert(content_hash="H", documents=[_doc("v1")], user_id="alice")
        surreal_db.upsert(content_hash="H", documents=[_doc("v2")], user_id="alice")
        assert _count(surreal_db) == 1
        assert {d.content for d in surreal_db.search("v", limit=10, user_id="alice")} == {"v2"}

    def test_scoped_reupsert_does_not_touch_shared(self, surreal_db):
        # A scoped re-upsert must never wipe the shared (NONE) bucket even when
        # they collide on the same content_hash.
        surreal_db.upsert(content_hash="SH", documents=[_doc("shared doc")], user_id=None)
        surreal_db.upsert(content_hash="SH", documents=[_doc("alice v1")], user_id="alice")
        surreal_db.upsert(content_hash="SH", documents=[_doc("alice v2")], user_id="alice")
        assert _raw_owners(surreal_db) == ["alice", None]

    def test_shared_upsert_does_not_wipe_scoped_owner(self, surreal_db):
        # A shared/admin re-ingest (``user_id=None``) must dedupe only the shared
        # bucket. Previously the None dedupe ran UNSCOPED and wiped every scoped
        # owner's row sharing that content_hash.
        surreal_db.insert(content_hash="SAME", documents=[_doc("alice owned")], user_id="alice")
        surreal_db.upsert(content_hash="SAME", documents=[_doc("shared doc")], user_id=None)
        # Alice's row survives the shared upsert and admin sees both rows.
        assert _raw_owners(surreal_db) == ["alice", None]
        alice = {d.content for d in surreal_db.search("doc", limit=10, user_id="alice")}
        assert "alice owned" in alice
        admin = {d.content for d in surreal_db.search("doc", limit=10, user_id=None)}
        assert {"alice owned", "shared doc"} <= admin


# ---------------------------------------------------------------------------
# Delete-by-content-id scoping
# ---------------------------------------------------------------------------
class TestDeleteByContentIdIsolation:
    @pytest.fixture
    def populated(self, surreal_db):
        """Two users own chunks under the SAME content_id — the adversarial
        scenario where Bob could try to wipe Alice's chunks."""
        alice = _doc("Alice's secret.")
        alice.content_id = "doc-1"
        bob = _doc("Bob's secret.")
        bob.content_id = "doc-1"
        surreal_db.insert(content_hash="h-alice", documents=[alice], user_id="alice")
        surreal_db.insert(content_hash="h-bob", documents=[bob], user_id="bob")
        return surreal_db

    def test_scoped_delete_only_removes_callers_chunks(self, populated):
        assert populated.delete_by_content_id("doc-1", user_id="bob") is True
        assert _raw_owners(populated) == ["alice"]

    def test_alice_can_delete_her_own(self, populated):
        assert populated.delete_by_content_id("doc-1", user_id="alice") is True
        assert _raw_owners(populated) == ["bob"]

    def test_unscoped_delete_wipes_everyone(self, populated):
        assert populated.delete_by_content_id("doc-1", user_id=None) is True
        assert _count(populated) == 0

    def test_scoped_delete_misses_when_user_owns_nothing(self, populated):
        # Carol owns nothing, so her scoped delete deletes nothing and reports False.
        assert populated.delete_by_content_id("doc-1", user_id="carol") is False
        assert _count(populated) == 2

    def test_scoped_delete_does_not_touch_shared(self, surreal_db):
        shared = _doc("shared doc")
        shared.content_id = "doc-2"
        owned = _doc("alice doc")
        owned.content_id = "doc-2"
        surreal_db.insert(content_hash="hs", documents=[shared], user_id=None)
        surreal_db.insert(content_hash="ha", documents=[owned], user_id="alice")
        # Alice deletes doc-2 under her scope — the shared row must remain.
        assert surreal_db.delete_by_content_id("doc-2", user_id="alice") is True
        assert _raw_owners(surreal_db) == [None]


# ---------------------------------------------------------------------------
# update_metadata must not let a caller reassign the owner
# ---------------------------------------------------------------------------
class TestUpdateMetadataOwnershipGuard:
    @pytest.fixture
    def owned(self, surreal_db):
        doc = _doc("metadata content")
        doc.content_id = "cid-1"
        surreal_db.insert(content_hash="hm", documents=[doc], user_id="alice")
        return surreal_db

    def test_caller_cannot_reassign_owner(self, owned):
        owned.update_metadata("cid-1", {"user_id": "bob", "tag": "x"})
        assert _raw_owners(owned) == ["alice"]

    def test_legitimate_metadata_still_applied(self, owned):
        owned.update_metadata("cid-1", {"tag": "x", "user_id": "bob"})
        rows = owned.client.query(f"SELECT meta_data FROM {owned.collection} WHERE content_id = 'cid-1';")
        assert rows[0]["meta_data"].get("tag") == "x"
        # The owner key never leaks into meta_data either.
        assert rows[0]["meta_data"].get("user_id") is None

    def test_owner_keeps_access_bob_does_not(self, owned):
        owned.update_metadata("cid-1", {"user_id": "bob"})
        alice = {d.content for d in owned.search("metadata", limit=10, user_id="alice")}
        bob = {d.content for d in owned.search("metadata", limit=10, user_id="bob")}
        assert "metadata content" in alice
        assert "metadata content" not in bob


# ---------------------------------------------------------------------------
# Schema migration for tables created before per-user isolation
# ---------------------------------------------------------------------------
class TestSchemaMigration:
    def test_legacy_table_migrated_and_rows_shared(self, surreal_db):
        """A table created without the owner field is migrated in place by
        ``create()``; pre-existing rows read as NONE and stay searchable as the
        shared bucket so old deployments keep working."""
        coll = surreal_db.collection
        # Simulate a legacy table: drop the owner fields, write a legacy row.
        surreal_db.client.query(f"REMOVE FIELD user_id ON {coll}; REMOVE FIELD content_id ON {coll};")
        surreal_db.client.query(
            f"CREATE {coll} SET content = $c, embedding = $e, meta_data = $m;",
            {
                "c": "legacy shared doc",
                "e": _DeterministicEmbedder().get_embedding("legacy shared doc"),
                "m": {"content_hash": "old"},
            },
        )
        # Re-open and create() -> idempotent migration of the owner field.
        surreal_db.create()
        surreal_db.insert(content_hash="ha", documents=[_doc("Alice new doc")], user_id="alice")
        contents = {d.content for d in surreal_db.search("doc", limit=10, user_id="alice")}
        assert "Alice new doc" in contents
        assert "legacy shared doc" in contents


# ---------------------------------------------------------------------------
# Async parity — the isolation must hold identically on the async surface
# ---------------------------------------------------------------------------
class TestAsyncIsolation:
    async def test_async_isolation_contract(self, async_surreal_db):
        db = async_surreal_db
        await db.async_insert(content_hash="ha", documents=[_doc("Alice salary is 180k")], user_id="alice")
        await db.async_insert(content_hash="hb", documents=[_doc("Bob salary is 215k")], user_id="bob")
        await db.async_insert(content_hash="hs", documents=[_doc("Office closed Jan 1")], user_id=None)

        alice = {d.content for d in await db.async_search("salary", limit=10, user_id="alice")}
        bob = {d.content for d in await db.async_search("salary", limit=10, user_id="bob")}
        admin = {d.content for d in await db.async_search("salary", limit=10, user_id=None)}

        assert "Alice salary is 180k" in alice
        assert "Office closed Jan 1" in alice
        assert "Bob salary is 215k" not in alice
        assert "Alice salary is 180k" not in bob
        assert {"Alice salary is 180k", "Bob salary is 215k", "Office closed Jan 1"} <= admin

    async def test_async_clobber_coexist(self, async_surreal_db):
        db = async_surreal_db
        await db.async_insert(content_hash="SAME", documents=[_doc("The secret is 42.")], user_id="alice")
        await db.async_insert(content_hash="SAME", documents=[_doc("The secret is 42.")], user_id="bob")
        assert await _async_raw_owners(db) == ["alice", "bob"]

    async def test_async_reupsert_replaces_not_accumulates(self, async_surreal_db):
        db = async_surreal_db
        await db.async_upsert(content_hash="H", documents=[_doc("v1")], user_id="alice")
        await db.async_upsert(content_hash="H", documents=[_doc("v2")], user_id="alice")
        assert await _async_count(db) == 1

    async def test_async_scoped_dedupe_keeps_other_owner(self, async_surreal_db):
        db = async_surreal_db
        await db.async_upsert(content_hash="SH", documents=[_doc("alice v1")], user_id="alice")
        await db.async_upsert(content_hash="SH", documents=[_doc("bob v1")], user_id="bob")
        await db.async_upsert(content_hash="SH", documents=[_doc("alice v2")], user_id="alice")
        assert await _async_raw_owners(db) == ["alice", "bob"]
        assert await _async_count(db) == 2
