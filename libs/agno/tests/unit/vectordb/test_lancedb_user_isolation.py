"""LanceDB per-user RAG isolation contract.

LanceDB isolates on a dedicated top-level ``user_id`` column, pushed into a
SQL-ish ``where`` predicate. ``NULL`` means shared / unowned, so a scoped read
has to match the caller's id OR NULL — dropping the NULL arm hides every
admin-uploaded chunk, and dropping the whole predicate leaks every owner.

The predicate has to be applied with ``prefilter=True`` so it runs BEFORE the
ANN top-K; post-filtering silently truncates results, which was the broken
situation that made LanceDB unsafe under the prior design.

``FakeLanceTable`` stands in for the table: it really evaluates the predicate
text the backend built against its rows, so a wrong predicate returns the wrong
rows rather than a passing assertion about a call.
"""

import json
import re
from hashlib import md5
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from agno.knowledge.document import Document
from agno.vectordb.lancedb import LanceDb
from agno.vectordb.search import SearchType

TEST_TABLE = "test_isolation_table"

_EQUALS = re.compile(r"^(\w+)\s*=\s*'(.*)'$", re.DOTALL)
_IS_NULL = re.compile(r"^(\w+)\s+IS\s+NULL$", re.IGNORECASE)


class FakeQuery:
    """The chained query builder LanceDB hands back from ``Table.search()``."""

    def __init__(self, table: "FakeLanceTable"):
        self._table = table
        self._where: Optional[str] = None
        self._limit: Optional[int] = None
        self._columns: Optional[List[str]] = None

    def where(self, clause: str, prefilter: bool = False) -> "FakeQuery":
        self._where = clause
        self._table.where_calls.append((clause, prefilter))
        return self

    def limit(self, n: int) -> "FakeQuery":
        self._limit = n
        return self

    def select(self, columns: List[str]) -> "FakeQuery":
        self._columns = columns
        return self

    def nprobes(self, n: int) -> "FakeQuery":
        return self

    def vector(self, embedding) -> "FakeQuery":
        return self

    def text(self, query: str) -> "FakeQuery":
        return self

    def to_list(self) -> List[Dict[str, Any]]:
        rows = [row for row in self._table.rows if self._where is None or self._table.evaluate(row, self._where)]
        if self._limit is not None:
            rows = rows[: self._limit]
        if self._columns is not None:
            return [{column: row.get(column) for column in self._columns} for row in rows]
        return [dict(row) for row in rows]


class FakeLanceTable:
    """A LanceDB table stand-in that evaluates the ``where`` predicate for real.

    Only the grammar this backend emits is supported — ``col = 'value'`` and
    ``col IS NULL`` joined by ``OR`` / ``AND``, optionally parenthesised.
    Anything else raises, so a predicate that changes shape fails loudly
    instead of quietly matching every row.
    """

    def __init__(self, name: str, schema):
        self.name = name
        self.schema = schema
        self.rows: List[Dict[str, Any]] = []
        # Every (clause, prefilter) pair the backend applied, in call order.
        self.where_calls: List[tuple] = []
        self.fts_indexes: List[str] = []

    def evaluate(self, row: Dict[str, Any], clause: str) -> bool:
        clause = clause.strip()
        if clause.startswith("(") and clause.endswith(")"):
            clause = clause[1:-1].strip()
        if " OR " in clause:
            return any(self.evaluate(row, part) for part in clause.split(" OR "))
        if " AND " in clause:
            return all(self.evaluate(row, part) for part in clause.split(" AND "))

        is_null = _IS_NULL.match(clause)
        if is_null:
            return row.get(is_null.group(1)) is None
        equals = _EQUALS.match(clause)
        if equals:
            column, literal = equals.groups()
            # Undo the SQL escape so ``o''reilly`` compares as ``o'reilly``.
            return row.get(column) == literal.replace("''", "'")
        raise AssertionError(f"FakeLanceTable cannot evaluate predicate {clause!r}")

    def search(self, query=None, vector_column_name=None, query_type=None) -> FakeQuery:
        return FakeQuery(self)

    def add(self, data, on_bad_vectors=None, fill_value=None) -> None:
        self.rows.extend(data)

    def delete(self, predicate: str) -> None:
        self.rows = [row for row in self.rows if not self.evaluate(row, predicate)]

    def count_rows(self) -> int:
        return len(self.rows)

    def create_fts_index(self, column: str, replace: bool = False) -> None:
        self.fts_indexes.append(column)


