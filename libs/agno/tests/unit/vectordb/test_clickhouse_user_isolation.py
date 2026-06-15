import os
import uuid

import pytest

clickhouse_connect = pytest.importorskip("clickhouse_connect")

from agno.knowledge.document import Document  # noqa: E402
from agno.vectordb.clickhouse import Clickhouse  # noqa: E402
from agno.vectordb.clickhouse.clickhousedb import SHARED_OWNER  # noqa: E402

CLICKHOUSE_HOST = os.environ.get("CLICKHOUSE_TEST_HOST", "localhost")
CLICKHOUSE_PORT = int(os.environ.get("CLICKHOUSE_TEST_PORT", "8124"))
CLICKHOUSE_USERNAME = os.environ.get("CLICKHOUSE_TEST_USERNAME", "default")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_TEST_PASSWORD", "")
TEST_DB = "isolation_test_db"


def _server_reachable() -> bool:
    """Probe the configured ClickHouse and ensure the test database exists, so
    the whole module skips cleanly when the server is down."""
    try:
        client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            username=CLICKHOUSE_USERNAME,
            password=CLICKHOUSE_PASSWORD,
        )
        client.command(f"CREATE DATABASE IF NOT EXISTS {TEST_DB}")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _server_reachable(), reason="ClickHouse server not reachable")


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

    def embed(self, document, *args, **kwargs):
        document.embedding = self.get_embedding(document.content)
        document.usage = {"total_tokens": 1}

    async def async_embed(self, document, *args, **kwargs):
        document.embedding = self.get_embedding(document.content)
        document.usage = {"total_tokens": 1}


def _doc(name: str, content: str, content_id: str = None) -> Document:
    """A Document with a non-null content_id (the column is non-nullable) and a
    precomputed deterministic embedding."""
    doc = Document(name=name, content=content)
    doc.content_id = content_id if content_id is not None else name
    doc.embedding = _DeterministicEmbedder().get_embedding(content)
    return doc


@pytest.fixture
def ch_db():
    """A fresh ClickHouse table per test, dropped on teardown."""
    table = f"iso_{uuid.uuid4().hex[:12]}"
    db = Clickhouse(
        table_name=table,
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        username=CLICKHOUSE_USERNAME,
        password=CLICKHOUSE_PASSWORD,
        database_name=TEST_DB,
        embedder=_DeterministicEmbedder(),
    )
    db.create()
    yield db
    try:
        db.drop()
    except Exception:
        pass


def _names(results):
    return {d.name for d in results}


def _owners_final(db):
    """The deduplicated owner column, read with FINAL so ReplacingMergeTree's
    in-flight duplicates don't skew assertions."""
    res = db.client.query(
        "SELECT user_id FROM {database_name:Identifier}.{table_name:Identifier} FINAL",
        parameters=db._get_base_parameters(),
    )
    return sorted(r[0] for r in res.result_rows)


def _count_final(db):
    res = db.client.query(
        "SELECT count() FROM {database_name:Identifier}.{table_name:Identifier} FINAL",
        parameters=db._get_base_parameters(),
    )
    return int(res.first_row[0])


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class TestSchema:
    """The owner lives in a dedicated ``user_id`` column. Pin the column and
    its sentinel — moving the owner into the meta_data/filters blob would
    silently break the scope predicate."""

    def test_shared_owner_sentinel_is_empty_string(self):
        assert SHARED_OWNER == ""

    def test_user_id_column_created(self, ch_db):
        assert ch_db._user_id_column_exists() is True

    def test_explicit_user_id_persisted_in_column(self, ch_db):
        ch_db.insert(content_hash="h1", documents=[_doc("alice", "alice content")], user_id="alice")
        assert _owners_final(ch_db) == ["alice"]

    def test_none_user_id_persisted_as_shared_sentinel(self, ch_db):
        ch_db.insert(content_hash="h1", documents=[_doc("shared", "shared content")], user_id=None)
        assert _owners_final(ch_db) == [SHARED_OWNER]

    def test_user_id_omitted_defaults_to_shared(self, ch_db):
        """Backwards-compatible: callers that never pass ``user_id`` get the
        shared sentinel — opting out of isolation."""
        ch_db.insert(content_hash="h1", documents=[_doc("shared", "shared content")])
        assert _owners_final(ch_db) == [SHARED_OWNER]


