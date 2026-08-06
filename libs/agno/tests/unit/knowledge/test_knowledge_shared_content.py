"""Tests that shared (unowned) content survives a scoped caller's deletes.

Reads surface a scoped caller's own rows plus the unowned ones, so a delete that
reused that list would destroy org-wide content. Both the single-item and the
bulk path have to skip it, and neither may strip its vectors on the way past --
``delete_by_content_id`` carries no owner, so removing them would leave the row
behind pointing at nothing.
"""

from typing import Any, Dict, List

import pytest

from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.sqlite import SqliteDb
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.base import VectorDb

SHARED = "k_shared"
ALICE = "k_alice"
BOB = "k_bob"


class MockVectorDb(VectorDb):
    """Mock VectorDb that records which content ids were deleted."""

    def __init__(self):
        self.deleted_content_ids: List[str] = []

    def create(self) -> None:
        pass

    async def async_create(self) -> None:
        pass

    def name_exists(self, name: str) -> bool:
        return False

    async def async_name_exists(self, name: str) -> bool:
        return False

    def id_exists(self, id: str) -> bool:
        return False

    def content_hash_exists(self, content_hash: str) -> bool:
        return False

    def insert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    async def async_insert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    def upsert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    async def async_upsert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    def upsert_available(self) -> bool:
        return True

    def search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        return []

    async def async_search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        return []

    def drop(self) -> None:
        pass

    async def async_drop(self) -> None:
        pass

    def exists(self) -> bool:
        return True

    async def async_exists(self) -> bool:
        return True

    def delete(self) -> bool:
        return True

    def delete_by_id(self, id: str) -> bool:
        return True

    def delete_by_name(self, name: str) -> bool:
        return True

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        return True

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        pass

    def delete_by_content_id(self, content_id: str) -> bool:
        self.deleted_content_ids.append(content_id)
        return True

    def get_supported_search_types(self) -> List[str]:
        return ["vector"]


@pytest.fixture
def vector_db():
    return MockVectorDb()


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


class TestBulkDeleteSparesSharedContent:
    def test_bulk_delete_removes_only_own_rows(self, knowledge, vector_db):
        knowledge.remove_all_content(user_id="alice")

        assert _rows(knowledge) == [BOB, SHARED]
        assert vector_db.deleted_content_ids == [ALICE]

    async def test_async_bulk_delete_removes_only_own_rows(self, knowledge, vector_db):
        await knowledge.aremove_all_content(user_id="alice")

        assert _rows(knowledge) == [BOB, SHARED]
        assert vector_db.deleted_content_ids == [ALICE]

    def test_unscoped_bulk_delete_removes_everything(self, knowledge, vector_db):
        knowledge.remove_all_content()

        assert _rows(knowledge) == []
        assert sorted(vector_db.deleted_content_ids) == [ALICE, BOB, SHARED]


class TestSingleDeleteLeavesNoOrphanedVectors:
    """A refused delete must not take the vectors with it."""

    def test_shared_row_keeps_its_vectors(self, knowledge, vector_db):
        knowledge.remove_content_by_id(SHARED, user_id="alice")

        assert SHARED in _rows(knowledge)
        assert vector_db.deleted_content_ids == []

    async def test_async_shared_row_keeps_its_vectors(self, knowledge, vector_db):
        await knowledge.aremove_content_by_id(SHARED, user_id="alice")

        assert SHARED in _rows(knowledge)
        assert vector_db.deleted_content_ids == []

    def test_other_users_row_keeps_its_vectors(self, knowledge, vector_db):
        knowledge.remove_content_by_id(BOB, user_id="alice")

        assert BOB in _rows(knowledge)
        assert vector_db.deleted_content_ids == []

    def test_own_row_is_fully_removed(self, knowledge, vector_db):
        knowledge.remove_content_by_id(ALICE, user_id="alice")

        assert ALICE not in _rows(knowledge)
        assert vector_db.deleted_content_ids == [ALICE]

    def test_unscoped_delete_removes_shared_row_and_its_vectors(self, knowledge, vector_db):
        knowledge.remove_content_by_id(SHARED)

        assert SHARED not in _rows(knowledge)
        assert vector_db.deleted_content_ids == [SHARED]
