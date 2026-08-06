"""SingleStore per-user RAG isolation contract.

The owner is a first-class ``user_id`` column (NULL = the shared bucket).
Scoped searches match ``user_id = caller OR user_id IS NULL`` so admin-uploaded
shared content stays discoverable; unscoped (admin) searches see everything.
``delete_by_content_id`` scopes to the caller so one user cannot wipe another's
chunks under a guessed content_id.

The SQLAlchemy engine is mocked and the session is a capturing double, so the
adapter's SQL is compiled and inspected without a running SingleStore.
"""

from hashlib import md5
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Engine

from agno.knowledge.document import Document
from agno.vectordb.singlestore import SingleStore

TEST_COLLECTION = "iso_test"
TEST_SCHEMA = "iso_schema"


class _DeterministicEmbedder:
    """A tiny embedder that needs no network or API key."""

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


def _alice_docs() -> List[Document]:
    return [Document(name="alice-salary", content="Alice's salary is 180k.")]


def _shared_docs() -> List[Document]:
    return [Document(name="company-holidays", content="The office is closed Jan 1.")]


@pytest.fixture
def singlestore_db():
    """A SingleStore wired to a mocked engine — enough to compile every stmt."""
    with patch("agno.vectordb.singlestore.singlestore.sessionmaker"):
        return SingleStore(
            collection=TEST_COLLECTION,
            schema=TEST_SCHEMA,
            db_engine=MagicMock(spec=Engine),
            embedder=_DeterministicEmbedder(),
        )


class _CapturingSession:
    """A ``Session.begin()`` context-manager double that records every executed
    statement and returns a configurable result."""

    def __init__(self, first=None, scalar=None, fetchall=None, rowcount=1):
        self.captured: list = []
        self._first = first
        self._scalar = scalar
        self._fetchall = fetchall if fetchall is not None else []
        self._rowcount = rowcount

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt):
        self.captured.append(stmt)
        result = MagicMock()
        result.first.return_value = self._first
        result.scalar.return_value = self._scalar
        result.fetchall.return_value = self._fetchall
        result.rowcount = self._rowcount
        return result

    def commit(self):
        pass


def _install_session(db, **result_kwargs) -> _CapturingSession:
    """Route ``db.Session.begin()`` to a fresh capturing session."""
    sess = _CapturingSession(**result_kwargs)
    db.Session = MagicMock()
    db.Session.begin.return_value = sess
    return sess


def _find_stmt(sess: _CapturingSession, keyword: str):
    """First captured statement whose compiled SQL starts with ``keyword``."""
    for stmt in sess.captured:
        if str(stmt).strip().upper().startswith(keyword):
            return stmt
    raise AssertionError(f"no {keyword} statement captured; got {[str(s)[:40] for s in sess.captured]}")


def _params(stmt) -> dict:
    """MySQL-compiled bound parameters for a captured statement."""
    return stmt.compile(dialect=mysql.dialect()).params


class TestWriteStampsOwner:
    """The owner is stored as a first-class ``user_id`` column, not buried in
    meta_data. ``user_id=None`` persists NULL — the shared bucket."""

    def _insert_params(self, db, user_id):
        sess = _install_session(db)
        db.insert(content_hash="h", documents=[Document(name="d", content="c")], user_id=user_id)
        return _params(_find_stmt(sess, "INSERT"))

    def test_explicit_user_id_stamped(self, singlestore_db):
        assert self._insert_params(singlestore_db, "alice").get("user_id") == "alice"

    def test_none_user_id_stored_as_null(self, singlestore_db):
        assert self._insert_params(singlestore_db, None).get("user_id") is None


