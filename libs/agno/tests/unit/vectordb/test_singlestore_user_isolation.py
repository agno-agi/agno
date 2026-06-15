import inspect
import os
from hashlib import md5
from typing import List
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects import mysql  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

from agno.knowledge.document import Document  # noqa: E402
from agno.vectordb.singlestore import SingleStore  # noqa: E402

TEST_COLLECTION = "iso_test"
TEST_SCHEMA = "iso_schema"


# --------------------------------------------------------------------------- #
# Deterministic embedder — no network, no API key.
# --------------------------------------------------------------------------- #
class _DeterministicEmbedder:
    """A tiny embedder that needs no network or API key. The content steers
    the vector so distinct documents land in distinct buckets — all the
    isolation tests need, and it gives us a real (sync + async) surface."""

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

    def embed(self, document, embedder=None):
        document.embedding = self.get_embedding(document.content)
        document.usage = {"total_tokens": 1}

    async def async_embed(self, document, embedder=None):
        document.embedding = self.get_embedding(document.content)
        document.usage = {"total_tokens": 1}


# --------------------------------------------------------------------------- #
# Mocked-engine fixtures (no DB).
# --------------------------------------------------------------------------- #
@pytest.fixture
def mock_db():
    """A SingleStore wired to a mocked engine/sessionmaker. Good enough to
    exercise pure SQL construction and the id-folding helper without a DB."""
    mock_engine = MagicMock(spec=Engine)
    with patch("agno.vectordb.singlestore.singlestore.sessionmaker"):
        db = SingleStore(
            collection=TEST_COLLECTION,
            schema=TEST_SCHEMA,
            db_engine=mock_engine,
            embedder=_DeterministicEmbedder(),
        )
    return db


# --------------------------------------------------------------------------- #
# 1. Signature contract.
# --------------------------------------------------------------------------- #
class TestSignatureContract:
    """``user_id: Optional[str] = None`` must be the LAST parameter on every
    scoped method (after ``batch_size`` on insert/upsert). The Knowledge
    wrapper passes ``user_id`` positionally/by-keyword uniformly, so a
    drifting signature silently TypeErrors or scopes the wrong arg."""

    @pytest.mark.parametrize(
        "method",
        [
            "insert",
            "async_insert",
            "upsert",
            "async_upsert",
            "search",
            "async_search",
            "delete_by_content_id",
        ],
    )
    def test_user_id_is_last_param_with_none_default(self, method):
        params = list(inspect.signature(getattr(SingleStore, method)).parameters.values())
        last = params[-1]
        assert last.name == "user_id", f"{method}: user_id is not the last parameter"
        assert last.default is None, f"{method}: user_id default is not None"


# --------------------------------------------------------------------------- #
# 2. Scope predicate (compiled SQL, no DB).
# --------------------------------------------------------------------------- #
class TestUserScopePredicate:
    """The scope builder is small enough to unit-test by compiling the SQL.
    We catch the OR semantics, the shared-NULL pattern, and — critically —
    that ``user_id`` is a BOUND parameter, never interpolated into the SQL."""

    def test_scoped_predicate_binds_user_id_and_ors_null(self, mock_db):
        stmt = mock_db._apply_user_scope(select(mock_db.table.c.name), "alice")
        compiled = stmt.compile(dialect=mysql.dialect())
        sql = str(compiled)
        assert "user_id = " in sql
        assert "IS NULL" in sql
        # user_id must be a bound param, not interpolated into the SQL text.
        assert "alice" not in sql, "user_id was string-interpolated into the SQL"
        assert "alice" in compiled.params.values()

    def test_none_user_id_applies_no_predicate(self, mock_db):
        stmt = mock_db._apply_user_scope(select(mock_db.table.c.name), None)
        sql = str(stmt.compile(dialect=mysql.dialect()))
        assert "WHERE" not in sql

    def test_empty_string_normalizes_to_unscoped(self, mock_db):
        # normalize_user_id collapses "" to None — same as the admin view.
        stmt = mock_db._apply_user_scope(select(mock_db.table.c.name), "")
        sql = str(stmt.compile(dialect=mysql.dialect()))
        assert "WHERE" not in sql


