"""SingleStore per-user RAG isolation contract.

The owner is a first-class ``user_id`` column (NULL = the shared bucket).
Scoped searches match ``user_id = caller OR user_id IS NULL`` so admin-uploaded
shared content stays discoverable; unscoped (admin) searches see everything.
``delete_by_content_id`` scopes to the caller so one user cannot wipe another's
chunks under a guessed content_id.

Two doubles drive this file, because neither one alone covers the contract.

``_CapturingSession`` records the statements the adapter built, so the SQL can be
compiled and inspected — the bound owner, the ``USING HASH`` DDL, the index probe
— without a running SingleStore.

``_RowSession`` applies those same statements to an in-memory row list, the way
``FakeSession`` does in ``test_pgvector_user_isolation.py``. Grepping compiled SQL
for ``user_id IS NULL`` passes on a predicate that still matches every row, so the
isolation itself is asserted here on the rows a query returns.
"""

from hashlib import md5
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Engine
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList, Null, TextClause
from sqlalchemy.sql.expression import Delete, Insert, Select

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


def _bob_docs() -> List[Document]:
    return [Document(name="bob-salary", content="Bob's salary is 215k.")]


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


class Unsupported(Exception):
    """The evaluator met a clause it does not model."""


def matches(row: Dict[str, Any], clause) -> bool:
    """Evaluate the predicate shapes this backend builds.

    Only ``col = value``, ``col IS NULL`` and AND/OR of those are modelled;
    anything else raises so a predicate that changes shape fails loudly rather
    than quietly matching every row.
    """
    if isinstance(clause, BooleanClauseList):
        results = [matches(row, part) for part in clause.clauses]
        return all(results) if clause.operator is operators.and_ else any(results)
    if isinstance(clause, BinaryExpression):
        column = getattr(clause.left, "name", None)
        if column is None:
            raise Unsupported(str(clause))
        if isinstance(clause.right, Null):
            if clause.operator is not operators.is_:
                raise Unsupported(str(clause))
            return row.get(column) is None
        if clause.operator is not operators.eq:
            raise Unsupported(str(clause))
        return row.get(column) == clause.right.value
    raise Unsupported(str(clause))


class _FakeResult:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return [SimpleNamespace(**row) for row in self._rows]

    @property
    def rowcount(self) -> int:
        return len(self._rows)


class _RowStore:
    """The rows every session the backend opens shares."""

    def __init__(self):
        self.rows: List[Dict[str, Any]] = []

    def __call__(self) -> "_RowSession":
        return _RowSession(self)

    def owners(self) -> List[str]:
        """Owner of every stored row, the shared bucket's NULL included."""
        return sorted((str(row.get("user_id")) for row in self.rows), key=str)


class _RowSession:
    """Applies the backend's statements to ``store.rows`` instead of recording them.

    The capturing double above proves the SQL carries the owner predicate; this
    one proves the predicate SELECTS the right rows, which is the assertion a
    tautological ``OR 1 = 1`` arm would otherwise sail straight through.
    """

    def __init__(self, store: _RowStore):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def begin(self):
        return self

    def commit(self):
        pass

    def execute(self, statement, params=None):
        if isinstance(statement, TextClause):
            return _FakeResult([])
        if isinstance(statement, Insert):
            record = {key: value for key, value in _params(statement).items() if not key.endswith("_1")}
            existing = next((row for row in self.store.rows if row["id"] == record["id"]), None)
            if existing is None:
                self.store.rows.append(dict(record))
            else:
                existing.update(record)
            return _FakeResult([])
        if isinstance(statement, Delete):
            kept = [row for row in self.store.rows if not matches(row, statement.whereclause)]
            deleted = len(self.store.rows) - len(kept)
            self.store.rows = kept
            return _FakeResult([{}] * deleted)
        if isinstance(statement, Select):
            clause = statement.whereclause
            rows = list(self.store.rows) if clause is None else [r for r in self.store.rows if matches(r, clause)]
            return _FakeResult(rows)
        return _FakeResult([])


