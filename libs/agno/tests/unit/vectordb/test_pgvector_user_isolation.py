"""PgVector per-user RAG isolation contract.

PgVector isolates on a nullable, indexed ``user_id`` column. ``NULL`` is the
shared bucket, which is the state every row written before this feature existed
is already in.

* Writes stamp the column and fold the owner into the primary key, so two users
  ingesting the same bytes get two rows instead of one row that changes hands.
* Writes with ``user_id=None`` keep the pre-isolation id, so an existing table
  keeps updating in place rather than growing a second copy of every row.
* The dedupe delete that ``upsert`` runs before writing is scoped to the same
  owner as the write - unscoped, it deletes another owner's chunks.
* Scoped reads match ``user_id = X OR user_id IS NULL``; unscoped reads apply no
  predicate at all.

``FakeSession`` executes the statements the backend built against an in-memory
row list, so a wrong predicate deletes the wrong rows rather than passing an
assertion about a call. The SQL asserted here is the text a real PostgreSQL 16 +
pgvector server was driven with.
"""

import uuid
from hashlib import md5
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import URL, Engine
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList, Null, TextClause
from sqlalchemy.sql.expression import Delete, Insert, Select

from agno.knowledge.document import Document
from agno.knowledge.embedder.base import Embedder
from agno.vectordb.pgvector import PgVector
from agno.vectordb.search import SearchType

TEST_TABLE = f"isolation_{uuid.uuid4().hex[:8]}"
TEST_SCHEMA = "ai"
TABLE = f"{TEST_SCHEMA}.{TEST_TABLE}"
TEST_DIMENSION = 8

ALICE = "Alice's salary is $180,000."
BOB = "Bob's salary is $215,000."
SHARED = "The office is closed on January 1."

HANDBOOK = "handbook-v1"


class Unsupported(Exception):
    """The evaluator met a clause it does not model."""