@pytest.fixture
def lance_db(mock_embedder):
    """A LanceDb wired to FakeLanceTable — no connection, nothing on disk.

    ``create_table`` hands the fake the schema the backend really built, so the
    schema assertions below are about ``_base_schema`` rather than a stub.
    """
    connection = MagicMock()
    connection.list_tables.return_value.tables = []
    connection.open_table.side_effect = ValueError(f"Table {TEST_TABLE} was not found")
    connection.create_table.side_effect = lambda **kwargs: FakeLanceTable(kwargs["name"], kwargs["schema"])

    return LanceDb(table_name=TEST_TABLE, connection=connection, embedder=mock_embedder)


def _alice_docs() -> List[Document]:
    return [Document(name="alice-salary", content="Alice's salary is $180k.")]


def _bob_docs() -> List[Document]:
    return [Document(name="bob-salary", content="Bob's salary is $215k.")]


def _shared_docs() -> List[Document]:
    return [Document(name="company-holidays", content="The office is closed Jan 1.")]


class TestSchemaHasUserIdColumn:
    """Pin the schema. If somebody removes the column the isolation tests
    below would still pass (everything goes to NULL = looks shared)
    misleadingly; this test fails loudly at the schema level."""

    def test_user_id_column_exists_on_table(self, lance_db):
        column_names = lance_db.table.schema.names
        assert lance_db.USER_ID_COL in column_names

    def test_user_id_column_is_nullable(self, lance_db):
        field = lance_db.table.schema.field(lance_db.USER_ID_COL)
        assert field.nullable is True

    def test_user_id_col_constant_is_user_id(self):
        # If this changes, every persisted row's column would silently stop
        # being read by retrieval. Pin it.
        assert LanceDb.USER_ID_COL == "user_id"


class TestInsertPopulatesUserIdColumn:
    """The owner from the explicit ``user_id=`` kwarg lands in the column.
    Not in the JSON payload — that's the whole point of the refactor."""

    def test_explicit_user_id_persisted_in_column(self, lance_db):
        lance_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")

        rows = lance_db.table.search().select([lance_db.USER_ID_COL]).to_list()
        assert len(rows) == 1
        assert rows[0][lance_db.USER_ID_COL] == "alice"

    def test_none_user_id_persisted_as_null(self, lance_db):
        """A shared chunk has ``NULL`` in the column. Both isolation
        predicates (yours plus NULL) match this row."""
        lance_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)

        rows = lance_db.table.search().select([lance_db.USER_ID_COL]).to_list()
        assert len(rows) == 1
        assert rows[0][lance_db.USER_ID_COL] is None

    def test_user_id_omitted_defaults_to_null(self, lance_db):
        """Backwards-compatible: callers that never pass ``user_id`` get
        NULL (shared) — they're effectively opting out of isolation."""
        lance_db.insert(content_hash="h1", documents=_shared_docs())

        rows = lance_db.table.search().select([lance_db.USER_ID_COL]).to_list()
        assert rows[0][lance_db.USER_ID_COL] is None

    def test_owner_stays_out_of_the_payload_blob(self, lance_db):
        """``payload`` is opaque JSON, so an owner hidden in there could not be
        pushed into a ``where`` clause at all."""
        lance_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")

        assert "user_id" not in json.loads(lance_db.table.rows[0]["payload"])


class TestSearchIsolationContract:
    """The load-bearing test: alice's search returns her chunks plus shared
    chunks, but never bob's. This is what makes K2 actually work."""

    @pytest.fixture
    def populated_db(self, lance_db):
        """Three rows: one alice, one bob, one shared (NULL)."""
        lance_db.insert(content_hash="alice-doc", documents=_alice_docs(), user_id="alice")
        lance_db.insert(content_hash="bob-doc", documents=_bob_docs(), user_id="bob")
        lance_db.insert(content_hash="shared-doc", documents=_shared_docs(), user_id=None)
        return lance_db

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

    def test_unknown_owner_sees_only_the_shared_bucket(self, populated_db):
        """Carol owns nothing, so the NULL arm is all that matches."""
        results = populated_db.search(query="anything", limit=10, user_id="carol")
        assert {d.name for d in results} == {"company-holidays"}


