"""SingleStore per-user isolation. No SingleStore image is available, so the emitted SQL is the contract."""

from hashlib import md5
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Engine

from agno.knowledge.document import Document
from agno.vectordb.singlestore import SingleStore

from .conftest import DeterministicEmbedder

TEST_COLLECTION = "iso_test"
TEST_SCHEMA = "iso_schema"


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
            embedder=DeterministicEmbedder(),
        )


class _CapturingSession:
    """A ``Session.begin()`` double that records executed statements and returns a configurable result."""

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
    """The owner is stored as a first-class ``user_id`` column, not buried in meta_data."""

    def _insert_params(self, db, user_id):
        sess = _install_session(db)
        db.insert(content_hash="h", documents=[Document(name="d", content="c")], user_id=user_id)
        return _params(_find_stmt(sess, "INSERT"))

    def test_explicit_user_id_stamped(self, singlestore_db):
        assert self._insert_params(singlestore_db, "alice").get("user_id") == "alice"

    def test_none_user_id_stored_as_null(self, singlestore_db):
        assert self._insert_params(singlestore_db, None).get("user_id") is None


class TestOwnerFoldedId:
    """Two owners uploading the same content get distinct row ids: the owner is folded into the id."""

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
        """The owner is folded into a fixed-length digest of base_id and content_hash."""
        base = md5(self.SAME.encode()).hexdigest()
        record_id = md5(f"{base}_{self.HASH}".encode()).hexdigest()
        expected = md5(f"{record_id}_alice".encode()).hexdigest()
        assert self._insert_id(singlestore_db, "alice") == expected

    def test_shared_write_keeps_unfolded_base_id(self, singlestore_db):
        base = md5(self.SAME.encode()).hexdigest()
        expected = md5(f"{base}_{self.HASH}".encode()).hexdigest()
        shared_id = self._insert_id(singlestore_db, None)
        assert shared_id == expected
        assert shared_id != self._insert_id(singlestore_db, "alice")


class TestSearchScope:
    """A scoped search filters on ``user_id = :uid OR user_id IS NULL`` — own rows plus shared."""

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
        # The caller id is bound, never interpolated.
        assert "alice" in _params(stmt).values()

    def test_scoped_search_binds_each_caller(self, singlestore_db):
        assert "bob" in _params(self._search_select(singlestore_db, "bob")).values()

    def test_admin_search_has_no_user_predicate(self, singlestore_db):
        assert "user_id" not in str(self._search_select(singlestore_db, None))

    @pytest.mark.asyncio
    async def test_async_search_scopes_too(self, singlestore_db):
        sess = _install_session(singlestore_db)
        await singlestore_db.async_search("salary", limit=10, user_id="alice")
        stmt = _find_stmt(sess, "SELECT")
        assert "user_id IS NULL" in str(stmt)
        assert "alice" in _params(stmt).values()


class TestUpsertDedupScope:
    """Upsert dedup keys on ``content_hash`` scoped by owner: it checks and clears only the writer's own bucket."""

    def test_dedup_check_is_scoped_to_writing_owner(self, singlestore_db):
        singlestore_db.content_hash_exists = MagicMock(return_value=False)
        _install_session(singlestore_db)
        singlestore_db.upsert(content_hash="h1", documents=[Document(name="d", content="c")], user_id="bob")
        singlestore_db.content_hash_exists.assert_called_once_with("h1", user_id="bob")

    def test_dedup_delete_is_scoped_to_writing_owner(self, singlestore_db):
        # The writer's own chunk already exists, so a pre-delete fires.
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
        singlestore_db.content_hash_exists = MagicMock(return_value=True)
        sess = _install_session(singlestore_db)
        singlestore_db.upsert(content_hash="h1", documents=[Document(name="d", content="c")], user_id=None)
        delete_stmt = _find_stmt(sess, "DELETE")
        sql = str(delete_stmt)
        assert "user_id IS NULL" in sql
        assert "user_id =" not in sql

    @pytest.mark.asyncio
    async def test_async_upsert_dedup_is_scoped_to_writing_owner(self, singlestore_db):
        """``async_upsert`` mirrors the sync guard: it clears the writer's own bucket before inserting."""
        singlestore_db.content_hash_exists = MagicMock(return_value=True)
        singlestore_db._delete_by_content_hash = MagicMock()
        _install_session(singlestore_db)
        await singlestore_db.async_upsert(content_hash="h1", documents=[Document(name="d", content="c")], user_id="bob")
        singlestore_db.content_hash_exists.assert_called_once_with("h1", user_id="bob")
        singlestore_db._delete_by_content_hash.assert_called_once_with("h1", user_id="bob")


class TestDeleteScope:
    """``delete_by_content_id`` with a ``user_id`` restricts the DELETE to that owner's rows."""

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


class TestDedupScope:
    """``_delete_by_content_hash`` deletes only that owner's rows; ``None`` scopes to the shared bucket."""

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


class TestAsyncIsolation:
    """The async write path stamps the owner exactly like the sync path."""

    @pytest.mark.asyncio
    async def test_async_insert_stamps_owner(self, singlestore_db):
        sess = _install_session(singlestore_db)
        await singlestore_db.async_insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        assert _params(_find_stmt(sess, "INSERT")).get("user_id") == "alice"

    @pytest.mark.asyncio
    async def test_async_insert_none_is_null(self, singlestore_db):
        sess = _install_session(singlestore_db)
        await singlestore_db.async_insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        assert _params(_find_stmt(sess, "INSERT")).get("user_id") is None