@pytest.fixture
def row_db(singlestore_db) -> SingleStore:
    """The same SingleStore, but with its sessions applied to real rows."""
    store = _RowStore()
    singlestore_db.Session = MagicMock()
    singlestore_db.Session.begin.side_effect = store
    singlestore_db.rows = store  # type: ignore[attr-defined]
    return singlestore_db


def _names(documents: List[Document]) -> set:
    return {document.name for document in documents}


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
        base = md5(self.SAME.encode()).hexdigest()
        unscoped = md5(f"{base}_{self.HASH}".encode()).hexdigest()
        expected = md5(f"{unscoped}_alice".encode()).hexdigest()
        assert self._insert_id(singlestore_db, "alice") == expected

    def test_shifted_boundary_does_not_collide(self, singlestore_db):
        """The content_hash is collapsed before the owner is appended, so a
        content_hash that itself ends in ``_alice`` cannot land on alice's row."""
        alice_id = self._insert_id(singlestore_db, "alice")
        sess = _install_session(singlestore_db)
        singlestore_db.insert(
            content_hash=f"{self.HASH}_alice",
            documents=[Document(name="c", content=self.SAME)],
            user_id=None,
        )
        assert _params(_find_stmt(sess, "INSERT"))["id"] != alice_id

    def test_underscored_base_id_cannot_collide_with_a_different_split(self, singlestore_db):
        """The base id is collapsed to a fixed-length digest before the owner is
        folded in. Without that collapse the '_' boundary moves and
        ('doc', '1', 'a_lice') and ('doc', '1_a', 'lice') join to one row id,
        letting one owner overwrite the other's row."""
        assert singlestore_db._scoped_record_id("doc", "1", "a_lice") != singlestore_db._scoped_record_id(
            "doc", "1_a", "lice"
        )
        # whatever the caller passes, the owner is always folded into a fixed-length digest
        assert len(singlestore_db._scoped_record_id("doc_1_2_3", self.HASH, None)) == 32

    def test_shared_write_keeps_unfolded_base_id(self, singlestore_db):
        base = md5(self.SAME.encode()).hexdigest()
        expected = md5(f"{base}_{self.HASH}".encode()).hexdigest()
        shared_id = self._insert_id(singlestore_db, None)
        assert shared_id == expected
        # And distinct from an owned write of the same content.
        assert shared_id != self._insert_id(singlestore_db, "alice")


class TestOwnerFoldedIdOnEveryWritePath:
    """The fold has to happen at every site that builds a row id, not just
    ``insert``: ``_upsert`` is what the public ``upsert`` actually writes with,
    and the two async paths write rows of their own. A site that skipped the
    fold would park two owners on one row id while the sync ``insert`` tests
    above stayed green."""

    SAME = "The merger closes in Q3."
    HASH = "h"

    def _expected(self, user_id) -> str:
        base = md5(self.SAME.encode()).hexdigest()
        unscoped = md5(f"{base}_{self.HASH}".encode()).hexdigest()
        return unscoped if user_id is None else md5(f"{unscoped}_{user_id}".encode()).hexdigest()

    def _docs(self) -> List[Document]:
        return [Document(name="c", content=self.SAME)]

    def _written_id(self, sess) -> str:
        return _params(_find_stmt(sess, "INSERT"))["id"]

    def _upsert_id(self, db, user_id) -> str:
        # Nothing to dedup, so upsert goes straight through to _upsert.
        db.content_hash_exists = MagicMock(return_value=False)
        sess = _install_session(db)
        db.upsert(content_hash=self.HASH, documents=self._docs(), user_id=user_id)
        return self._written_id(sess)

    async def _async_insert_id(self, db, user_id) -> str:
        sess = _install_session(db)
        await db.async_insert(content_hash=self.HASH, documents=self._docs(), user_id=user_id)
        return self._written_id(sess)

    async def _async_upsert_id(self, db, user_id) -> str:
        db.content_hash_exists = MagicMock(return_value=False)
        sess = _install_session(db)
        await db.async_upsert(content_hash=self.HASH, documents=self._docs(), user_id=user_id)
        return self._written_id(sess)

    def test_upsert_shared_keeps_unfolded_base_id(self, singlestore_db):
        assert self._upsert_id(singlestore_db, None) == self._expected(None)

    def test_upsert_two_owners_get_distinct_ids(self, singlestore_db):
        assert self._upsert_id(singlestore_db, "alice") != self._upsert_id(singlestore_db, "bob")

    async def test_async_insert_shared_keeps_unfolded_base_id(self, singlestore_db):
        assert await self._async_insert_id(singlestore_db, None) == self._expected(None)

    async def test_async_insert_two_owners_get_distinct_ids(self, singlestore_db):
        alice_id = await self._async_insert_id(singlestore_db, "alice")
        bob_id = await self._async_insert_id(singlestore_db, "bob")
        assert alice_id != bob_id

    async def test_async_upsert_shared_keeps_unfolded_base_id(self, singlestore_db):
        assert await self._async_upsert_id(singlestore_db, None) == self._expected(None)

    async def test_async_upsert_two_owners_get_distinct_ids(self, singlestore_db):
        alice_id = await self._async_upsert_id(singlestore_db, "alice")
        bob_id = await self._async_upsert_id(singlestore_db, "bob")
        assert alice_id != bob_id

    async def test_all_four_write_paths_agree_on_one_id(self, singlestore_db):
        """Same owner, same content, same hash -> the same row from any path, so
        an owner re-ingesting through a different entry point round-trips on its
        own row instead of forking a second one."""
        sess = _install_session(singlestore_db)
        singlestore_db.insert(content_hash=self.HASH, documents=self._docs(), user_id="alice")
        ids = {
            self._written_id(sess),
            self._upsert_id(singlestore_db, "alice"),
            await self._async_insert_id(singlestore_db, "alice"),
            await self._async_upsert_id(singlestore_db, "alice"),
        }
        assert ids == {self._expected("alice")}


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