class TestMigration:
    """A table created before per-user isolation lacks ``user_id``. ``create()``
    must add it in place so old deployments keep working instead of hard-failing
    on insert or silently returning ``[]`` on scoped search."""

    @pytest.fixture
    def legacy_db(self):
        """A table built WITHOUT the user_id column — the pre-isolation schema."""
        table = f"legacy_{uuid.uuid4().hex[:12]}"
        db = Clickhouse(
            table_name=table,
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            username=CLICKHOUSE_USERNAME,
            password=CLICKHOUSE_PASSWORD,
            database_name=TEST_DB,
            embedder=_DeterministicEmbedder(),
        )
        db.client.command("SET allow_experimental_vector_similarity_index = 1")
        db.client.command("SET enable_json_type = 1")
        db.client.command(
            f"""CREATE TABLE {TEST_DB}.{table} (
                id String, name String, meta_data JSON DEFAULT '{{}}', filters JSON DEFAULT '{{}}',
                content String, content_id String, embedding Array(Float32), usage JSON,
                created_at DateTime('UTC') DEFAULT now(), content_hash String,
                INDEX embedding_index embedding TYPE vector_similarity('hnsw','L2Distance',8,'bf16',64,512)
            ) ENGINE = ReplacingMergeTree ORDER BY id"""
        )
        yield db
        try:
            db.drop()
        except Exception:
            pass

    def test_legacy_table_missing_user_id(self, legacy_db):
        assert legacy_db._user_id_column_exists() is False

    def test_create_migrates_in_place(self, legacy_db):
        legacy_db.create()
        assert legacy_db._user_id_column_exists() is True

    def test_migration_is_idempotent(self, legacy_db):
        legacy_db.create()
        legacy_db.create()  # must not raise
        assert legacy_db._user_id_column_exists() is True

    def test_scoped_search_works_after_migration(self, legacy_db):
        legacy_db.create()
        legacy_db.insert(content_hash="h", documents=[_doc("alice", "alice content")], user_id="alice")
        results = legacy_db.search("alice content", limit=5, user_id="alice")
        assert "alice" in _names(results)


# ---------------------------------------------------------------------------
# Search isolation
# ---------------------------------------------------------------------------
class TestSearchIsolation:
    """The load-bearing test: alice's search returns her chunks plus shared
    chunks, never bob's. user_id=None is the admin view and sees everything."""

    @pytest.fixture
    def populated(self, ch_db):
        ch_db.insert(content_hash="ha", documents=[_doc("alice-salary", "Alice salary 180k")], user_id="alice")
        ch_db.insert(content_hash="hb", documents=[_doc("bob-salary", "Bob salary 215k")], user_id="bob")
        ch_db.insert(content_hash="hs", documents=[_doc("company-holidays", "office closed Jan 1")], user_id=None)
        return ch_db

    def test_alice_sees_her_own_chunk(self, populated):
        assert "alice-salary" in _names(populated.search("salary", limit=10, user_id="alice"))

    def test_alice_sees_shared_chunk(self, populated):
        assert "company-holidays" in _names(populated.search("salary", limit=10, user_id="alice"))

    def test_alice_never_sees_bobs_chunk(self, populated):
        """The isolation contract. If this fails alice is retrieving bob's
        confidential chunks."""
        results = populated.search("salary", limit=10, user_id="alice")
        assert "bob-salary" not in _names(results)
        for d in results:
            assert "Bob salary" not in d.content

    def test_bob_never_sees_alices_chunk(self, populated):
        assert "alice-salary" not in _names(populated.search("salary", limit=10, user_id="bob"))

    def test_admin_sees_everything(self, populated):
        names = _names(populated.search("salary", limit=10, user_id=None))
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names

    def test_empty_string_user_id_is_admin_view(self, populated):
        """``user_id=""`` normalizes to None (unscoped) — same as admin."""
        names = _names(populated.search("salary", limit=10, user_id=""))
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names

    def test_carol_sees_only_shared(self, populated):
        """A user with no chunks of her own sees only the shared bucket."""
        names = _names(populated.search("salary", limit=10, user_id="carol"))
        assert names == {"company-holidays"}


# ---------------------------------------------------------------------------
# Delete scoping
# ---------------------------------------------------------------------------
class TestDeleteScoping:
    """``delete_by_content_id(content_id, user_id=...)`` must scope to the
    caller's rows — otherwise Bob could guess Alice's content_id and wipe her
    chunks, or a scoped caller could delete shared org content."""

    @pytest.fixture
    def populated(self, ch_db):
        # Three owners share the SAME content_id 'doc-1' — the adversarial case.
        ch_db.insert(content_hash="ha", documents=[_doc("ad", "alice secret", "doc-1")], user_id="alice")
        ch_db.insert(content_hash="hb", documents=[_doc("bd", "bob secret", "doc-1")], user_id="bob")
        ch_db.insert(content_hash="hs", documents=[_doc("sd", "shared secret", "doc-1")], user_id=None)
        return ch_db

    def test_scoped_delete_only_removes_callers_chunks(self, populated):
        populated.delete_by_content_id("doc-1", user_id="bob")
        # Bob's row gone; alice and shared remain. Isolation broken if bob's
        # delete touched another owner.
        assert _owners_final(populated) == [SHARED_OWNER, "alice"]

    def test_scoped_delete_does_not_touch_shared(self, populated):
        """A scoped caller must NOT delete the shared (empty-owner) bucket."""
        populated.delete_by_content_id("doc-1", user_id="alice")
        assert SHARED_OWNER in _owners_final(populated)

    def test_scoped_delete_misses_when_user_owns_nothing(self, populated):
        populated.delete_by_content_id("doc-1", user_id="carol")
        assert _owners_final(populated) == [SHARED_OWNER, "alice", "bob"]

    def test_unscoped_delete_wipes_everyone(self, populated):
        """Legacy/admin behaviour: ``user_id=None`` deletes across all owners."""
        populated.delete_by_content_id("doc-1", user_id=None)
        assert _count_final(populated) == 0


