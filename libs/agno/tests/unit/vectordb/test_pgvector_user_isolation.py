import hashlib
import uuid
from typing import List, Optional

import pytest

from agno.knowledge.document import Document
from agno.vectordb.pgvector import PgVector
from agno.vectordb.search import SearchType

PG_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
TEST_SCHEMA = "ai"
DIM = 64


class HashEmbedder:
    """Deterministic content->vector. Distinct content => distinct vector,
    so vector-search ranking actually discriminates between rows (a constant
    mock embedding would make every row equidistant and hide isolation bugs).
    """

    dimensions = DIM
    enable_batch = False

    def _vec(self, text_in: str) -> List[float]:
        v: List[float] = []
        seed = text_in or ""
        i = 0
        while len(v) < DIM:
            h = hashlib.md5(f"{seed}:{i}".encode()).digest()
            for b in h:
                v.append((b / 255.0) * 2 - 1)
                if len(v) >= DIM:
                    break
            i += 1
        return v

    def get_embedding(self, text_in: str) -> List[float]:
        return self._vec(text_in)

    def get_embedding_and_usage(self, text_in: str):
        return self._vec(text_in), {"total_tokens": 1}

    async def async_get_embedding_and_usage(self, text_in: str):
        return self._vec(text_in), {"total_tokens": 1}

    async def async_get_embeddings_batch_and_usage(self, texts: List[str]):
        return [self._vec(t) for t in texts], [{"total_tokens": 1} for _ in texts]


def _server_available() -> bool:
    try:
        from sqlalchemy import create_engine
        from sqlalchemy import text as sa_text

        eng = create_engine(PG_URL)
        with eng.connect() as conn:
            conn.execute(sa_text("SELECT 1"))
        return True
    except Exception:
        return False


requires_pg = pytest.mark.skipif(
    not _server_available(),
    reason="PostgreSQL/pgvector not reachable at localhost:5532",
)


def _alice_docs() -> List[Document]:
    return [Document(name="alice-salary", content="Alice's salary is $180k.")]


def _bob_docs() -> List[Document]:
    return [Document(name="bob-salary", content="Bob's salary is $215k.")]


def _shared_docs() -> List[Document]:
    return [Document(name="company-holidays", content="The office is closed Jan 1.")]


@pytest.fixture
def pgvector_db():
    """A fresh PgVector backed by a throwaway table, dropped after the test."""
    table = f"test_iso_{uuid.uuid4().hex[:8]}"
    db = PgVector(table_name=table, schema=TEST_SCHEMA, db_url=PG_URL, embedder=HashEmbedder())
    db.create()
    yield db
    try:
        db.drop()
    except Exception:
        pass


def _vector_db(search_type: SearchType) -> PgVector:
    table = f"test_iso_{uuid.uuid4().hex[:8]}"
    db = PgVector(
        table_name=table,
        schema=TEST_SCHEMA,
        db_url=PG_URL,
        embedder=HashEmbedder(),
        search_type=search_type,
    )
    db.create()
    return db


def _owners(db: PgVector) -> List[Optional[str]]:
    from sqlalchemy import text as sa_text

    with db.Session() as sess:
        rows = sess.execute(sa_text(f"SELECT user_id FROM {db.table.fullname} ORDER BY user_id NULLS FIRST")).fetchall()
    return [r[0] for r in rows]


# --------------------------------------------------------------------------
# Pure-logic tests — no server required.
# --------------------------------------------------------------------------


class TestRecordIdFoldsUserId:
    """The deterministic primary key must include ``user_id`` so the SAME
    ``content_hash`` owned by two users yields two distinct ids — otherwise
    they collide on the PK and one clobbers the other.
    """

    def _db(self) -> PgVector:
        # No create() — we only call the pure id helper, never touch the DB.
        return PgVector(table_name="x", schema=TEST_SCHEMA, db_url=PG_URL, embedder=HashEmbedder())

    def test_same_hash_different_user_distinct_ids(self):
        db = self._db()
        a = db._record_id("base", "h1", "alice")
        b = db._record_id("base", "h1", "bob")
        assert a != b

    def test_none_user_id_renders_as_legacy_unscoped_id(self):
        """``None`` => the legacy id (no owner component) byte-for-byte, so
        content that was never owner-stamped stays addressable."""
        db = self._db()
        expected = hashlib.md5(b"base_h1").hexdigest()
        assert db._record_id("base", "h1", None) == expected

    def test_same_user_same_hash_stable_id(self):
        db = self._db()
        assert db._record_id("base", "h1", "alice") == db._record_id("base", "h1", "alice")