class TestSearchIsolationContract:
    """The load-bearing test: alice's search returns her rows plus the shared
    ones, never bob's.

    Every other class here greps the compiled SQL for ``user_id IS NULL`` and
    friends, which a predicate can satisfy while still matching every row -
    ``(user_id = :uid OR user_id IS NULL OR 1 = 1)`` passes all of them. These
    tests run the statement against rows, the way ``FakeSession`` does in
    ``test_pgvector_user_isolation.py``, so a scope that only looks right fails.
    """

    @pytest.fixture
    def populated_db(self, row_db):
        """Three rows: one alice, one bob, one shared (NULL)."""
        row_db.insert(content_hash="ha", documents=_alice_docs(), user_id="alice")
        row_db.insert(content_hash="hb", documents=_bob_docs(), user_id="bob")
        row_db.insert(content_hash="hs", documents=_shared_docs(), user_id=None)
        return row_db

    def test_alice_sees_her_own_and_the_shared_row(self, populated_db):
        assert _names(populated_db.search("salary", limit=10, user_id="alice")) == {
            "alice-salary",
            "company-holidays",
        }

    def test_alice_never_sees_bobs_row(self, populated_db):
        """The isolation contract. If this fails the whole feature is broken -
        alice would be retrieving bob's confidential chunks."""
        for document in populated_db.search("salary", limit=10, user_id="alice"):
            assert "Bob's salary" not in document.content

    def test_bob_never_sees_alices_row(self, populated_db):
        assert "alice-salary" not in _names(populated_db.search("salary", limit=10, user_id="bob"))

    def test_unknown_owner_sees_only_the_shared_bucket(self, populated_db):
        """Carol owns nothing, so the NULL arm is all that matches."""
        assert _names(populated_db.search("salary", limit=10, user_id="carol")) == {"company-holidays"}

    def test_admin_sees_everything(self, populated_db):
        assert _names(populated_db.search("salary", limit=10, user_id=None)) == {
            "alice-salary",
            "bob-salary",
            "company-holidays",
        }

    def test_scoped_hash_delete_removes_only_the_owners_row(self, populated_db):
        """The rows the DELETE reached, not the text it compiled to."""
        populated_db._delete_by_content_hash("ha", user_id="bob")
        assert populated_db.rows.owners() == ["None", "alice", "bob"]

        populated_db._delete_by_content_hash("ha", user_id="alice")
        assert populated_db.rows.owners() == ["None", "bob"]

    def test_shared_hash_delete_leaves_every_owner_alone(self, populated_db):
        """``None`` addresses the shared bucket, so a shared re-upsert of content
        an owner also holds cannot wipe the owner's row."""
        populated_db.insert(content_hash="hs", documents=_alice_docs(), user_id="alice")

        populated_db._delete_by_content_hash("hs", user_id=None)

        assert populated_db.rows.owners() == ["alice", "alice", "bob"]

    def test_the_gate_sees_exactly_the_rows_the_delete_reaches(self, populated_db):
        """The dedup pair, both halves against the same rows: a hash bob privately
        holds is not the shared bucket's duplicate, and the shared hash is not his."""
        assert populated_db.content_hash_exists("hb", user_id="bob") is True
        assert populated_db.content_hash_exists("hb", user_id="alice") is False
        assert populated_db.content_hash_exists("hb", user_id=None) is False
        assert populated_db.content_hash_exists("hs", user_id=None) is True

    def test_scoped_upsert_of_identical_content_keeps_the_shared_row(self, populated_db):
        """The keystone. Bob upserts byte-identical content under his own scope -
        the company-wide document must survive and stay retrievable."""
        populated_db.upsert(content_hash="hs", documents=_shared_docs(), user_id="bob")

        assert _names(populated_db.search("holidays", limit=10, user_id="alice")) == {
            "alice-salary",
            "company-holidays",
        }

    def test_scoped_delete_by_content_id_spares_the_other_owner(self, populated_db):
        """Bob guesses alice's content_id under his own scope; her row survives."""
        alice = Document(name="alice-doc", content="Alice's secret.")
        alice.content_id = "doc-1"
        bob = Document(name="bob-doc", content="Bob's secret.")
        bob.content_id = "doc-1"
        populated_db.insert(content_hash="h-alice", documents=[alice], user_id="alice")
        populated_db.insert(content_hash="h-bob", documents=[bob], user_id="bob")

        populated_db.delete_by_content_id("doc-1", user_id="bob")

        assert "alice-doc" in _names(populated_db.search("secret", limit=10, user_id="alice"))
        assert "bob-doc" not in _names(populated_db.search("secret", limit=10, user_id="bob"))


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