# --------------------------------------------------------------------------- #
# 3. Row-id folding (clobber prevention).
# --------------------------------------------------------------------------- #
class TestRecordIdFolding:
    """The deterministic row id must fold in the owner so two users uploading
    the SAME content under the SAME content_hash get distinct ids and coexist
    instead of clobbering each other. The shared (None) bucket must keep the
    legacy id so previously persisted shared rows stay addressable."""

    def test_shared_bucket_keeps_legacy_id(self, mock_db):
        # Shared/unscoped keeps the legacy owner-less id md5(f"{base}_{hash}"),
        # byte-identical for both None and "" (falsy = unscoped).
        legacy = md5(b"x_H").hexdigest()
        assert mock_db._record_id("x", "H", None) == legacy
        assert mock_db._record_id("x", "H", "") == legacy

    def test_scoped_id_differs_from_shared(self, mock_db):
        assert mock_db._record_id("x", "H", "alice") != mock_db._record_id("x", "H", None)

    def test_two_users_get_distinct_ids(self, mock_db):
        assert mock_db._record_id("x", "H", "alice") != mock_db._record_id("x", "H", "bob")

    def test_same_user_same_content_is_stable(self, mock_db):
        assert mock_db._record_id("x", "H", "alice") == mock_db._record_id("x", "H", "alice")


# --------------------------------------------------------------------------- #
# 4. Schema carries the owner column.
# --------------------------------------------------------------------------- #
class TestSchemaHasUserIdColumn:
    def test_table_has_user_id_column(self, mock_db):
        assert "user_id" in mock_db.table.c

    def test_user_id_column_is_nullable(self, mock_db):
        # NULL is the shared bucket — the column must allow it.
        assert mock_db.table.c.user_id.nullable is True


# --------------------------------------------------------------------------- #
# 5. Insert / upsert stamp the owner into the column (mocked execute).
# --------------------------------------------------------------------------- #
class TestWriteStampsOwner:
    """Without a DB we can still assert the INSERT statement carries the
    ``user_id`` column with the caller's value — i.e. the owner is stored as a
    first-class column, not buried inside meta_data."""

    def _captured_insert_params(self, db, executed_stmt):
        compiled = executed_stmt.compile(dialect=mysql.dialect())
        return compiled.params

    def test_insert_includes_user_id_value(self, mock_db):
        captured = []

        class _Sess:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def execute(self_inner, stmt):
                captured.append(stmt)

            def commit(self_inner):
                pass

        mock_db.Session = MagicMock()
        mock_db.Session.begin.return_value = _Sess()

        doc = Document(name="d", content="alice content")
        mock_db.insert(content_hash="h", documents=[doc], user_id="alice")

        assert captured, "no statement executed"
        params = self._captured_insert_params(mock_db, captured[0])
        assert params.get("user_id") == "alice"

    def test_insert_none_stores_null_owner(self, mock_db):
        captured = []

        class _Sess:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def execute(self_inner, stmt):
                captured.append(stmt)

            def commit(self_inner):
                pass

        mock_db.Session = MagicMock()
        mock_db.Session.begin.return_value = _Sess()

        doc = Document(name="d", content="shared content")
        mock_db.insert(content_hash="h", documents=[doc], user_id=None)

        params = self._captured_insert_params(mock_db, captured[0])
        assert params.get("user_id") is None


# --------------------------------------------------------------------------- #
# Live server section — skipped cleanly when no server is configured.
# --------------------------------------------------------------------------- #
_LIVE_URL = os.environ.get("SINGLESTORE_TEST_URL")


def _server_reachable(url: str) -> bool:
    try:
        eng = sqlalchemy.create_engine(url)
        with eng.connect() as conn:
            conn.execute(sqlalchemy.text("SELECT 1"))
        return True
    except Exception:
        return False