class TestPredicatePushdown:
    """The predicate text the backend built, and that it is applied ahead of
    the ANN top-K rather than after it."""

    SCOPE = "(user_id = 'alice' OR user_id IS NULL)"

    @pytest.mark.parametrize("search_type", [SearchType.vector, SearchType.keyword, SearchType.hybrid])
    def test_every_search_type_prefilters_on_the_scope(self, lance_db, search_type):
        """All three read paths build the same clause and pass
        ``prefilter=True`` — post-filtering would truncate a scoped result set
        down to whatever survived the global top-K."""
        lance_db.search_type = search_type

        lance_db.search(query="salary", limit=5, user_id="alice")

        assert lance_db.table.where_calls == [(self.SCOPE, True)]

    def test_unscoped_search_applies_no_predicate(self, lance_db):
        """Callers who never pass ``user_id`` must get the query they always got."""
        lance_db.search(query="salary", limit=5, user_id=None)

        assert lance_db.table.where_calls == []


class TestDeleteByContentIdIsolation:
    """``delete_by_content_id(content_id, user_id=...)`` must scope the
    delete to the caller's bucket — otherwise Bob could guess Alice's
    content_id and wipe her chunks.

    LanceDB scopes via the ``user_id`` column (``WHERE user_id = X``
    in ``.where()`` before scanning payloads).
    """

    @pytest.fixture
    def populated_db(self, lance_db):
        """Two users own chunks under the SAME content_id 'doc-1'. This
        is the realistic adversarial scenario — Bob guesses the id and
        tries to delete it. Without ``user_id`` scoping he'd wipe both."""
        alice_doc = Document(name="alice-doc", content="Alice's secret.")
        alice_doc.content_id = "doc-1"
        bob_doc = Document(name="bob-doc", content="Bob's secret.")
        bob_doc.content_id = "doc-1"

        lance_db.insert(content_hash="h-alice", documents=[alice_doc], user_id="alice")
        lance_db.insert(content_hash="h-bob", documents=[bob_doc], user_id="bob")
        return lance_db

    def test_scoped_delete_only_removes_callers_chunks(self, populated_db):
        """Bob asks to delete 'doc-1' under his own scope — alice's
        chunks must remain."""
        populated_db.delete_by_content_id("doc-1", user_id="bob")

        rows = populated_db.table.search().select([populated_db.USER_ID_COL]).to_list()
        owners = sorted(r[populated_db.USER_ID_COL] for r in rows)
        assert owners == ["alice"], "Isolation broken: bob's scoped delete touched alice's chunks"

    def test_scoped_delete_narrows_on_the_owner_column(self, populated_db):
        """The delete scan is pushed down as ``user_id = 'bob'`` — note it has
        no NULL arm, so a scoped delete cannot reach the shared bucket either."""
        populated_db.delete_by_content_id("doc-1", user_id="bob")

        assert populated_db.table.where_calls[0] == ("user_id = 'bob'", False)

    def test_alice_can_delete_her_own(self, populated_db):
        populated_db.delete_by_content_id("doc-1", user_id="alice")

        rows = populated_db.table.search().select([populated_db.USER_ID_COL]).to_list()
        owners = sorted(r[populated_db.USER_ID_COL] for r in rows)
        assert owners == ["bob"]

    def test_unscoped_delete_wipes_everyone(self, populated_db):
        """Legacy behaviour: ``user_id=None`` deletes across all owners.
        Pin it so we notice if the default semantics change."""
        populated_db.delete_by_content_id("doc-1", user_id=None)

        assert populated_db.table.count_rows() == 0

    def test_scoped_delete_misses_when_user_does_not_own_anything(self, populated_db):
        """Carol has no chunks. Her scoped delete of doc-1 is a no-op."""
        populated_db.delete_by_content_id("doc-1", user_id="carol")

        assert populated_db.table.count_rows() == 2


class TestDocIdFoldsInTheOwner:
    """LanceDB derives the row id from the content, so two users uploading the
    same bytes used to land on one id. The dedupe delete addresses rows by id,
    which made that shared id a cross-tenant delete."""

    def test_two_owners_of_the_same_bytes_get_distinct_ids(self, lance_db):
        lance_db.insert(content_hash="h1", documents=[Document(name="t", content="Template.")], user_id="alice")
        lance_db.insert(content_hash="h1", documents=[Document(name="t", content="Template.")], user_id="bob")

        assert len({row["id"] for row in lance_db.table.rows}) == 2

    def test_unscoped_doc_id_is_unchanged(self, lance_db):
        """Existing tables keep their ids, so the fix is not a migration."""
        legacy = md5(f"{md5(b'Template.').hexdigest()}_h1".encode()).hexdigest()

        lance_db.insert(content_hash="h1", documents=[Document(name="t", content="Template.")])

        assert lance_db.table.rows[0]["id"] == legacy

    def test_scoped_doc_id_is_a_plain_digest(self, lance_db):
        """Fixed-length hex, so folding the owner in cannot make two different
        (id, owner) pairs collide the way a raw ``a_b`` join can."""
        assert len(lance_db._scoped_doc_id("base", "h1", "alice")) == 32
        assert lance_db._scoped_doc_id("base", "h1", None) == md5(b"base_h1").hexdigest()

    def test_underscored_base_id_cannot_collide_with_a_different_split(self, lance_db):
        """The base id is collapsed to a fixed-length digest before the owner is
        folded in. Without that collapse the '_' boundary moves and
        ('doc', '1', 'a_lice') and ('doc', '1_a', 'lice') join to one id, letting
        one owner overwrite the other's row."""
        assert lance_db._scoped_doc_id("doc", "1", "a_lice") != lance_db._scoped_doc_id("doc", "1_a", "lice")
        # whatever the caller passes, the owner is always folded into a fixed-length digest
        assert len(lance_db._scoped_doc_id("doc_1_2_3", "h1", None)) == 32