class TestContentHashExistsScoping:
    """``content_hash_exists`` is the guard half of the pair above: ``upsert``
    only calls ``_delete_by_content_hash`` once this says True, so it has to see
    exactly the rows that delete can reach. Scoped to an owner it reads only that
    owner's rows; ``None`` reads the SHARED bucket (user_id IS NULL), NOT every
    owner."""

    def _select_stmt(self, db, user_id):
        sess = _install_session(db)
        db.content_hash_exists("h", user_id=user_id)
        return _find_stmt(sess, "SELECT")

    def test_scoped_check_restricts_to_owner(self, singlestore_db):
        stmt = self._select_stmt(singlestore_db, "alice")
        sql = str(stmt)
        assert "content_hash =" in sql
        assert "user_id =" in sql
        assert "alice" in _params(stmt).values()

    def test_none_check_scopes_to_shared_bucket(self, singlestore_db):
        """The regression. ``None`` used to drop the owner predicate and match any
        owner, so a hash alice privately held read as a duplicate for the shared
        bucket and a later shared publish under ``skip_if_exists`` was swallowed
        — while the delete this guards only ever reached ``user_id IS NULL``."""
        stmt = self._select_stmt(singlestore_db, None)
        sql = str(stmt)
        assert "content_hash =" in sql
        assert "user_id IS NULL" in sql
        assert "user_id =" not in sql

    def test_both_halves_of_the_dedup_pair_agree_on_none(self, singlestore_db):
        """The guard and the delete emit the same owner predicate for ``None``;
        the guard firing on rows the delete cannot reach is the whole bug."""
        guard = str(self._select_stmt(singlestore_db, None))
        sess = _install_session(singlestore_db, rowcount=1)
        singlestore_db._delete_by_content_hash("h", user_id=None)
        delete = str(_find_stmt(sess, "DELETE"))

        assert "user_id IS NULL" in guard
        assert "user_id IS NULL" in delete