def matches(row: Dict[str, Any], clause) -> bool:
    """Evaluate the predicate shapes this backend builds for writes.

    Only ``col = value``, ``col IS NULL`` and AND/OR of those are modelled;
    anything else raises so a predicate that changes shape fails loudly.
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


def sql(statement) -> Tuple[str, Dict[str, Any]]:
    """The statement as PostgreSQL receives it: text plus its bound values.

    Kept parameterised rather than inlined, so the assertions below also pin
    that the owner travels as a bind and is never interpolated into the text.
    """
    if isinstance(statement, TextClause):
        return " ".join(str(statement).split()), {}
    compiled = statement.compile(dialect=postgresql.dialect())
    return " ".join(str(compiled).split()), dict(compiled.params)


class FakeResult:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def scalar(self):
        return len(self._rows)


class FakeSession:
    """Applies the backend's statements to ``rows``, and records their SQL.

    INSERT respects the primary key: a plain insert of a duplicate id raises the
    way PostgreSQL would, and ON CONFLICT DO UPDATE replaces the row in place -
    which is what makes an ownership transfer observable here.
    """

    def __init__(self, store: "FakeStore"):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def begin(self):
        return self

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def execute(self, statement, params=None):
        self.store.statements.append(sql(statement))

        if isinstance(statement, Insert):
            return self._insert(statement, params)
        if isinstance(statement, Delete):
            kept = [row for row in self.store.rows if not matches(row, statement.whereclause)]
            deleted = len(self.store.rows) - len(kept)
            self.store.rows = kept
            return FakeResult([{}] * deleted)
        if isinstance(statement, Select):
            return FakeResult(self._select(statement))
        return FakeResult([])

    def _insert(self, statement, params) -> FakeResult:
        records = params if params is not None else self._values_of(statement)
        on_conflict = statement._post_values_clause is not None
        for record in records:
            existing = next((row for row in self.store.rows if row["id"] == record["id"]), None)
            if existing is None:
                self.store.rows.append(dict(record))
            elif on_conflict:
                existing.update(record)
            else:
                raise AssertionError(f"duplicate key value violates unique constraint: {record['id']}")
        return FakeResult([])

    @staticmethod
    def _values_of(statement) -> List[Dict[str, Any]]:
        """Pull the rows back out of a multi-values INSERT ... ON CONFLICT."""
        compiled = statement.compile(dialect=postgresql.dialect())
        rows: Dict[int, Dict[str, Any]] = {}
        for key, value in compiled.params.items():
            column, _, index = key.rpartition("_m")
            rows.setdefault(int(index), {})[column] = value
        return [rows[index] for index in sorted(rows)]

    def _select(self, statement) -> List[Dict[str, Any]]:
        clause = statement.whereclause
        if clause is None:
            return list(self.store.rows)
        try:
            return [row for row in self.store.rows if matches(row, clause)]
        except Unsupported:
            # A read whose predicate carries vector distance maths. Those tests
            # assert on the SQL, not on returned rows.
            return []


class FakeStore:
    """The rows and the statement log shared by every session the backend opens."""

    def __init__(self):
        self.rows: List[Dict[str, Any]] = []
        self.statements: List[Tuple[str, Dict[str, Any]]] = []

    def __call__(self) -> FakeSession:
        return FakeSession(self)

    def owners(self) -> List[str]:
        return sorted((row.get("user_id") or "NULL") for row in self.rows)

    def contents(self) -> List[str]:
        return sorted(row["content"] for row in self.rows)

    def last(self, keyword: str) -> Tuple[str, Dict[str, Any]]:
        return next(entry for entry in reversed(self.statements) if entry[0].startswith(keyword))

    def any_text(self, fragment: str) -> bool:
        return any(fragment in text for text, _ in self.statements)

    def any_bind(self, key: str, value: Any) -> bool:
        return any(binds.get(key) == value for _, binds in self.statements)


@pytest.fixture
def embedder():
    """Specced so the async half gets awaitable embedding calls."""
    mock = Mock(spec=Embedder)
    mock.dimensions = TEST_DIMENSION
    mock.enable_batch = False
    mock.get_embedding_and_usage.return_value = ([0.1] * TEST_DIMENSION, {"tokens": 10})
    mock.async_get_embedding_and_usage.return_value = ([0.1] * TEST_DIMENSION, {"tokens": 10})
    return mock


@pytest.fixture
def pgvector_db(embedder):
    """A PgVector with a real table definition and a FakeStore for a database."""
    engine = MagicMock(spec=Engine)
    engine.url = MagicMock(spec=URL)
    engine.url.get_backend_name.return_value = "postgresql"

    with patch("agno.vectordb.pgvector.pgvector.scoped_session"):
        db = PgVector(table_name=TEST_TABLE, schema=TEST_SCHEMA, db_engine=engine, embedder=embedder)
    db.Session = FakeStore()  # type: ignore[assignment]
    return db


def doc(name: str, content: str, content_id: str = "cid") -> Document:
    return Document(name=name, content=content, content_id=content_id)


def seed(db: PgVector) -> None:
    """One row per owner under a single content_hash - the collision case."""
    db.upsert(HANDBOOK, [doc("alice", ALICE)], user_id="alice")
    db.upsert(HANDBOOK, [doc("bob", BOB)], user_id="bob")
    db.upsert(HANDBOOK, [doc("shared", SHARED)])


def legacy_id(content: str, content_hash: str) -> str:
    """The record id this backend produced before the owner was folded in."""
    return md5(f"{md5(content.encode()).hexdigest()}_{content_hash}".encode()).hexdigest()


class TestOwnerIsWritten:
    """The owner is a real column, and it reaches the primary key."""

    def test_table_has_a_nullable_user_id_column(self, pgvector_db):
        column = pgvector_db.table.c.user_id
        assert column.nullable is True

    def test_scoped_write_stamps_the_column(self, pgvector_db):
        pgvector_db.upsert(HANDBOOK, [doc("alice", ALICE)], user_id="alice")

        assert pgvector_db.Session.owners() == ["alice"]

    def test_unscoped_write_leaves_the_column_null(self, pgvector_db):
        pgvector_db.upsert(HANDBOOK, [doc("shared", SHARED)])

        assert pgvector_db.Session.owners() == ["NULL"]

    def test_two_owners_of_the_same_bytes_get_distinct_ids(self, pgvector_db):
        """The id is the primary key. Sharing it is what let one owner's write
        overwrite the other's row."""
        alice = pgvector_db._get_document_record(doc("t", "Quarterly template."), None, HANDBOOK, "alice")
        bob = pgvector_db._get_document_record(doc("t", "Quarterly template."), None, HANDBOOK, "bob")

        assert alice["id"] != bob["id"]

    def test_unscoped_record_id_is_unchanged(self, pgvector_db):
        """Existing tables keep updating in place, so the fix is not a migration."""
        record = pgvector_db._get_document_record(doc("legacy", SHARED), None, HANDBOOK, None)

        assert record["id"] == legacy_id(SHARED, HANDBOOK)

    def test_scoped_record_id_is_a_plain_digest(self, pgvector_db):
        """Fixed-length hex, so folding the owner in cannot make two different
        (id, owner) pairs collide the way a raw ``a_b`` join can."""
        scoped = pgvector_db._scoped_record_id("base", HANDBOOK, "alice")

        assert len(scoped) == 32
        assert pgvector_db._scoped_record_id("base", HANDBOOK, None) == md5(f"base_{HANDBOOK}".encode()).hexdigest()

    def test_underscored_base_id_cannot_collide_with_a_different_split(self, pgvector_db):
        """The base id is collapsed to a fixed-length digest before the owner is
        folded in. Without that collapse the '_' boundary moves and
        ('doc', '1', 'a_lice') and ('doc', '1_a', 'lice') join to one record id,
        letting one owner overwrite the other's row."""
        assert pgvector_db._scoped_record_id("doc", "1", "a_lice") != pgvector_db._scoped_record_id(
            "doc", "1_a", "lice"
        )
        # whatever the caller passes, the owner is always folded into a fixed-length digest
        assert len(pgvector_db._scoped_record_id("doc_1_2_3", HANDBOOK, None)) == 32

    def test_document_id_is_still_honoured(self, pgvector_db):
        """A caller-supplied Document.id seeds the derivation; the owner is
        folded on top of it, not instead of it."""
        supplied = doc("named", ALICE)
        supplied.id = "doc-42"

        record = pgvector_db._get_document_record(supplied, None, HANDBOOK, "alice")

        assert record["id"] == md5(f"{md5(b'doc-42_' + HANDBOOK.encode()).hexdigest()}_alice".encode()).hexdigest()


