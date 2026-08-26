"""LanceDB per-user isolation: the owner lives in a nullable ``user_id`` column, NULL is the shared bucket."""

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
    """Fixture to create and clean up a LanceDb instance"""
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
    """Pin the schema."""

    def test_user_id_column_exists_on_table(self, lance_db):
        column_names = lance_db.table.schema.names
        assert lance_db.USER_ID_COL in column_names

    def test_user_id_column_is_nullable(self, lance_db):
        field = lance_db.table.schema.field(lance_db.USER_ID_COL)
        assert field.nullable is True


class TestWriteStampsOwner:
    """The owner from the explicit ``user_id=`` kwarg lands in the column."""

    def test_explicit_user_id_persisted_in_column(self, lance_db):
        lance_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")

        rows = lance_db.table.search().select([lance_db.USER_ID_COL]).to_list()
        assert len(rows) == 1
        assert rows[0][lance_db.USER_ID_COL] == "alice"

    def test_none_user_id_persisted_as_null(self, lance_db):
        lance_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)

        rows = lance_db.table.search().select([lance_db.USER_ID_COL]).to_list()
        assert len(rows) == 1
        assert rows[0][lance_db.USER_ID_COL] is None

    def test_user_id_omitted_defaults_to_null(self, lance_db):
        """Test that callers who never pass ``user_id`` get NULL (shared)"""
        lance_db.insert(content_hash="h1", documents=_shared_docs())

        rows = lance_db.table.search().select([lance_db.USER_ID_COL]).to_list()
        assert rows[0][lance_db.USER_ID_COL] is None