class TestUserScopePredicate:
    """The scope helper ANDs ``user_id = X OR user_id IS NULL`` only when a
    user is set; ``None`` (and empty string, which normalizes to None) yields
    no predicate."""

    def _db(self) -> PgVector:
        return PgVector(table_name="x", schema=TEST_SCHEMA, db_url=PG_URL, embedder=HashEmbedder())

    def test_none_user_id_no_predicate(self):
        from sqlalchemy import select

        db = self._db()
        stmt = select(db.table.c.id)
        assert db._apply_user_scope(stmt, None) is stmt

    def test_scoped_user_id_adds_predicate(self):
        from sqlalchemy import select

        db = self._db()
        stmt = select(db.table.c.id)
        scoped = db._apply_user_scope(stmt, "alice")
        compiled = str(scoped.compile(compile_kwargs={"literal_binds": True}))
        assert "user_id" in compiled
        assert "IS NULL" in compiled


# --------------------------------------------------------------------------
# Live, server-backed tests.
# --------------------------------------------------------------------------


@requires_pg
class TestInsertPopulatesUserIdColumn:
    def test_explicit_user_id_persisted_in_column(self, pgvector_db):
        pgvector_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")
        assert _owners(pgvector_db) == ["alice"]

    def test_none_user_id_persisted_as_null(self, pgvector_db):
        pgvector_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)
        assert _owners(pgvector_db) == [None]

    def test_user_id_omitted_defaults_to_null(self, pgvector_db):
        pgvector_db.insert(content_hash="h1", documents=_shared_docs())
        assert _owners(pgvector_db) == [None]


@requires_pg
@pytest.mark.parametrize("search_type", [SearchType.vector, SearchType.keyword, SearchType.hybrid])
class TestSearchIsolationContract:
    """alice sees her chunks plus shared, never bob's — across vector,
    keyword AND hybrid. Run for every search path because each builds its
    own statement and could independently drop the scope predicate."""

    def _populate(self, db: PgVector):
        db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)

    def test_alice_sees_own_and_shared_never_bob(self, search_type):
        db = _vector_db(search_type)
        try:
            self._populate(db)
            res = {d.name for d in db.search("salary office", limit=10, user_id="alice")}
            assert "alice-salary" in res
            assert "company-holidays" in res
            assert "bob-salary" not in res
        finally:
            db.drop()

    def test_bob_never_sees_alice(self, search_type):
        db = _vector_db(search_type)
        try:
            self._populate(db)
            res = {d.name for d in db.search("salary", limit=10, user_id="bob")}
            assert "alice-salary" not in res
        finally:
            db.drop()

    def test_admin_sees_everything(self, search_type):
        db = _vector_db(search_type)
        try:
            self._populate(db)
            res = {d.name for d in db.search("salary office", limit=10, user_id=None)}
            assert {"alice-salary", "bob-salary", "company-holidays"} <= res
        finally:
            db.drop()


@requires_pg
@pytest.mark.asyncio
@pytest.mark.parametrize("search_type", [SearchType.vector, SearchType.keyword, SearchType.hybrid])
class TestSearchIsolationContractAsync:
    """Same contract through the async path."""

    async def _populate(self, db: PgVector):
        await db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        await db.async_insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        await db.async_insert(content_hash="hs", documents=_shared_docs(), user_id=None)

    async def test_alice_isolated(self, search_type):
        db = _vector_db(search_type)
        try:
            await self._populate(db)
            res = {d.name for d in await db.async_search("salary office", limit=10, user_id="alice")}
            assert "alice-salary" in res
            assert "bob-salary" not in res
        finally:
            await db.async_drop()

    async def test_admin_sees_everything(self, search_type):
        db = _vector_db(search_type)
        try:
            await self._populate(db)
            res = {d.name for d in await db.async_search("salary office", limit=10, user_id=None)}
            assert {"alice-salary", "bob-salary", "company-holidays"} <= res
        finally:
            await db.async_drop()


