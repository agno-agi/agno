from typing import Any, Dict, List, Optional

import pytest

from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.base import VectorDb


class MockVectorDb(VectorDb):
    """Minimal in-memory VectorDb stub to capture inserts for assertions."""

    def __init__(self) -> None:
        self._inserted: Dict[str, List[Document]] = {}
        self._exists: bool = True

    # Lifecycle / existence
    def create(self) -> None:
        self._exists = True

    async def async_create(self) -> None:
        self._exists = True

    def exists(self) -> bool:
        return self._exists

    async def async_exists(self) -> bool:
        return self._exists

    def drop(self) -> None:
        self._inserted.clear()
        self._exists = False

    async def async_drop(self) -> None:
        self.drop()

    # Presence helpers
    def name_exists(self, name: str) -> bool:
        return False

    def async_name_exists(self, name: str) -> bool:
        return False

    def id_exists(self, id: str) -> bool:
        return False

    def content_hash_exists(self, content_hash: str) -> bool:
        return False

    # Insert / Upsert
    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        self._inserted[content_hash] = documents

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        self._inserted[content_hash] = documents

    def upsert_available(self) -> bool:
        return False

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        self._inserted[content_hash] = documents

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        self._inserted[content_hash] = documents

    # Search
    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        return []

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        return []

    # Search types
    def get_supported_search_types(self) -> List[str]:
        return None

    # Deletes / updates (not used in these tests)
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
        return True

    # Helper for tests
    def get_all_inserted_documents(self) -> List[Document]:
        all_docs: List[Document] = []
        for docs in self._inserted.values():
            all_docs.extend(docs)
        return all_docs


# Diverse text samples to exercise UTF-8 handling across scripts and edge cases
UTF8_SAMPLES = [
    "你好",  # Chinese
    "こんにちは",  # Japanese
    "안녕하세요",  # Korean
    "Привет",  # Cyrillic
    "مرحبا",  # Arabic
    "नमस्ते",  # Devanagari
    "שלום",  # Hebrew
    "Café naïve – élève",  # Accented Latin, en dash
    "🙂🚀✨",  # Emoji sequence
    "e\u0301 vs é",  # combining mark vs precomposed
]


def _assert_insert_contains_text(fake_db: MockVectorDb, expected: str) -> None:
    docs = fake_db.get_all_inserted_documents()
    assert len(docs) >= 1
    contents = "\n".join([getattr(d, "content", "") for d in docs])
    assert expected in contents


@pytest.mark.parametrize("text", UTF8_SAMPLES)
def test_insert_sync_handles_utf8_samples(text: str) -> None:
    fake_db = MockVectorDb()
    kb = Knowledge(vector_db=fake_db)
    kb.insert(text_content=text)
    _assert_insert_contains_text(fake_db, text)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", UTF8_SAMPLES)
async def test_ainsert_handles_utf8_samples(text: str) -> None:
    fake_db = MockVectorDb()
    kb = Knowledge(vector_db=fake_db)
    await kb.ainsert(text_content=text)
    _assert_insert_contains_text(fake_db, text)


def test_insert_sync_replaces_invalid_surrogates() -> None:
    # Lone surrogate characters are not valid in UTF-8; they should be replaced with U+FFFD
    bad_text = "bad\udffftext"
    fake_db = MockVectorDb()
    kb = Knowledge(vector_db=fake_db)
    kb.insert(text_content=bad_text)
    docs = fake_db.get_all_inserted_documents()
    contents = "\n".join([getattr(d, "content", "") for d in docs])
    # Some environments render replacement as '?' when logging/printing
    assert "\ufffd" in contents or "�" in contents or "?" in contents


@pytest.mark.asyncio
async def test_ainsert_replaces_invalid_surrogates() -> None:
    bad_text = "\ud800orphan"
    fake_db = MockVectorDb()
    kb = Knowledge(vector_db=fake_db)
    await kb.ainsert(text_content=bad_text)
    docs = fake_db.get_all_inserted_documents()
    contents = "\n".join([getattr(d, "content", "") for d in docs])
    assert "\ufffd" in contents or "�" in contents or "?" in contents