_LIVE_AVAILABLE = bool(_LIVE_URL) and _server_reachable(_LIVE_URL or "")
_live = pytest.mark.skipif(
    not _LIVE_AVAILABLE,
    reason="No live SingleStore (set SINGLESTORE_TEST_URL to a reachable SQLAlchemy URL to enable).",
)

# Use the database named in the URL (managed clusters often deny CREATE
# DATABASE); fall back to a scratch db when the URL points at the server root.
_URL_DB = urlsplit(_LIVE_URL or "").path.lstrip("/")
LIVE_DB = _URL_DB or "iso_live_db"


def _embedded(name: str, content: str) -> Document:
    doc = Document(name=name, content=content)
    doc.embedding = _DeterministicEmbedder().get_embedding(content)
    return doc


@pytest.fixture
def live_db():
    """A fresh table against a live SingleStore. Recreated per test so each
    starts empty; dropped on teardown."""
    if _URL_DB:
        url = _LIVE_URL
    else:
        base = sqlalchemy.create_engine(_LIVE_URL)
        with base.connect() as conn:
            conn.execute(sqlalchemy.text(f"CREATE DATABASE IF NOT EXISTS {LIVE_DB}"))
            conn.commit()
        url = (_LIVE_URL.rstrip("/")) + "/" + LIVE_DB
    db = SingleStore(
        collection=TEST_COLLECTION,
        schema=LIVE_DB,
        db_url=url,
        embedder=_DeterministicEmbedder(),
    )
    try:
        db.drop()
    except Exception:
        pass
    db.create()
    yield db
    try:
        db.drop()
    except Exception:
        pass


def _alice_docs() -> List[Document]:
    return [Document(name="alice-salary", content="Alice's salary is 180k.")]


def _bob_docs() -> List[Document]:
    return [Document(name="bob-salary", content="Bob's salary is 215k.")]


def _shared_docs() -> List[Document]:
    return [Document(name="company-holidays", content="The office is closed Jan 1.")]


@_live
class TestLiveSearchIsolation:
    """The load-bearing live test: alice's search returns her chunks plus
    shared chunks, but never bob's."""

    @pytest.fixture
    def populated(self, live_db):
        live_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        live_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        live_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return live_db

    def test_alice_sees_own_and_shared(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "company-holidays" in names

    def test_alice_never_sees_bob(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id="alice")}
        assert "bob-salary" not in names

    def test_bob_never_sees_alice(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id="bob")}
        assert "alice-salary" not in names

    def test_admin_sees_everything(self, populated):
        names = {d.name for d in populated.search("salary", limit=10, user_id=None)}
        assert {"alice-salary", "bob-salary", "company-holidays"} <= names


@_live
class TestLiveClobberAndDedupe:
    def test_two_users_same_content_and_hash_coexist(self, live_db):
        live_db.insert(content_hash="SAME", documents=[_embedded("s", "The secret is 42.")], user_id="alice")
        live_db.insert(content_hash="SAME", documents=[_embedded("s", "The secret is 42.")], user_id="bob")
        assert live_db.get_count() == 2

    def test_same_user_reinsert_replaces(self, live_db):
        live_db.upsert(content_hash="H", documents=[_embedded("d", "v1")], user_id="alice")
        live_db.upsert(content_hash="H", documents=[_embedded("d", "v2")], user_id="alice")
        assert live_db.get_count() == 1

    def test_scoped_dedupe_keeps_other_owner(self, live_db):
        live_db.upsert(content_hash="SH", documents=[_embedded("ad", "alice v1")], user_id="alice")
        live_db.upsert(content_hash="SH", documents=[_embedded("bd", "bob v1")], user_id="bob")
        live_db.upsert(content_hash="SH", documents=[_embedded("ad", "alice v2")], user_id="alice")
        assert live_db.get_count() == 2

    def test_shared_upsert_does_not_wipe_scoped_owners(self, live_db):
        """A shared/admin re-ingest (``user_id=None``) under a hash that scoped
        owners already uploaded must scope its dedupe-delete to the shared bucket
        only — pre-fix it wiped every scoped owner sharing that content_hash."""
        live_db.upsert(content_hash="SAME", documents=[_embedded("ad", "alice v1")], user_id="alice")
        live_db.upsert(content_hash="SAME", documents=[_embedded("bd", "bob v1")], user_id="bob")
        # The wipe trigger: a shared re-ingest of the SAME content_hash.
        live_db.upsert(content_hash="SAME", documents=[_embedded("sd", "shared v1")], user_id=None)
        # Alice's and bob's scoped chunks both survive alongside the shared one.
        assert live_db.get_count() == 3
        assert "ad" in {d.name for d in live_db.search("alice", limit=10, user_id="alice")}
        assert "bd" in {d.name for d in live_db.search("bob", limit=10, user_id="bob")}