@requires_pg
class TestCrossUserClobber:
    """Two users upsert the SAME content_hash directly to the vector_db
    (bypassing Knowledge, which would already fold user_id into the hash).
    The backend must be correct on its own: both rows coexist, isolated,
    neither deletes the other. Same-user re-upsert replaces in place.
    """

    SAME = "same-content-hash"

    def test_two_users_same_hash_coexist(self, pgvector_db):
        pgvector_db.upsert(content_hash=self.SAME, documents=_alice_docs(), user_id="alice")
        pgvector_db.upsert(content_hash=self.SAME, documents=_bob_docs(), user_id="bob")
        assert pgvector_db.get_count() == 2
        assert _owners(pgvector_db) == ["alice", "bob"]

    def test_same_user_reupsert_replaces_not_duplicates(self, pgvector_db):
        pgvector_db.upsert(content_hash=self.SAME, documents=_alice_docs(), user_id="alice")
        pgvector_db.upsert(content_hash=self.SAME, documents=_bob_docs(), user_id="bob")

        updated = [Document(name="alice-salary-v2", content="Alice's salary is now $200k.")]
        pgvector_db.upsert(content_hash=self.SAME, documents=updated, user_id="alice")

        assert pgvector_db.get_count() == 2  # no duplicate row for alice
        from sqlalchemy import text as sa_text

        with pgvector_db.Session() as sess:
            alice_names = [
                r[0]
                for r in sess.execute(
                    sa_text(f"SELECT name FROM {pgvector_db.table.fullname} WHERE user_id = 'alice'")
                ).fetchall()
            ]
            bob_names = [
                r[0]
                for r in sess.execute(
                    sa_text(f"SELECT name FROM {pgvector_db.table.fullname} WHERE user_id = 'bob'")
                ).fetchall()
            ]
        assert alice_names == ["alice-salary-v2"]
        assert bob_names == ["bob-salary"], "alice's re-upsert clobbered bob's row"

    @pytest.mark.asyncio
    async def test_two_users_same_hash_coexist_async(self):
        db = _vector_db(SearchType.vector)
        try:
            await db.async_upsert(content_hash=self.SAME, documents=_alice_docs(), user_id="alice")
            await db.async_upsert(content_hash=self.SAME, documents=_bob_docs(), user_id="bob")
            assert db.get_count() == 2
            await db.async_upsert(content_hash=self.SAME, documents=_alice_docs(), user_id="alice")
            assert db.get_count() == 2  # re-upsert still no duplicate
        finally:
            await db.async_drop()

    def test_shared_upsert_does_not_wipe_scoped_owners(self, pgvector_db):
        # A shared/admin re-ingest (user_id=None) of a content_hash that scoped
        # users already own must dedupe ONLY the shared bucket — it must never
        # delete another owner's rows that happen to share that content_hash.
        pgvector_db.upsert(content_hash=self.SAME, documents=_alice_docs(), user_id="alice")
        pgvector_db.upsert(content_hash=self.SAME, documents=_bob_docs(), user_id="bob")
        pgvector_db.upsert(content_hash=self.SAME, documents=_shared_docs(), user_id=None)
        assert _owners(pgvector_db) == [None, "alice", "bob"]
        # A second shared re-ingest dedupes only the shared row (no scoped loss).
        pgvector_db.upsert(content_hash=self.SAME, documents=_shared_docs(), user_id=None)
        assert _owners(pgvector_db) == [None, "alice", "bob"]

    @pytest.mark.asyncio
    async def test_shared_upsert_does_not_wipe_scoped_owners_async(self):
        db = _vector_db(SearchType.vector)
        try:
            await db.async_upsert(content_hash=self.SAME, documents=_alice_docs(), user_id="alice")
            await db.async_upsert(content_hash=self.SAME, documents=_bob_docs(), user_id="bob")
            await db.async_upsert(content_hash=self.SAME, documents=_shared_docs(), user_id=None)
            assert _owners(db) == [None, "alice", "bob"]
        finally:
            await db.async_drop()


@requires_pg
class TestDeleteByContentIdIsolation:
    """``delete_by_content_id(content_id, user_id=...)`` scopes the delete to
    the owner — Bob can't wipe Alice's chunks by guessing her content_id,
    and a scoped delete must NEVER touch the shared (NULL) bucket.
    """

    @pytest.fixture
    def populated_db(self, pgvector_db):
        alice = Document(name="alice-doc", content="Alice secret.")
        alice.content_id = "doc-1"
        bob = Document(name="bob-doc", content="Bob secret.")
        bob.content_id = "doc-1"
        shared = Document(name="shared-doc", content="Shared note.")
        shared.content_id = "doc-1"
        pgvector_db.insert(content_hash="ha", documents=[alice], user_id="alice")
        pgvector_db.insert(content_hash="hb", documents=[bob], user_id="bob")
        pgvector_db.insert(content_hash="hs", documents=[shared], user_id=None)
        return pgvector_db

    def test_scoped_delete_only_removes_callers_chunks(self, populated_db):
        assert populated_db.delete_by_content_id("doc-1", user_id="bob") is True
        # alice + shared survive; bob gone.
        assert _owners(populated_db) == [None, "alice"]

    def test_scoped_delete_never_touches_shared(self, populated_db):
        populated_db.delete_by_content_id("doc-1", user_id="alice")
        owners = _owners(populated_db)
        assert None in owners, "scoped delete wiped the shared (NULL) bucket"

    def test_non_owner_scoped_delete_deletes_nothing_returns_false(self, populated_db):
        assert populated_db.delete_by_content_id("doc-1", user_id="carol") is False
        assert populated_db.get_count() == 3

    def test_unscoped_delete_wipes_everyone(self, populated_db):
        assert populated_db.delete_by_content_id("doc-1", user_id=None) is True
        assert populated_db.get_count() == 0

    def test_delete_missing_content_id_returns_false(self, pgvector_db):
        pgvector_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        assert pgvector_db.delete_by_content_id("nonexistent") is False