class TestUpsertDedupeIsScoped:
    """``upsert`` deletes the previous copy of the content first. That delete
    has to address the same owner the write does."""

    def test_scoped_dedupe_delete_names_the_owner(self, pgvector_db):
        pgvector_db.upsert(HANDBOOK, [doc("alice", ALICE)], user_id="alice")
        pgvector_db.upsert(HANDBOOK, [doc("alice", ALICE + " Updated.")], user_id="alice")

        text, binds = pgvector_db.Session.last("DELETE")
        assert text == (
            f"DELETE FROM {TABLE} WHERE {TABLE}.content_hash = %(content_hash_1)s AND {TABLE}.user_id = %(user_id_1)s"
        )
        assert binds["user_id_1"] == "alice"

    def test_unscoped_dedupe_delete_addresses_the_shared_bucket(self, pgvector_db):
        """``IS NULL``, not "no predicate": a shared re-upsert must not be able
        to reach a scoped owner's identical-content rows."""
        pgvector_db.upsert(HANDBOOK, [doc("shared", SHARED)])
        pgvector_db.upsert(HANDBOOK, [doc("shared", SHARED + " Confirmed.")])

        text, _ = pgvector_db.Session.last("DELETE")
        assert text == (
            f"DELETE FROM {TABLE} WHERE {TABLE}.content_hash = %(content_hash_1)s AND {TABLE}.user_id IS NULL"
        )

    def test_existence_check_is_scoped_to_the_owner(self, pgvector_db):
        pgvector_db.upsert(HANDBOOK, [doc("alice", ALICE)], user_id="alice")

        text, binds = pgvector_db.Session.statements[0]
        assert text == (
            f"SELECT 1 FROM {TABLE} WHERE {TABLE}.content_hash = %(content_hash_1)s "
            f"AND {TABLE}.user_id = %(user_id_1)s LIMIT %(param_1)s"
        )
        assert binds["user_id_1"] == "alice"

    def test_unscoped_existence_check_addresses_the_shared_bucket(self, pgvector_db):
        """``content_hash_exists`` without an owner is the gate ``Knowledge``
        calls for ``skip_if_exists``, and it is the guard half of the pair whose
        other half deletes ``WHERE user_id IS NULL``. It used to match any owner,
        so alice's private row swallowed a later shared publish of the same
        content and the shared bucket never received it."""
        pgvector_db.upsert(HANDBOOK, [doc("alice", ALICE)], user_id="alice")

        assert pgvector_db.content_hash_exists(HANDBOOK, user_id="alice") is True
        assert pgvector_db.content_hash_exists(HANDBOOK, user_id="bob") is False
        assert pgvector_db.content_hash_exists(HANDBOOK) is False

        text, _ = pgvector_db.Session.last("SELECT")
        assert text == (
            f"SELECT 1 FROM {TABLE} WHERE {TABLE}.content_hash = %(content_hash_1)s "
            f"AND {TABLE}.user_id IS NULL LIMIT %(param_1)s"
        )

    def test_shared_publish_survives_a_private_holder(self, pgvector_db):
        """The user-visible half: the shared publish is not skipped, so both the
        private row and the shared one exist afterwards."""
        pgvector_db.upsert(HANDBOOK, [doc("alice", ALICE)], user_id="alice")

        if not pgvector_db.content_hash_exists(HANDBOOK):
            pgvector_db.upsert(HANDBOOK, [doc("shared", SHARED)])

        assert pgvector_db.Session.owners() == ["NULL", "alice"]


