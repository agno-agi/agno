"""Tests for exception handling in knowledge loading methods."""

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.base import VectorDb


class MockVectorDb(VectorDb):
    """Minimal VectorDb stub for testing."""

    def __init__(self) -> None:
        self._inserted: Dict[str, List[Document]] = {}
        self._exists: bool = True

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

    def name_exists(self, name: str) -> bool:
        return False

    def async_name_exists(self, name: str) -> bool:
        return False

    def id_exists(self, id: str) -> bool:
        return False

    def content_hash_exists(self, content_hash: str) -> bool:
        return False

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

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        return []

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        return []

    def get_supported_search_types(self) -> List[str]:
        return ["vector"]

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


class FailingReader:
    """Reader that raises exceptions for testing."""

    def __init__(self, error_message: str = "Read failed"):
        self.error_message = error_message

    def read(self, source, name=None, password=None) -> List[Document]:
        raise Exception(self.error_message)

    async def async_read(self, source, name=None, password=None) -> List[Document]:
        raise Exception(self.error_message)


@pytest.fixture
def knowledge():
    return Knowledge(vector_db=MockVectorDb())


# --- _load_from_path exception handling ---


def test_load_from_path_catches_reader_exception(knowledge, tmp_path):
    """Test that _load_from_path catches reader exceptions and marks content FAILED."""
    # Create a temporary file to test with
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    knowledge._insert_contents_db = MagicMock()
    knowledge._update_content = MagicMock()

    content = Content(path=str(test_file), reader=FailingReader("Token limit exceeded"))
    content.content_hash = "test_hash"
    content.id = "test_id"

    # Should not raise
    knowledge._load_from_path(content, upsert=False, skip_if_exists=False)

    # Content should be marked as failed
    assert content.status == ContentStatus.FAILED
    assert "Token limit exceeded" in content.status_message
    knowledge._update_content.assert_called()


@pytest.mark.asyncio
async def test_aload_from_path_catches_reader_exception(knowledge, tmp_path):
    """Test that _aload_from_path catches reader exceptions and marks content FAILED."""
    # Create a temporary file to test with
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    knowledge._ainsert_contents_db = AsyncMock()
    knowledge._aupdate_content = AsyncMock()

    content = Content(path=str(test_file), reader=FailingReader("Connection refused"))
    content.content_hash = "test_hash"
    content.id = "test_id"

    # Should not raise
    await knowledge._aload_from_path(content, upsert=False, skip_if_exists=False)

    assert content.status == ContentStatus.FAILED
    assert "Connection refused" in content.status_message


# --- _load_from_content exception handling ---


def test_load_from_content_catches_reader_exception(knowledge):
    """Test that _load_from_content catches exceptions and marks content FAILED."""
    knowledge._insert_contents_db = MagicMock()
    knowledge._update_content = MagicMock()

    content = Content(
        name="test",
        file_data="some text content",
        reader=FailingReader("Chunking failed"),
    )
    content.content_hash = "test_hash"
    content.id = "test_id"

    # Should not raise
    knowledge._load_from_content(content, upsert=False, skip_if_exists=False)

    assert content.status == ContentStatus.FAILED
    assert "Chunking failed" in content.status_message


@pytest.mark.asyncio
async def test_aload_from_content_catches_reader_exception(knowledge):
    """Test that _aload_from_content catches exceptions and marks content FAILED."""
    knowledge._ainsert_contents_db = AsyncMock()
    knowledge._aupdate_content = AsyncMock()

    content = Content(
        name="test",
        file_data="some text content",
        reader=FailingReader("Embedding API error"),
    )
    content.content_hash = "test_hash"
    content.id = "test_id"

    await knowledge._aload_from_content(content, upsert=False, skip_if_exists=False)

    assert content.status == ContentStatus.FAILED
    assert "Embedding API error" in content.status_message


# --- Token limit specific tests ---


def test_load_from_content_handles_token_limit_error(knowledge):
    """Test that token limit errors are caught and logged appropriately."""
    knowledge._insert_contents_db = MagicMock()
    knowledge._update_content = MagicMock()

    content = Content(
        name="large_doc",
        file_data="x" * 100000,  # Large content
        reader=FailingReader("maximum context length exceeded"),
    )
    content.content_hash = "test_hash"
    content.id = "test_id"

    # Should not raise, should mark as failed
    knowledge._load_from_content(content, upsert=False, skip_if_exists=False)

    assert content.status == ContentStatus.FAILED
    assert "maximum context length" in content.status_message.lower()


def test_load_from_path_handles_token_limit_error(knowledge, tmp_path):
    """Test that _load_from_path handles token limit errors appropriately."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    knowledge._insert_contents_db = MagicMock()
    knowledge._update_content = MagicMock()

    content = Content(
        path=str(test_file),
        reader=FailingReader("This model's maximum context length is 8192 tokens"),
    )
    content.content_hash = "test_hash"
    content.id = "test_id"

    # Should not raise
    knowledge._load_from_path(content, upsert=False, skip_if_exists=False)

    assert content.status == ContentStatus.FAILED
    assert "token" in content.status_message.lower()


# --- Verify exceptions don't propagate to callers ---


def test_load_from_path_does_not_propagate_exceptions(knowledge, tmp_path):
    """Test that exceptions in _load_from_path don't propagate up."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    knowledge._insert_contents_db = MagicMock()
    knowledge._update_content = MagicMock()

    content = Content(path=str(test_file), reader=FailingReader("Unexpected error"))
    content.content_hash = "test_hash"
    content.id = "test_id"

    # This should not raise any exception
    try:
        knowledge._load_from_path(content, upsert=False, skip_if_exists=False)
    except Exception as e:
        pytest.fail(f"_load_from_path raised an exception: {e}")

    assert content.status == ContentStatus.FAILED


@pytest.mark.asyncio
async def test_aload_from_content_does_not_propagate_exceptions(knowledge):
    """Test that exceptions in _aload_from_content don't propagate up."""
    knowledge._ainsert_contents_db = AsyncMock()
    knowledge._aupdate_content = AsyncMock()

    content = Content(
        name="test",
        file_data="some text",
        reader=FailingReader("Database connection failed"),
    )
    content.content_hash = "test_hash"
    content.id = "test_id"

    # This should not raise any exception
    try:
        await knowledge._aload_from_content(content, upsert=False, skip_if_exists=False)
    except Exception as e:
        pytest.fail(f"_aload_from_content raised an exception: {e}")

    assert content.status == ContentStatus.FAILED


# --- Test error message is captured in status_message ---


def test_error_message_captured_in_status_message(knowledge, tmp_path):
    """Test that the actual error message is captured in status_message."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    knowledge._insert_contents_db = MagicMock()
    knowledge._update_content = MagicMock()

    specific_error = "Very specific error message 12345"
    content = Content(path=str(test_file), reader=FailingReader(specific_error))
    content.content_hash = "test_hash"
    content.id = "test_id"

    knowledge._load_from_path(content, upsert=False, skip_if_exists=False)

    assert content.status == ContentStatus.FAILED
    assert specific_error in content.status_message