@_live
class TestLiveDeleteScoping:
    @pytest.fixture
    def populated(self, live_db):
        alice = Document(name="alice-doc", content="Alice's secret.")
        alice.content_id = "doc-1"
        bob = Document(name="bob-doc", content="Bob's secret.")
        bob.content_id = "doc-1"
        live_db.insert(content_hash="h-alice", documents=[alice], user_id="alice")
        live_db.insert(content_hash="h-bob", documents=[bob], user_id="bob")
        return live_db

    def test_scoped_delete_removes_only_callers(self, populated):
        assert populated.delete_by_content_id("doc-1", user_id="bob") is True
        assert populated.get_count() == 1

    def test_scoped_delete_misses_when_not_owner(self, populated):
        assert populated.delete_by_content_id("doc-1", user_id="carol") is False
        assert populated.get_count() == 2

    def test_unscoped_delete_wipes_all(self, populated):
        populated.delete_by_content_id("doc-1", user_id=None)
        assert populated.get_count() == 0


@_live
class TestLiveSchemaMigration:
    """A table created before this feature lacks ``user_id``. ``create()`` on a
    pre-existing legacy table must add the column in place (idempotently)."""

    def test_create_adds_user_id_to_legacy_table(self, live_db):
        # Drop and recreate a legacy-shaped table (no user_id column).
        live_db.drop()
        eng = sqlalchemy.create_engine(live_db.db_url)
        with eng.connect() as conn:
            conn.execute(
                sqlalchemy.text(
                    f"CREATE TABLE {LIVE_DB}.{TEST_COLLECTION} "
                    "(id TEXT, name TEXT, meta_data TEXT, content TEXT, "
                    f"embedding VECTOR({live_db.dimensions}) NOT NULL, `usage` TEXT, "
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, content_hash TEXT, content_id TEXT)"
                )
            )
            conn.commit()
        assert live_db._user_id_column_exists() is False

        live_db.create()  # should migrate
        assert live_db._user_id_column_exists() is True

        # Idempotent: a second create() changes nothing, not an error.
        live_db.create()
        assert live_db._user_id_column_exists() is True


@_live
class TestLiveAsyncIsolation:
    async def test_async_insert_and_search_isolated(self, live_db):
        await live_db.async_insert(
            content_hash="ha", documents=[_embedded("alice-a", "Alice async salary")], user_id="alice"
        )
        await live_db.async_insert(content_hash="hb", documents=[_embedded("bob-a", "Bob async salary")], user_id="bob")
        names = {d.name for d in await live_db.async_search("salary", limit=10, user_id="alice")}
        assert "alice-a" in names
        assert "bob-a" not in names

    async def test_async_upsert_scoped_dedupe(self, live_db):
        await live_db.async_upsert(content_hash="SH", documents=[_embedded("ad", "alice v1")], user_id="alice")
        await live_db.async_upsert(content_hash="SH", documents=[_embedded("bd", "bob v1")], user_id="bob")
        await live_db.async_upsert(content_hash="SH", documents=[_embedded("ad", "alice v2")], user_id="alice")
        assert live_db.get_count() == 2
