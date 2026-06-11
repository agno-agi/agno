"""LanceDB per-user RAG isolation contract.

These tests prove that the column-based isolation actually works end-to-end
against a real LanceDB instance — alice can find her chunks plus shared
chunks, but never bob's. This is the canonical contract we'd want to mirror
across every backend that supports K2 isolation; it pairs with the safety
guarantees that the wrapper now provides via ``.where(prefilter=True)`` so
the predicate runs BEFORE the ANN top-K (not after, which was the broken
post-filter situation that made LanceDB unsafe under the prior design).
"""

import os
import shutil
from typing import List

import pytest

from agno.knowledge.document import Document
from agno.vectordb.lancedb import LanceDb

TEST_TABLE = "test_isolation_table"
TEST_PATH = "tmp/test_lancedb_isolation"


@pytest.fixture
def lance_db(mock_embedder):
    """A fresh LanceDb per test — the schema change for ``user_id`` is in the
    base schema and would conflict with any cached table from another test."""
    os.makedirs(TEST_PATH, exist_ok=True)
    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)
        os.makedirs(TEST_PATH)

    db = LanceDb(uri=TEST_PATH, table_name=TEST_TABLE, embedder=mock_embedder)
    db.create()
    yield db

    try:
        db.drop()
    except Exception:
        pass
    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)


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
        assert owners == ["alice"], (
            "Isolation broken: bob's scoped delete touched alice's chunks"
        )

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
