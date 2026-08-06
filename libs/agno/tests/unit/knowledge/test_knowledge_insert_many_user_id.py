"""Tests for insert_many() / ainsert_many() user_id parameter passing.

``insert()`` takes ``user_id`` and carries it to ``vector_db.insert(user_id=...)``.
Its siblings take ``*args, **kwargs``, so a ``user_id`` handed to them used to be
read by nobody and every chunk landed unowned with no error. These tests assert on
the owner the vector DB is actually handed, not on the shape of the internal call.

``paths`` and ``text_contents`` are driven end-to-end into the recording backend.
``urls``, ``topics`` and ``remote_content`` fetch before they reach the vector DB,
so those loops are checked at ``_load_content``, where ``content.user_id`` is the
single value the vector-DB write later reads.
"""

from typing import Any, Dict, List, Optional, Tuple

import pytest

from agno.knowledge.content import Content
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content.remote_content import GCSContent
from agno.vectordb.base import VectorDb


class RecordingVectorDb(VectorDb):
    """Minimal VectorDb stub that records the owner it was handed."""

    def __init__(self):
        self.seen_user_ids: List[Optional[str]] = []

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
        return False

    def upsert_available(self) -> bool:
        return False

    def insert(self, content_hash: str, documents, filters=None, user_id: Optional[str] = None) -> None:
        self.seen_user_ids.append(user_id)

    async def async_insert(self, content_hash: str, documents, filters=None, user_id: Optional[str] = None) -> None:
        self.seen_user_ids.append(user_id)

    def upsert(self, content_hash: str, documents, filters=None, user_id: Optional[str] = None) -> None:
        self.seen_user_ids.append(user_id)

    async def async_upsert(self, content_hash: str, documents, filters=None, user_id: Optional[str] = None) -> None:
        self.seen_user_ids.append(user_id)

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
    return Knowledge(vector_db=RecordingVectorDb())


@pytest.fixture
def text_files(tmp_path) -> List[str]:
    paths = []
    for name, body in (("alpha.txt", "alpha document"), ("beta.txt", "beta document")):
        file_path = tmp_path / name
        file_path.write_text(body)
        paths.append(str(file_path))
    return paths


def _origins(knowledge: Knowledge) -> List[Tuple[str, Optional[str]]]:
    """Record (content origin, owner) instead of loading, so the loops that
    fetch before they write can still be checked without the network."""
    seen: List[Tuple[str, Optional[str]]] = []

    def _record(content: Content, *args, **kwargs) -> None:
        for origin in ("path", "url", "file_data", "topics", "remote_content"):
            if getattr(content, origin, None):
                seen.append((origin, content.user_id))

    async def _arecord(content: Content, *args, **kwargs) -> None:
        _record(content)

    knowledge._load_content = _record  # type: ignore[method-assign]
    knowledge._aload_content = _arecord  # type: ignore[method-assign]
    return seen


def _all_content_kwargs() -> Dict[str, Any]:
    """One item for every loop of the keyword branch."""
    return {
        "paths": ["doc.txt"],
        "urls": ["https://example.com/doc.txt"],
        "text_contents": ["some text"],
        "topics": ["Cats"],
        "remote_content": GCSContent(bucket_name="bucket", blob_name="doc.txt"),
    }


# --- Keyword branch ---


def test_insert_many_keyword_branch_passes_user_id(knowledge, text_files):
    """user_id reaches the vector db for every chunk written by the paths loop."""
    knowledge.insert_many(paths=text_files, user_id="alice")

    assert knowledge.vector_db.seen_user_ids == ["alice", "alice"]


def test_insert_many_keyword_branch_text_contents_passes_user_id(knowledge):
    knowledge.insert_many(text_contents=["one", "two"], user_id="alice")

    assert knowledge.vector_db.seen_user_ids == ["alice", "alice"]


def test_insert_many_keyword_branch_covers_every_content_type(knowledge):
    """Every loop in the keyword branch forwards the owner - missing one is the
    bug this guards against."""
    seen = _origins(knowledge)

    knowledge.insert_many(**_all_content_kwargs(), user_id="alice")

    assert seen == [
        ("path", "alice"),
        ("url", "alice"),
        ("file_data", "alice"),
        ("topics", "alice"),
        ("remote_content", "alice"),
    ]


def test_insert_many_keyword_branch_without_user_id_is_unowned(knowledge, text_files):
    knowledge.insert_many(paths=text_files)

    assert knowledge.vector_db.seen_user_ids == [None, None]


@pytest.mark.asyncio
async def test_ainsert_many_keyword_branch_passes_user_id(knowledge, text_files):
    await knowledge.ainsert_many(paths=text_files, user_id="alice")

    assert knowledge.vector_db.seen_user_ids == ["alice", "alice"]


@pytest.mark.asyncio
async def test_ainsert_many_keyword_branch_covers_every_content_type(knowledge):
    seen = _origins(knowledge)

    await knowledge.ainsert_many(**_all_content_kwargs(), user_id="alice")

    assert seen == [
        ("path", "alice"),
        ("url", "alice"),
        ("file_data", "alice"),
        ("topics", "alice"),
        ("remote_content", "alice"),
    ]


@pytest.mark.asyncio
async def test_ainsert_many_keyword_branch_without_user_id_is_unowned(knowledge, text_files):
    await knowledge.ainsert_many(paths=text_files)

    assert knowledge.vector_db.seen_user_ids == [None, None]


# --- List-of-dicts branch ---


def test_insert_many_list_branch_applies_top_level_user_id(knowledge):
    knowledge.insert_many([{"text_content": "one"}, {"text_content": "two"}], user_id="alice")

    assert knowledge.vector_db.seen_user_ids == ["alice", "alice"]


def test_insert_many_list_branch_per_item_user_id_wins(knowledge):
    """A per-item owner overrides the top-level one, so a single call can mix
    owners."""
    knowledge.insert_many(
        [
            {"text_content": "one", "user_id": "bob"},
            {"text_content": "two"},
        ],
        user_id="alice",
    )

    assert knowledge.vector_db.seen_user_ids == ["bob", "alice"]


def test_insert_many_list_branch_per_item_user_id_without_top_level(knowledge):
    knowledge.insert_many(
        [
            {"text_content": "one", "user_id": "bob"},
            {"text_content": "two"},
        ]
    )

    assert knowledge.vector_db.seen_user_ids == ["bob", None]


def test_insert_many_list_branch_without_user_id_is_unowned(knowledge):
    knowledge.insert_many([{"text_content": "one"}, {"text_content": "two"}])

    assert knowledge.vector_db.seen_user_ids == [None, None]


@pytest.mark.asyncio
async def test_ainsert_many_list_branch_applies_top_level_user_id(knowledge):
    await knowledge.ainsert_many([{"text_content": "one"}, {"text_content": "two"}], user_id="alice")

    assert knowledge.vector_db.seen_user_ids == ["alice", "alice"]


@pytest.mark.asyncio
async def test_ainsert_many_list_branch_per_item_user_id_wins(knowledge):
    await knowledge.ainsert_many(
        [
            {"text_content": "one", "user_id": "bob"},
            {"text_content": "two"},
        ],
        user_id="alice",
    )

    assert knowledge.vector_db.seen_user_ids == ["bob", "alice"]


@pytest.mark.asyncio
async def test_ainsert_many_list_branch_without_user_id_is_unowned(knowledge):
    await knowledge.ainsert_many([{"text_content": "one"}, {"text_content": "two"}])

    assert knowledge.vector_db.seen_user_ids == [None, None]