class TestUpsertDoesNotDestroyAnotherOwner:
    """The regression: alice upserts, bob upserts the same content_hash."""

    def test_second_owner_does_not_wipe_the_first(self, pgvector_db):
        pgvector_db.upsert(HANDBOOK, [doc("alice", ALICE)], user_id="alice")
        pgvector_db.upsert(HANDBOOK, [doc("bob", BOB)], user_id="bob")

        assert pgvector_db.Session.owners() == ["alice", "bob"]
        assert pgvector_db.Session.contents() == sorted([ALICE, BOB])

    def test_identical_bytes_from_two_owners_both_survive(self, pgvector_db):
        """The worst case: same content AND same content_hash, so every derived
        value except the owner is equal."""
        pgvector_db.upsert(HANDBOOK, [doc("t", "Quarterly template.")], user_id="alice")
        pgvector_db.upsert(HANDBOOK, [doc("t", "Quarterly template.")], user_id="bob")

        assert pgvector_db.Session.owners() == ["alice", "bob"]

    def test_shared_upsert_does_not_wipe_scoped_owners(self, pgvector_db):
        seed(pgvector_db)

        pgvector_db.upsert(HANDBOOK, [doc("shared", SHARED + " Confirmed.")])

        assert pgvector_db.Session.owners() == ["NULL", "alice", "bob"]
        assert ALICE in pgvector_db.Session.contents()

    def test_scoped_upsert_does_not_wipe_the_shared_bucket(self, pgvector_db):
        seed(pgvector_db)

        pgvector_db.upsert(HANDBOOK, [doc("alice", ALICE + " Updated.")], user_id="alice")

        assert pgvector_db.Session.owners() == ["NULL", "alice", "bob"]
        assert pgvector_db.Session.contents() == sorted([ALICE + " Updated.", BOB, SHARED])

    def test_re_upsert_replaces_only_the_callers_row(self, pgvector_db):
        seed(pgvector_db)

        pgvector_db.upsert(HANDBOOK, [doc("alice", ALICE + " Updated.")], user_id="alice")

        assert ALICE not in pgvector_db.Session.contents()
        assert BOB in pgvector_db.Session.contents()

    def test_insert_of_the_same_bytes_by_two_owners_does_not_collide(self, pgvector_db):
        """``insert`` has no ON CONFLICT clause, so a shared primary key would be
        an integrity error rather than a silent overwrite."""
        pgvector_db.insert(HANDBOOK, [doc("t", "Quarterly template.")], user_id="alice")
        pgvector_db.insert(HANDBOOK, [doc("t", "Quarterly template.")], user_id="bob")

        assert pgvector_db.Session.owners() == ["alice", "bob"]


class TestOnConflictCannotTransferOwnership:
    """``ON CONFLICT DO UPDATE SET user_id = excluded.user_id`` rewrites the owner
    of whatever row it lands on. With the owner in the id it can only ever land
    on the caller's own row."""

    def test_upsert_statement_still_refreshes_the_owner(self, pgvector_db):
        pgvector_db.upsert(HANDBOOK, [doc("alice", ALICE)], user_id="alice")

        text, _ = pgvector_db.Session.last("INSERT")
        assert "ON CONFLICT (id) DO UPDATE SET" in text
        assert "user_id = excluded.user_id" in text

    def test_conflict_target_is_unreachable_from_another_owner(self, pgvector_db):
        pgvector_db.upsert(HANDBOOK, [doc("t", "Quarterly template.")], user_id="alice")
        alice_id = pgvector_db.Session.rows[0]["id"]

        pgvector_db.upsert(HANDBOOK, [doc("t", "Quarterly template.")], user_id="bob")

        rows = {row["user_id"]: row["id"] for row in pgvector_db.Session.rows}
        assert rows["alice"] == alice_id
        assert rows["bob"] != alice_id

    def test_same_owner_conflict_keeps_the_owner(self, pgvector_db):
        """Straight into ``_upsert`` twice, so the conflict clause is what
        collapses the two writes rather than the dedupe delete."""
        pgvector_db._upsert(HANDBOOK, [doc("alice", ALICE)], user_id="alice")
        pgvector_db._upsert(HANDBOOK, [doc("alice", ALICE)], user_id="alice")

        assert pgvector_db.Session.owners() == ["alice"]


