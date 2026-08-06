"""Tests for the owner scope of the ``skip_if_exists`` existence check.

``skip_if_exists`` used to gate on ``content_hash_exists(content_hash)`` with no
owner, so the first person to upload a file claimed it for everyone: a second
owner uploading the identical file was told it already existed and ended up with
no chunks of their own — and no way to read the first owner's, since retrieval is
scoped per user. These tests assert on the rows the vector DB actually ends up
holding, not on the shape of the internal call.

A set ``user_id`` matches only that owner's rows, the way the column-based
backends scope it (pgvector, LanceDB). ``None`` matches any owner, which is the
unscoped query the fix removed — modelling it that way is what makes the second
owner's denial observable here. Note the shipped backends read ``None`` more
narrowly, as the shared bucket alone (``user_id IS NULL``); no test below turns
on the difference.
"""

from typing import List, Optional, Tuple

import pytest

from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.base import VectorDb


class OwnerAwareVectorDb(VectorDb):
    """VectorDb stub that stores an owner per row and honours it on lookup."""

    def __init__(self):
        self.rows: List[Tuple[str, Optional[str]]] = []
        self.exists_calls: List[Tuple[str, Optional[str]]] = []

    def create(self) -> None:
        pass

    async def async_create(self) -> None:
        pass

    def name_exists(self, name: str) -> bool:
        return False

    def async_name_exists(self, name: str) -> bool:
        return False

    def id_exists(self, id: str) -> bool:
        return False

    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        self.exists_calls.append((content_hash, user_id))
        if user_id is None:
            return any(stored_hash == content_hash for stored_hash, _ in self.rows)
        return (content_hash, user_id) in self.rows

    def upsert_available(self) -> bool:
        return False

    def insert(self, content_hash: str, documents, filters=None, user_id: Optional[str] = None) -> None:
        self.rows.append((content_hash, user_id))

    async def async_insert(self, content_hash: str, documents, filters=None, user_id: Optional[str] = None) -> None:
        self.rows.append((content_hash, user_id))

    def upsert(self, content_hash: str, documents, filters=None, user_id: Optional[str] = None) -> None:
        self.rows.append((content_hash, user_id))

    async def async_upsert(self, content_hash: str, documents, filters=None, user_id: Optional[str] = None) -> None:
        self.rows.append((content_hash, user_id))

    def search(self, query: str, limit: int = 5, filters=None, user_id: Optional[str] = None) -> List[Document]:
        return []

    async def async_search(
        self, query: str, limit: int = 5, filters=None, user_id: Optional[str] = None
    ) -> List[Document]:
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

    def delete_by_metadata(self, metadata) -> bool:
        return True

    def update_metadata(self, content_id: str, metadata) -> None:
        pass

    def delete_by_content_id(self, content_id: str, user_id: Optional[str] = None) -> bool:
        return True

    def get_supported_search_types(self) -> List[str]:
        return ["vector"]


@pytest.fixture
def knowledge() -> Knowledge:
    return Knowledge(vector_db=OwnerAwareVectorDb())


@pytest.fixture
def handbook(tmp_path) -> str:
    """One file, uploaded by both owners, so both uploads share a content hash."""
    file_path = tmp_path / "handbook.txt"
    file_path.write_text("the company handbook")
    return str(file_path)


@pytest.fixture
def handbook_dir(tmp_path) -> str:
    """A directory upload, which fans out into one Content per file."""
    directory = tmp_path / "docs"
    directory.mkdir()
    (directory / "handbook.txt").write_text("the company handbook")
    (directory / "policies.txt").write_text("the company policies")
    return str(directory)


def _owners(knowledge: Knowledge) -> List[Optional[str]]:
    return [owner for _, owner in knowledge.vector_db.rows]


# --- The reported bug: a second owner is denied their own copy ---


def test_second_owner_gets_own_copy(knowledge, handbook):
    """Bob uploading the file Alice already uploaded gets his own chunks."""
    knowledge.insert(path=handbook, skip_if_exists=True, user_id="alice")
    knowledge.insert(path=handbook, skip_if_exists=True, user_id="bob")

    assert _owners(knowledge) == ["alice", "bob"]