# ---------------------------------------------------------------------------
# Clobber prevention
# ---------------------------------------------------------------------------
class TestClobberPrevention:
    """The row id must fold in the owner. ReplacingMergeTree collapses rows
    sharing the PK ``id``, so without the owner two users inserting IDENTICAL
    content under the SAME content_hash collide and one silently overwrites the
    other. The vector DB is a public API — it must stay correct on its own."""

    def test_two_users_same_content_and_hash_coexist(self, ch_db):
        ch_db.insert(content_hash="SAME", documents=[_doc("secret", "the secret is 42")], user_id="alice")
        ch_db.insert(content_hash="SAME", documents=[_doc("secret", "the secret is 42")], user_id="bob")
        assert _owners_final(ch_db) == ["alice", "bob"]

    def test_clobbered_rows_stay_isolated_on_search(self, ch_db):
        ch_db.insert(content_hash="SAME", documents=[_doc("secret", "the secret is 42")], user_id="alice")
        ch_db.insert(content_hash="SAME", documents=[_doc("secret", "the secret is 42")], user_id="bob")
        assert _names(ch_db.search("secret", limit=10, user_id="alice")) == {"secret"}
        assert _names(ch_db.search("secret", limit=10, user_id="bob")) == {"secret"}
        assert _count_final(ch_db) == 2

    def test_same_user_reinsert_same_content_replaces(self, ch_db):
        """Same owner + same content = same row id, so a re-insert collapses to
        one row under FINAL rather than duplicating."""
        ch_db.insert(content_hash="H", documents=[_doc("d", "content v1")], user_id="alice")
        ch_db.insert(content_hash="H", documents=[_doc("d", "content v1")], user_id="alice")
        assert _count_final(ch_db) == 1

    def test_shared_bucket_keeps_legacy_id(self, ch_db):
        """``user_id=None`` rows keep the content-only id so previously persisted
        shared rows stay byte-identical and addressable."""
        from hashlib import md5

        legacy = md5(b"content").hexdigest()
        assert ch_db._record_id("content", None) == legacy
        assert ch_db._record_id("content", "alice") != legacy


# ---------------------------------------------------------------------------
# Upsert dedupe scoping
# ---------------------------------------------------------------------------
class TestUpsertDedupe:
    """``upsert`` dedupes by deleting prior chunks with the same content_hash
    before re-inserting. That delete must be SCOPED to the owner — otherwise
    Alice re-upserting wipes Bob's chunk that carries the same content_hash."""

    def test_scoped_dedupe_keeps_other_owner(self, ch_db):
        ch_db.upsert(content_hash="SH", documents=[_doc("ad", "alice v1")], user_id="alice")
        ch_db.upsert(content_hash="SH", documents=[_doc("bd", "bob v1")], user_id="bob")
        ch_db.upsert(content_hash="SH", documents=[_doc("ad2", "alice v2")], user_id="alice")
        assert _owners_final(ch_db) == ["alice", "bob"]

    def test_same_user_reupsert_replaces(self, ch_db):
        ch_db.upsert(content_hash="H", documents=[_doc("d", "v1")], user_id="alice")
        ch_db.upsert(content_hash="H", documents=[_doc("d", "v1")], user_id="alice")
        assert _count_final(ch_db) == 1

    def test_scoped_dedupe_keeps_shared(self, ch_db):
        """Re-upserting a scoped owner must not delete the shared copy of the
        same content_hash."""
        ch_db.upsert(content_hash="SH", documents=[_doc("shared", "shared v1")], user_id=None)
        ch_db.upsert(content_hash="SH", documents=[_doc("ad", "alice v1")], user_id="alice")
        ch_db.upsert(content_hash="SH", documents=[_doc("ad2", "alice v2")], user_id="alice")
        assert SHARED_OWNER in _owners_final(ch_db)

    def test_shared_upsert_does_not_wipe_scoped_owners(self, ch_db):
        """A shared/admin re-ingest (``user_id=None``) under a hash that scoped
        owners already uploaded must scope its dedupe-delete to the shared bucket
        only — pre-fix it wiped every scoped owner sharing that content_hash."""
        ch_db.upsert(content_hash="SAME", documents=[_doc("ad", "alice v1")], user_id="alice")
        ch_db.upsert(content_hash="SAME", documents=[_doc("bd", "bob v1")], user_id="bob")
        # The wipe trigger: a shared re-ingest of the SAME content_hash.
        ch_db.upsert(content_hash="SAME", documents=[_doc("sd", "shared v1")], user_id=None)
        assert _owners_final(ch_db) == [SHARED_OWNER, "alice", "bob"]