class TestOwnerFoldedId:
    """Two owners uploading the SAME content must get DISTINCT row ids (the
    owner is folded into the id). A shared (None) write keeps the un-folded
    base id, so a shared re-ingest round-trips on the same row."""

    SAME = "The merger closes in Q3."
    HASH = "h"

    def _insert_id(self, db, user_id) -> str:
        sess = _install_session(db)
        db.insert(content_hash=self.HASH, documents=[Document(name="c", content=self.SAME)], user_id=user_id)
        return _params(_find_stmt(sess, "INSERT"))["id"]

    def test_identical_content_two_owners_get_distinct_ids(self, singlestore_db):
        alice_id = self._insert_id(singlestore_db, "alice")
        bob_id = self._insert_id(singlestore_db, "bob")
        assert alice_id != bob_id

    def test_owner_fold_matches_expected_digest(self, singlestore_db):
        """base_id is caller-controlled and variable length, so it is collapsed with
        the content hash into a fixed-length digest before the owner is folded in.
        Joined raw, ('doc_1', 'alice') and ('doc', '1_alice') land on one row id."""
        base = md5(self.SAME.encode()).hexdigest()
        record_id = md5(f"{base}_{self.HASH}".encode()).hexdigest()
        expected = md5(f"{record_id}_alice".encode()).hexdigest()
        assert self._insert_id(singlestore_db, "alice") == expected

    def test_shared_write_keeps_unfolded_base_id(self, singlestore_db):
        base = md5(self.SAME.encode()).hexdigest()
        expected = md5(f"{base}_{self.HASH}".encode()).hexdigest()
        shared_id = self._insert_id(singlestore_db, None)
        assert shared_id == expected
        # And distinct from an owned write of the same content.
        assert shared_id != self._insert_id(singlestore_db, "alice")


class TestSearchScope:
    """A scoped search's WHERE clause is ``user_id = :uid OR user_id IS NULL``
    (own OR shared), with the caller bound in. Admin (``user_id=None``) adds no
    user predicate."""

    def _search_select(self, db, user_id):
        sess = _install_session(db)
        db.search("salary", limit=10, user_id=user_id)
        return _find_stmt(sess, "SELECT")

    def test_scoped_search_is_own_or_shared_with_uid_bound(self, singlestore_db):
        stmt = self._search_select(singlestore_db, "alice")
        sql = str(stmt)
        assert "user_id =" in sql
        assert "user_id IS NULL" in sql
        assert " OR " in sql
        # The caller id is a bound parameter (never interpolated).
        assert "alice" in _params(stmt).values()

    def test_scoped_search_binds_each_caller(self, singlestore_db):
        assert "bob" in _params(self._search_select(singlestore_db, "bob")).values()

    def test_admin_search_has_no_user_predicate(self, singlestore_db):
        assert "user_id" not in str(self._search_select(singlestore_db, None))

    async def test_async_search_scopes_too(self, singlestore_db):
        sess = _install_session(singlestore_db)
        await singlestore_db.async_search("salary", limit=10, user_id="alice")
        stmt = _find_stmt(sess, "SELECT")
        assert "user_id IS NULL" in str(stmt)
        assert "alice" in _params(stmt).values()


class TestUpsertDedupScoping:
    """The sync upsert dedup path keys on ``content_hash`` scoped by owner: it
    checks/deletes only the writer's own bucket, so a second owner uploading
    identical content can't evict the first owner's row."""

    def test_dedup_check_is_scoped_to_writing_owner(self, singlestore_db):
        singlestore_db.content_hash_exists = MagicMock(return_value=False)
        _install_session(singlestore_db)
        singlestore_db.upsert(content_hash="h1", documents=[Document(name="d", content="c")], user_id="bob")
        singlestore_db.content_hash_exists.assert_called_once_with("h1", user_id="bob")

    def test_dedup_delete_is_scoped_to_writing_owner(self, singlestore_db):
        # Writer's own chunk already exists -> a pre-delete fires, scoped to bob.
        singlestore_db.content_hash_exists = MagicMock(return_value=True)
        sess = _install_session(singlestore_db)
        singlestore_db.upsert(content_hash="h1", documents=[Document(name="d", content="c")], user_id="bob")
        delete_stmt = _find_stmt(sess, "DELETE")
        sql = str(delete_stmt)
        assert "content_hash =" in sql
        assert "user_id =" in sql
        params = _params(delete_stmt)
        assert params.get("content_hash_1") == "h1"
        assert "bob" in params.values()

    def test_shared_upsert_dedup_deletes_only_shared_bucket(self, singlestore_db):
        # A shared (None) re-ingest scopes its pre-delete to user_id IS NULL,
        # never touching an owner's identical-content row.
        singlestore_db.content_hash_exists = MagicMock(return_value=True)
        sess = _install_session(singlestore_db)
        singlestore_db.upsert(content_hash="h1", documents=[Document(name="d", content="c")], user_id=None)
        delete_stmt = _find_stmt(sess, "DELETE")
        sql = str(delete_stmt)
        assert "user_id IS NULL" in sql
        assert "user_id =" not in sql

    async def test_async_upsert_dedup_is_scoped_to_writing_owner(self, singlestore_db):
        """``async_upsert`` mirrors sync upsert's guard: because the table has no
        unique key (ON DUPLICATE KEY UPDATE never fires), it checks/deletes the
        writer's own bucket before inserting so re-upserting can't pile up dupes."""
        singlestore_db.content_hash_exists = MagicMock(return_value=True)
        singlestore_db._delete_by_content_hash = MagicMock()
        _install_session(singlestore_db)
        await singlestore_db.async_upsert(content_hash="h1", documents=[Document(name="d", content="c")], user_id="bob")
        singlestore_db.content_hash_exists.assert_called_once_with("h1", user_id="bob")
        singlestore_db._delete_by_content_hash.assert_called_once_with("h1", user_id="bob")