class TestUserIdIndexDDL:
    """The scope predicate filters on ``user_id`` on every read, delete and
    existence check, so the column carries an index. It is created in
    ``optimize()`` rather than inlined in the ``CREATE TABLE`` string: ``create()``
    returns early for a table that already exists, so a deployment that predates
    the column's index would otherwise never get one."""

    INDEX = f"idx_{TEST_COLLECTION}_user_id"

    def _optimize_sql(self, db, index_exists: bool) -> List[str]:
        """Every statement ``optimize()`` sends, with the existence probe
        answering ``index_exists``."""
        db._index_exists = MagicMock(return_value=index_exists)
        connection = MagicMock()
        db.db_engine.connect.return_value.__enter__.return_value = connection
        db.optimize()
        return [str(call.args[0]) for call in connection.execute.call_args_list]

    def test_optimize_creates_a_hash_index_on_user_id(self, singlestore_db):
        sql = self._optimize_sql(singlestore_db, index_exists=False)
        assert len(sql) == 1
        assert sql[0] == (f"ALTER TABLE {TEST_SCHEMA}.{TEST_COLLECTION} ADD INDEX {self.INDEX} (user_id) USING HASH")

    def test_index_is_a_hash_index(self, singlestore_db):
        """USING HASH is load-bearing, not decoration: a SingleStore columnstore
        table — the default table type — rejects USING BTREE outright, and the
        predicate is pure equality either way."""
        assert "USING HASH" in self._optimize_sql(singlestore_db, index_exists=False)[0]

    def test_optimize_is_idempotent(self, singlestore_db):
        """``create()`` calls ``optimize()``, and an operator may call it again on
        a live table. A second ALTER would fail with a duplicate key name."""
        assert self._optimize_sql(singlestore_db, index_exists=True) == []

    def test_optimize_survives_a_server_that_rejects_the_ddl(self, singlestore_db):
        """An older SingleStore, or a column already indexed under another name,
        degrades to an unindexed table rather than failing the caller."""
        singlestore_db._index_exists = MagicMock(return_value=False)
        connection = MagicMock()
        connection.execute.side_effect = RuntimeError("Feature 'ADD INDEX' is not supported")
        singlestore_db.db_engine.connect.return_value.__enter__.return_value = connection

        singlestore_db.optimize()

    def test_create_indexes_a_new_table(self, singlestore_db):
        """The new-table path: ``create()`` builds the table and then routes
        through ``optimize()``, so a fresh deployment is indexed without the
        operator doing anything."""
        singlestore_db.table_exists = MagicMock(return_value=False)
        singlestore_db._index_exists = MagicMock(return_value=False)
        connection = MagicMock()
        singlestore_db.db_engine.connect.return_value.__enter__.return_value = connection

        singlestore_db.create()

        statements = [str(call.args[0]) for call in connection.execute.call_args_list]
        assert any("CREATE TABLE" in stmt for stmt in statements)
        assert any(f"ADD INDEX {self.INDEX} (user_id) USING HASH" in stmt for stmt in statements)

    def _probe_stmt(self, db, row):
        """Run the existence probe with the server answering ``row``, and return
        ``(result, statement)``."""
        connection = MagicMock()
        connection.execute.return_value.first.return_value = row
        db.db_engine.connect.return_value.__enter__.return_value = connection
        result = db._index_exists(self.INDEX)
        return result, connection.execute.call_args.args[0]

    def test_index_existence_probe_is_scoped_to_this_table(self, singlestore_db):
        """The probe binds schema/table/index — a like-named index on another
        table in the cluster must not read as ours and suppress the ALTER."""
        result, stmt = self._probe_stmt(singlestore_db, None)

        assert result is False
        assert "information_schema.STATISTICS" in str(stmt)
        assert stmt.compile().params == {
            "schema": TEST_SCHEMA,
            "table": TEST_COLLECTION,
            "index": self.INDEX,
        }

    def test_index_existence_probe_reports_a_hit(self, singlestore_db):
        assert self._probe_stmt(singlestore_db, (1,))[0] is True


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