class TestUpsertDoesNotDestroyAnotherOwner:
    """``upsert`` deletes the previous copy of the content before writing. That
    delete has to address the same owner the write does."""

    @pytest.fixture
    def populated_db(self, lance_db):
        """Three owners under ONE content_hash - the collision case."""
        lance_db.upsert(content_hash="handbook", documents=_alice_docs(), user_id="alice")
        lance_db.upsert(content_hash="handbook", documents=_bob_docs(), user_id="bob")
        lance_db.upsert(content_hash="handbook", documents=_shared_docs())
        return lance_db

    def _owners(self, db):
        return sorted((row.get(db.USER_ID_COL) or "NULL") for row in db.table.rows)

    def _names(self, db):
        return sorted(json.loads(row["payload"])["name"] for row in db.table.rows)

    def test_second_owner_does_not_wipe_the_first(self, lance_db):
        lance_db.upsert(content_hash="handbook", documents=_alice_docs(), user_id="alice")
        lance_db.upsert(content_hash="handbook", documents=_bob_docs(), user_id="bob")

        assert self._owners(lance_db) == ["alice", "bob"]
        assert self._names(lance_db) == ["alice-salary", "bob-salary"]

    def test_identical_bytes_from_two_owners_both_survive(self, lance_db):
        """Same content AND same content_hash, so every derived value except the
        owner is equal."""
        lance_db.upsert(content_hash="h1", documents=[Document(name="t", content="Template.")], user_id="alice")
        lance_db.upsert(content_hash="h1", documents=[Document(name="t", content="Template.")], user_id="bob")

        assert self._owners(lance_db) == ["alice", "bob"]

    def test_shared_upsert_does_not_wipe_scoped_owners(self, populated_db):
        populated_db.upsert(content_hash="handbook", documents=_shared_docs())

        assert self._owners(populated_db) == ["NULL", "alice", "bob"]

    def test_scoped_upsert_does_not_wipe_the_shared_bucket(self, populated_db):
        populated_db.upsert(content_hash="handbook", documents=_alice_docs(), user_id="alice")

        assert self._owners(populated_db) == ["NULL", "alice", "bob"]

    def test_re_upsert_replaces_only_the_callers_row(self, populated_db):
        updated = [Document(name="alice-salary-v2", content="Alice's salary is $190k.")]

        populated_db.upsert(content_hash="handbook", documents=updated, user_id="alice")

        assert self._names(populated_db) == ["alice-salary-v2", "bob-salary", "company-holidays"]

    def test_dedupe_delete_narrows_on_the_owner(self, lance_db):
        """Both the existence check and the delete scan push ``user_id = 'alice'``
        down. No NULL arm: a scoped write must not reach the shared bucket."""
        lance_db.upsert(content_hash="handbook", documents=_alice_docs(), user_id="alice")
        lance_db.upsert(content_hash="handbook", documents=_alice_docs(), user_id="alice")

        assert lance_db.table.where_calls[-2:] == [("user_id = 'alice'", False), ("user_id = 'alice'", False)]

    def test_unscoped_dedupe_delete_addresses_the_shared_bucket(self, lance_db):
        """``IS NULL``, not "no predicate": a shared re-upsert must not be able to
        reach a scoped owner's identical-content rows."""
        lance_db.upsert(content_hash="handbook", documents=_shared_docs())
        lance_db.upsert(content_hash="handbook", documents=_shared_docs())

        assert lance_db.table.where_calls[-1] == ("user_id IS NULL", False)

    async def test_async_upsert_does_not_wipe_another_owner(self, lance_db):
        await lance_db.async_upsert(content_hash="handbook", documents=_alice_docs(), user_id="alice")
        await lance_db.async_upsert(content_hash="handbook", documents=_bob_docs(), user_id="bob")

        assert self._owners(lance_db) == ["alice", "bob"]