class TestSearchScope:
    """Test that a scoped search returns the caller's chunks plus shared chunks, never another user's."""

    @pytest.fixture
    def search_corpus(self, lance_db):
        """Three rows: one alice, one bob, one shared (NULL)."""
        lance_db.insert(content_hash="alice-doc", documents=_alice_docs(), user_id="alice")
        lance_db.insert(content_hash="bob-doc", documents=_bob_docs(), user_id="bob")
        lance_db.insert(content_hash="shared-doc", documents=_shared_docs(), user_id=None)
        return lance_db

    def test_alice_sees_her_own_chunk(self, search_corpus):
        results = search_corpus.search(query="salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "alice-salary" in names

    def test_alice_sees_shared_chunk(self, search_corpus):
        results = search_corpus.search(query="anything", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "company-holidays" in names

    def test_alice_never_sees_bobs_chunk(self, search_corpus):
        """The isolation contract."""
        results = search_corpus.search(query="salary", limit=10, user_id="alice")
        names = {d.name for d in results}
        assert "bob-salary" not in names

    def test_bob_never_sees_alices_chunk(self, search_corpus):
        results = search_corpus.search(query="salary", limit=10, user_id="bob")
        names = {d.name for d in results}
        assert "alice-salary" not in names

    def test_admin_sees_everything(self, search_corpus):
        """``user_id=None`` at search time means no scope — admin view."""
        results = search_corpus.search(query="anything", limit=10, user_id=None)
        names = {d.name for d in results}
        assert "alice-salary" in names
        assert "bob-salary" in names
        assert "company-holidays" in names


class TestDeleteScope:
    """Test that ``delete_by_content_id`` scopes the delete to the caller's own chunks."""

    @pytest.fixture
    def content_id_corpus(self, lance_db):
        """Two users own chunks under the same content_id 'doc-1'"""
        alice_doc = Document(name="alice-doc", content="Alice's secret.")
        alice_doc.content_id = "doc-1"
        bob_doc = Document(name="bob-doc", content="Bob's secret.")
        bob_doc.content_id = "doc-1"

        lance_db.insert(content_hash="h-alice", documents=[alice_doc], user_id="alice")
        lance_db.insert(content_hash="h-bob", documents=[bob_doc], user_id="bob")
        return lance_db

    def test_scoped_delete_only_removes_callers_chunks(self, content_id_corpus):
        """Bob asks to delete 'doc-1' under his own scope — alice's chunks must remain."""
        content_id_corpus.delete_by_content_id("doc-1", user_id="bob")

        rows = content_id_corpus.table.search().select([content_id_corpus.USER_ID_COL]).to_list()
        owners = sorted(r[content_id_corpus.USER_ID_COL] for r in rows)
        assert owners == ["alice"], "Isolation broken: bob's scoped delete touched alice's chunks"

    def test_alice_can_delete_her_own(self, content_id_corpus):
        content_id_corpus.delete_by_content_id("doc-1", user_id="alice")

        rows = content_id_corpus.table.search().select([content_id_corpus.USER_ID_COL]).to_list()
        owners = sorted(r[content_id_corpus.USER_ID_COL] for r in rows)
        assert owners == ["bob"]

    def test_unscoped_delete_wipes_everyone(self, content_id_corpus):
        """Legacy behaviour: ``user_id=None`` deletes across all owners."""
        content_id_corpus.delete_by_content_id("doc-1", user_id=None)

        assert content_id_corpus.table.count_rows() == 0

    def test_scoped_delete_misses_when_user_does_not_own_anything(self, content_id_corpus):
        content_id_corpus.delete_by_content_id("doc-1", user_id="carol")

        assert content_id_corpus.table.count_rows() == 2


class TestWhereClauseHelper:
    """Test the scope clause builder."""

    def test_none_returns_no_clause(self, lance_db):
        assert lance_db._user_scope_where_clause(None) is None

    def test_simple_alice_clause(self, lance_db):
        clause = lance_db._user_scope_where_clause("alice")
        assert "user_id = 'alice'" in clause
        assert "user_id IS NULL" in clause
        assert " OR " in clause

    def test_single_quote_in_user_id_is_escaped(self, lance_db):
        """SQL injection guard."""
        clause = lance_db._user_scope_where_clause("o'reilly")
        # Doubled single-quote — standard SQL escaping.
        assert "user_id = 'o''reilly'" in clause


class TestAsyncIsolation:
    """The async path must scope exactly as the sync one does.

    ``async_insert``/``async_upsert``/``async_search`` are separate implementations rather
    than thin wrappers, so a scoping bug can live in one and not the other.
    """

    @pytest.fixture
    def async_corpus(self, lance_db):
        lance_db.insert(content_hash="alice-doc", documents=_alice_docs(), user_id="alice")
        lance_db.insert(content_hash="bob-doc", documents=_bob_docs(), user_id="bob")
        lance_db.insert(content_hash="shared-doc", documents=_shared_docs(), user_id=None)
        return lance_db

    @pytest.mark.asyncio
    async def test_async_search_returns_own_and_shared_never_another_owner(self, async_corpus):
        names = {d.name for d in await async_corpus.async_search(query="salary", limit=10, user_id="alice")}

        assert "alice-salary" in names
        assert "bob-salary" not in names

    @pytest.mark.asyncio
    async def test_async_search_sees_the_shared_bucket(self, async_corpus):
        names = {d.name for d in await async_corpus.async_search(query="anything", limit=10, user_id="alice")}

        assert "company-holidays" in names

    @pytest.mark.asyncio
    async def test_async_unscoped_search_spans_every_owner(self, async_corpus):
        names = {d.name for d in await async_corpus.async_search(query="salary", limit=10, user_id=None)}

        assert {"alice-salary", "bob-salary"} <= names

    @pytest.mark.asyncio
    async def test_async_insert_stamps_the_owner(self, lance_db):
        await lance_db.async_insert(content_hash="alice-doc", documents=_alice_docs(), user_id="alice")
        await lance_db.async_insert(content_hash="bob-doc", documents=_bob_docs(), user_id="bob")

        names = {d.name for d in lance_db.search(query="salary", limit=10, user_id="alice")}
        assert "alice-salary" in names
        assert "bob-salary" not in names

    @pytest.mark.asyncio
    async def test_async_insert_with_no_owner_is_shared(self, lance_db):
        await lance_db.async_insert(content_hash="shared-doc", documents=_shared_docs(), user_id=None)

        names = {d.name for d in lance_db.search(query="anything", limit=10, user_id="alice")}
        assert "company-holidays" in names

    @pytest.mark.asyncio
    async def test_async_upsert_does_not_disturb_another_owner(self, lance_db):
        await lance_db.async_upsert(content_hash="h1", documents=_alice_docs(), user_id="alice")
        await lance_db.async_upsert(content_hash="h1", documents=_bob_docs(), user_id="bob")
        # Re-upserting alice's hash must leave bob's row alone
        await lance_db.async_upsert(content_hash="h1", documents=_alice_docs(), user_id="alice")

        assert {d.name for d in lance_db.search(query="salary", limit=10, user_id="bob")} >= {"bob-salary"}