class TestScopedReads:
    """The read predicate is ``user_id = X OR user_id IS NULL`` - the caller's own
    rows plus the shared bucket."""

    SCOPE = f"{TABLE}.user_id = %(user_id_1)s OR {TABLE}.user_id IS NULL"

    @pytest.mark.parametrize("search_type", [SearchType.vector, SearchType.keyword, SearchType.hybrid])
    def test_every_search_type_applies_the_scope(self, pgvector_db, search_type):
        pgvector_db.search_type = search_type

        pgvector_db.search("salary", limit=5, user_id="alice")

        assert pgvector_db.Session.any_text(self.SCOPE)
        assert pgvector_db.Session.any_bind("user_id_1", "alice")

    @pytest.mark.parametrize("search_type", [SearchType.vector, SearchType.keyword, SearchType.hybrid])
    def test_unscoped_search_applies_no_predicate(self, pgvector_db, search_type):
        pgvector_db.search_type = search_type

        pgvector_db.search("salary", limit=5)

        assert not pgvector_db.Session.any_text("user_id")

    def test_empty_string_owner_does_not_fall_back_to_admin(self, pgvector_db):
        """An empty string is not None, so it must still narrow."""
        pgvector_db.search("salary", limit=5, user_id="")

        assert pgvector_db.Session.any_text(self.SCOPE)
        assert pgvector_db.Session.any_bind("user_id_1", "")


class TestAsyncUpsertMatchesSync:
    """``async_upsert`` runs its own dedupe and its own id derivation."""

    @pytest.mark.asyncio
    async def test_second_owner_does_not_wipe_the_first(self, pgvector_db):
        await pgvector_db.async_upsert(HANDBOOK, [doc("alice", ALICE)], user_id="alice")
        await pgvector_db.async_upsert(HANDBOOK, [doc("bob", BOB)], user_id="bob")

        assert pgvector_db.Session.owners() == ["alice", "bob"]

    @pytest.mark.asyncio
    async def test_scoped_dedupe_delete_names_the_owner(self, pgvector_db):
        await pgvector_db.async_upsert(HANDBOOK, [doc("alice", ALICE)], user_id="alice")
        await pgvector_db.async_upsert(HANDBOOK, [doc("alice", ALICE + " Updated.")], user_id="alice")

        text, binds = pgvector_db.Session.last("DELETE")
        assert f"{TABLE}.user_id = %(user_id_1)s" in text
        assert binds["user_id_1"] == "alice"

    @pytest.mark.asyncio
    async def test_unscoped_dedupe_delete_addresses_the_shared_bucket(self, pgvector_db):
        await pgvector_db.async_upsert(HANDBOOK, [doc("shared", SHARED)])
        await pgvector_db.async_upsert(HANDBOOK, [doc("shared", SHARED + " Confirmed.")])

        text, _ = pgvector_db.Session.last("DELETE")
        assert f"{TABLE}.user_id IS NULL" in text

    @pytest.mark.asyncio
    async def test_async_insert_ids_are_owner_scoped(self, pgvector_db):
        await pgvector_db.async_insert(HANDBOOK, [doc("t", "Quarterly template.")], user_id="alice")
        await pgvector_db.async_insert(HANDBOOK, [doc("t", "Quarterly template.")], user_id="bob")

        assert pgvector_db.Session.owners() == ["alice", "bob"]

    @pytest.mark.asyncio
    async def test_async_unscoped_record_id_is_unchanged(self, pgvector_db):
        await pgvector_db.async_insert(HANDBOOK, [doc("shared", SHARED)])

        assert pgvector_db.Session.rows[0]["id"] == legacy_id(SHARED, HANDBOOK)
