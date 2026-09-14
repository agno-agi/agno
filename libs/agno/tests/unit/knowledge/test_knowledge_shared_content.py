"""Tests that shared (unowned) content survives a scoped caller's deletes.

Both the single-item and bulk paths must skip rows the caller does not own, and
leave their vectors alone -- ``delete_by_content_id`` takes no owner to scope by.
"""

from unittest.mock import MagicMock

import pytest

from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.sqlite import SqliteDb
from agno.knowledge.knowledge import Knowledge

SHARED = "k_shared"
ALICE = "k_alice"
BOB = "k_bob"


@pytest.fixture
def vector_db():
    return MagicMock()


@pytest.fixture
def knowledge(tmp_path, vector_db):
    db = SqliteDb(db_file=str(tmp_path / "knowledge_shared_content.db"))
    kb = Knowledge(name="handbook", vector_db=vector_db, contents_db=db)
    for content_id, owner in ((SHARED, None), (ALICE, "alice"), (BOB, "bob")):
        db.upsert_knowledge_content(
            KnowledgeRow(id=content_id, name=content_id, description="content", user_id=owner, linked_to=kb.name)
        )
    return kb


def _rows(knowledge):
    return sorted(row.id for row in knowledge.contents_db.get_knowledge_contents()[0])


def _vectors_deleted(vector_db):
    return sorted(call.args[0] for call in vector_db.delete_by_content_id.call_args_list)


class TestBulkDeleteSparesSharedContent:
    def test_bulk_delete_removes_only_own_rows(self, knowledge, vector_db):
        knowledge.remove_all_content(user_id="alice")

        assert _rows(knowledge) == [BOB, SHARED]
        assert _vectors_deleted(vector_db) == [ALICE]

    async def test_async_bulk_delete_removes_only_own_rows(self, knowledge, vector_db):
        await knowledge.aremove_all_content(user_id="alice")

        assert _rows(knowledge) == [BOB, SHARED]
        assert _vectors_deleted(vector_db) == [ALICE]

    def test_unscoped_bulk_delete_removes_everything(self, knowledge, vector_db):
        knowledge.remove_all_content()

        assert _rows(knowledge) == []
        assert _vectors_deleted(vector_db) == [ALICE, BOB, SHARED]


class TestSingleDeleteLeavesNoOrphanedVectors:
    """A refused delete must not take the vectors with it."""

    @pytest.mark.parametrize("content_id", [SHARED, BOB])
    def test_row_alice_does_not_own_keeps_its_vectors(self, knowledge, vector_db, content_id):
        knowledge.remove_content_by_id(content_id, user_id="alice")

        assert content_id in _rows(knowledge)
        assert _vectors_deleted(vector_db) == []

    async def test_async_shared_row_keeps_its_vectors(self, knowledge, vector_db):
        await knowledge.aremove_content_by_id(SHARED, user_id="alice")

        assert SHARED in _rows(knowledge)
        assert _vectors_deleted(vector_db) == []

    def test_own_row_is_fully_removed(self, knowledge, vector_db):
        knowledge.remove_content_by_id(ALICE, user_id="alice")

        assert ALICE not in _rows(knowledge)
        assert _vectors_deleted(vector_db) == [ALICE]

    def test_unscoped_delete_removes_shared_row_and_its_vectors(self, knowledge, vector_db):
        knowledge.remove_content_by_id(SHARED)

        assert SHARED not in _rows(knowledge)
        assert _vectors_deleted(vector_db) == [SHARED]

    def test_empty_string_is_a_real_owner(self, knowledge, vector_db):
        """``""`` scopes to itself; it is not a second spelling of "unscoped"."""
        knowledge.remove_content_by_id(SHARED, user_id="")

        assert SHARED in _rows(knowledge)
        assert _vectors_deleted(vector_db) == []