class TestDeleteByContentIdScoping:
    """``delete_by_content_id(content_id, user_id=...)`` restricts to that owner
    so Bob guessing Alice's content_id under his own scope can't touch her rows.
    Admin (``None``) spans all owners (content_id only)."""

    def _delete_stmt(self, db, user_id):
        sess = _install_session(db, rowcount=1)
        db.delete_by_content_id("doc-1", user_id=user_id)
        return _find_stmt(sess, "DELETE")

    def test_scoped_delete_restricts_to_owner(self, singlestore_db):
        stmt = self._delete_stmt(singlestore_db, "bob")
        sql = str(stmt)
        assert "content_id =" in sql
        assert "user_id =" in sql
        params = _params(stmt)
        assert params.get("content_id_1") == "doc-1"
        assert "bob" in params.values()

    def test_scoped_delete_binds_each_caller(self, singlestore_db):
        assert "carol" in _params(self._delete_stmt(singlestore_db, "carol")).values()

    def test_unscoped_delete_spans_all_owners(self, singlestore_db):
        assert "user_id" not in str(self._delete_stmt(singlestore_db, None))


class TestDeleteByContentHashScoping:
    """``_delete_by_content_hash`` scoped to an owner deletes only that owner's
    rows; ``None`` scopes to the SHARED bucket (user_id IS NULL), NOT every
    owner — so a shared re-upsert never wipes a scoped owner's identical row."""

    def _delete_stmt(self, db, user_id):
        sess = _install_session(db, rowcount=1)
        db._delete_by_content_hash("h", user_id=user_id)
        return _find_stmt(sess, "DELETE")

    def test_scoped_hash_delete_restricts_to_owner(self, singlestore_db):
        stmt = self._delete_stmt(singlestore_db, "alice")
        sql = str(stmt)
        assert "content_hash =" in sql
        assert "user_id =" in sql
        assert "alice" in _params(stmt).values()

    def test_none_hash_delete_scopes_to_shared_bucket(self, singlestore_db):
        stmt = self._delete_stmt(singlestore_db, None)
        sql = str(stmt)
        assert "content_hash =" in sql
        assert "user_id IS NULL" in sql
        assert "user_id =" not in sql


class TestAsyncWriteStampsOwner:
    """The async write path stamps the owner exactly like the sync path."""

    async def test_async_insert_stamps_owner(self, singlestore_db):
        sess = _install_session(singlestore_db)
        await singlestore_db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        assert _params(_find_stmt(sess, "INSERT")).get("user_id") == "alice"

    async def test_async_insert_none_is_null(self, singlestore_db):
        sess = _install_session(singlestore_db)
        await singlestore_db.async_insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        assert _params(_find_stmt(sess, "INSERT")).get("user_id") is None