@pytest.mark.asyncio
async def test_second_owner_gets_own_copy_async(knowledge, handbook):
    await knowledge.ainsert(path=handbook, skip_if_exists=True, user_id="alice")
    await knowledge.ainsert(path=handbook, skip_if_exists=True, user_id="bob")

    assert _owners(knowledge) == ["alice", "bob"]


def test_second_owner_gets_own_copy_from_text_content(knowledge):
    """The file_data loop takes the same owner as the path loop."""
    knowledge.insert(text_content="the company handbook", skip_if_exists=True, user_id="alice")
    knowledge.insert(text_content="the company handbook", skip_if_exists=True, user_id="bob")

    assert _owners(knowledge) == ["alice", "bob"]


def test_second_owner_gets_own_copy_from_directory(knowledge, handbook_dir):
    """A directory fans out into a Content per file; each one keeps the owner."""
    knowledge.insert(path=handbook_dir, skip_if_exists=True, user_id="alice")
    knowledge.insert(path=handbook_dir, skip_if_exists=True, user_id="bob")

    assert _owners(knowledge) == ["alice", "alice", "bob", "bob"]


# --- The behaviour skip_if_exists is there for, still intact ---


def test_same_owner_second_upload_is_skipped(knowledge, handbook):
    """The dedupe still fires within one owner - that is the whole point of the
    flag, and scoping must not turn it off."""
    knowledge.insert(path=handbook, skip_if_exists=True, user_id="alice")
    knowledge.insert(path=handbook, skip_if_exists=True, user_id="alice")

    assert _owners(knowledge) == ["alice"]


@pytest.mark.asyncio
async def test_same_owner_second_upload_is_skipped_async(knowledge, handbook):
    await knowledge.ainsert(path=handbook, skip_if_exists=True, user_id="alice")
    await knowledge.ainsert(path=handbook, skip_if_exists=True, user_id="alice")

    assert _owners(knowledge) == ["alice"]


def test_unscoped_duplicate_is_still_skipped(knowledge, handbook):
    """Deployments that never pass a user_id keep the pre-isolation behaviour."""
    knowledge.insert(path=handbook, skip_if_exists=True)
    knowledge.insert(path=handbook, skip_if_exists=True)

    assert _owners(knowledge) == [None]


def test_without_skip_if_exists_both_uploads_are_written(knowledge, handbook):
    knowledge.insert(path=handbook, user_id="alice")
    knowledge.insert(path=handbook, user_id="alice")

    assert _owners(knowledge) == ["alice", "alice"]


# --- The owner reaches the backend, for the origins that read before writing ---


def test_owner_reaches_the_existence_check(knowledge, handbook):
    knowledge.insert(path=handbook, skip_if_exists=True, user_id="alice")

    assert knowledge.vector_db.exists_calls
    assert {owner for _, owner in knowledge.vector_db.exists_calls} == {"alice"}


def test_topics_owner_reaches_the_existence_check(knowledge):
    """The topics loop rebuilds Content per topic; the owner has to survive that
    rebuild or every topic upload is checked against the shared bucket."""
    knowledge.insert(topics=["Cats"], skip_if_exists=True, user_id="alice")

    assert knowledge.vector_db.exists_calls
    assert {owner for _, owner in knowledge.vector_db.exists_calls} == {"alice"}


@pytest.mark.asyncio
async def test_topics_owner_reaches_the_existence_check_async(knowledge):
    await knowledge.ainsert(topics=["Cats"], skip_if_exists=True, user_id="alice")

    assert knowledge.vector_db.exists_calls
    assert {owner for _, owner in knowledge.vector_db.exists_calls} == {"alice"}


def test_unscoped_upload_reaches_the_existence_check_with_no_owner(knowledge, handbook):
    knowledge.insert(path=handbook, skip_if_exists=True)

    assert knowledge.vector_db.exists_calls == [(knowledge.vector_db.exists_calls[0][0], None)]