# ---------------------------------------------------------------------------
# update_metadata ownership guard
# ---------------------------------------------------------------------------
class TestUpdateMetadataGuard:
    """``update_metadata`` merges the caller's dict into the meta_data/filters
    blobs. It must NOT let metadata={"user_id": ...} flip a chunk's owner — the
    owner lives in the dedicated column and ownership reassignment would let a
    caller steal or leak a chunk."""

    def test_caller_cannot_reassign_owner(self, ch_db):
        ch_db.insert(content_hash="hm", documents=[_doc("md", "metadata content", "cid-1")], user_id="alice")
        ch_db.update_metadata("cid-1", {"user_id": "bob", "tag": "x"})
        assert _owners_final(ch_db) == ["alice"]

    def test_owner_unchanged_keeps_access(self, ch_db):
        ch_db.insert(content_hash="hm", documents=[_doc("md", "metadata content", "cid-1")], user_id="alice")
        ch_db.update_metadata("cid-1", {"user_id": "bob"})
        assert "md" in _names(ch_db.search("metadata content", limit=10, user_id="alice"))
        assert "md" not in _names(ch_db.search("metadata content", limit=10, user_id="bob"))


# ---------------------------------------------------------------------------
# Async isolation (built on a sync-created table; see module docstring)
# ---------------------------------------------------------------------------
@pytest.fixture
def ch_db_async():
    table = f"iso_async_{uuid.uuid4().hex[:12]}"
    db = Clickhouse(
        table_name=table,
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        username=CLICKHOUSE_USERNAME,
        password=CLICKHOUSE_PASSWORD,
        database_name=TEST_DB,
        embedder=_DeterministicEmbedder(),
    )
    # Sync create gives a valid table; we exercise the async ISOLATION paths.
    db.create()
    yield db
    try:
        db.drop()
    except Exception:
        pass


class TestAsyncSearchIsolation:
    async def _populate(self, db):
        await db.async_insert(content_hash="ha", documents=[_doc("alice-salary", "Alice salary 180k")], user_id="alice")
        await db.async_insert(content_hash="hb", documents=[_doc("bob-salary", "Bob salary 215k")], user_id="bob")
        await db.async_insert(
            content_hash="hs", documents=[_doc("company-holidays", "office closed Jan 1")], user_id=None
        )

    async def test_async_alice_sees_own_and_shared(self, ch_db_async):
        await self._populate(ch_db_async)
        names = _names(await ch_db_async.async_search("salary", limit=10, user_id="alice"))
        assert "alice-salary" in names
        assert "company-holidays" in names

    async def test_async_alice_never_sees_bob(self, ch_db_async):
        await self._populate(ch_db_async)
        names = _names(await ch_db_async.async_search("salary", limit=10, user_id="alice"))
        assert "bob-salary" not in names

    async def test_async_admin_sees_all(self, ch_db_async):
        await self._populate(ch_db_async)
        names = _names(await ch_db_async.async_search("salary", limit=10, user_id=None))
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names


class TestAsyncUpsertDedupe:
    async def test_async_scoped_dedupe_keeps_other_owner(self, ch_db_async):
        await ch_db_async.async_upsert(content_hash="SH", documents=[_doc("ad", "alice v1")], user_id="alice")
        await ch_db_async.async_upsert(content_hash="SH", documents=[_doc("bd", "bob v1")], user_id="bob")
        await ch_db_async.async_upsert(content_hash="SH", documents=[_doc("ad2", "alice v2")], user_id="alice")
        assert _owners_final(ch_db_async) == ["alice", "bob"]

    async def test_async_same_user_reupsert_replaces(self, ch_db_async):
        await ch_db_async.async_upsert(content_hash="H", documents=[_doc("d", "v1")], user_id="alice")
        await ch_db_async.async_upsert(content_hash="H", documents=[_doc("d", "v1")], user_id="alice")
        assert _count_final(ch_db_async) == 1

    async def test_async_clobber_coexist(self, ch_db_async):
        await ch_db_async.async_insert(
            content_hash="SAME", documents=[_doc("secret", "the secret is 42")], user_id="alice"
        )
        await ch_db_async.async_insert(
            content_hash="SAME", documents=[_doc("secret", "the secret is 42")], user_id="bob"
        )
        assert _owners_final(ch_db_async) == ["alice", "bob"]