class TestContentHashExistsScope:
    """The existence gate that ``upsert`` consults before deleting."""

    @pytest.fixture
    def populated_db(self, lance_db):
        lance_db.insert(content_hash="handbook", documents=_alice_docs(), user_id="alice")
        return lance_db

    def test_scoped_check_only_sees_the_owner(self, populated_db):
        assert populated_db.content_hash_exists("handbook", user_id="alice") is True
        assert populated_db.content_hash_exists("handbook", user_id="bob") is False

    def test_unscoped_check_does_not_see_a_privately_owned_hash(self, populated_db):
        """The regression. ``Knowledge`` calls this with one argument for
        ``skip_if_exists``; it used to match across owners, so alice's private
        row swallowed a later shared publish of the same content and the shared
        (NULL) bucket never received it."""
        assert populated_db.content_hash_exists("handbook") is False

    def test_unscoped_check_sees_the_shared_bucket(self, populated_db):
        populated_db.insert(content_hash="handbook", documents=_shared_docs(), user_id=None)

        assert populated_db.content_hash_exists("handbook") is True

    def test_unscoped_check_applies_the_shared_bucket_predicate(self, populated_db):
        """``IS NULL``, not "no predicate" — the same clause
        ``_delete_by_content_hash`` emits for ``None``."""
        populated_db.table.where_calls.clear()

        populated_db.content_hash_exists("handbook")

        assert populated_db.table.where_calls == [("user_id IS NULL", False)]


class TestOwnerWhereClauseHelper:
    """The write-side clause builder: exact owner, no shared arm."""

    def test_none_addresses_the_shared_bucket(self, lance_db):
        assert lance_db._owner_where_clause(None) == "user_id IS NULL"

    def test_owner_has_no_null_arm(self, lance_db):
        clause = lance_db._owner_where_clause("alice")

        assert clause == "user_id = 'alice'"
        assert "IS NULL" not in clause

    def test_single_quote_in_user_id_is_escaped(self, lance_db):
        assert lance_db._owner_where_clause("o'reilly") == "user_id = 'o''reilly'"

    def test_quoted_owner_still_deletes_only_its_own_rows(self, lance_db):
        """The escaped clause has to survive evaluation, not just look right."""
        lance_db.upsert(content_hash="h1", documents=_alice_docs(), user_id="o'reilly")
        lance_db.upsert(content_hash="h1", documents=_bob_docs(), user_id="bob")

        lance_db.upsert(content_hash="h1", documents=_shared_docs(), user_id="o'reilly")

        owners = sorted(row[lance_db.USER_ID_COL] for row in lance_db.table.rows)
        assert owners == ["bob", "o'reilly"]


class TestWhereClauseHelper:
    """The clause builder is small enough to unit-test directly. We can
    catch escaping bugs and shared-NULL semantics without spinning up a DB."""

    def test_none_returns_no_clause(self, lance_db):
        assert lance_db._user_scope_where_clause(None) is None

    def test_simple_alice_clause(self, lance_db):
        # Must match the caller's id OR the shared (NULL) bucket — both.
        clause = lance_db._user_scope_where_clause("alice")
        assert "user_id = 'alice'" in clause
        assert "user_id IS NULL" in clause
        assert " OR " in clause

    def test_single_quote_in_user_id_is_escaped(self, lance_db):
        """SQL injection guard. A user_id like ``o'reilly`` must not break
        the predicate or open a query-injection hole."""
        clause = lance_db._user_scope_where_clause("o'reilly")
        # Doubled single-quote — standard SQL escaping.
        assert "user_id = 'o''reilly'" in clause

    def test_quoted_user_id_still_matches_only_its_own_rows(self, lance_db):
        """The escaped clause has to survive evaluation, not just look right:
        ``o'reilly`` sees his own row plus the shared one, never bob's."""
        lance_db.insert(content_hash="h1", documents=[Document(name="quoted", content="x")], user_id="o'reilly")
        lance_db.insert(content_hash="h2", documents=_bob_docs(), user_id="bob")
        lance_db.insert(content_hash="h3", documents=_shared_docs(), user_id=None)

        results = lance_db.search(query="x", limit=10, user_id="o'reilly")

        assert {d.name for d in results} == {"quoted", "company-holidays"}
