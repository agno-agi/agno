"""Tests for metadata propagation when using path in Knowledge.

This tests the fix for issue #6077 where metadata was not propagated to documents
when using path in add_content_async/ainsert.
"""

import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from agno.knowledge.content import Content
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.base import VectorDb


class MockVectorDb(VectorDb):
    """Mock VectorDb that tracks inserted documents and their metadata."""

    def __init__(self):
        self.inserted_documents: List[Document] = []
        self.upserted_documents: List[Document] = []

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
        self.inserted_documents.extend(documents)

    async def async_insert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        self.inserted_documents.extend(documents)

    def upsert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        self.upserted_documents.extend(documents)

    async def async_upsert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        self.upserted_documents.extend(documents)

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
        return True

    def get_supported_search_types(self) -> List[str]:
        return ["vector"]


class MockReader:
    """Mock reader that returns test documents."""

    def read(self, path, name=None, password=None) -> List[Document]:
        return [Document(name=name or str(path), content="Test document content")]

    async def aread(self, path, name=None, password=None) -> List[Document]:
        return [Document(name=name or str(path), content="Test document content")]


@pytest.fixture
def temp_text_file():
    """Create a temporary text file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Test document content for metadata propagation testing.")
        temp_path = f.name
    yield temp_path
    # Cleanup
    Path(temp_path).unlink(missing_ok=True)


@pytest.fixture
def mock_vector_db():
    """Create a mock vector database."""
    return MockVectorDb()


def test_prepare_documents_for_insert_with_metadata():
    """Test that _prepare_documents_for_insert correctly merges metadata."""
    mock_db = MockVectorDb()
    knowledge = Knowledge(vector_db=mock_db)

    # Create test documents
    documents = [
        Document(name="doc1", content="Content 1", meta_data={"existing": "value1"}),
        Document(name="doc2", content="Content 2", meta_data={}),
        Document(name="doc3", content="Content 3"),  # No meta_data
    ]

    metadata = {"document_id": "123", "knowledge_base_id": "456", "filename": "test.txt"}

    # Call _prepare_documents_for_insert with metadata
    result = knowledge._prepare_documents_for_insert(documents, "content-id-1", metadata=metadata)

    # Verify metadata was merged (linked_to is always added, empty string for unnamed knowledge)
    assert result[0].meta_data == {
        "existing": "value1",
        "document_id": "123",
        "knowledge_base_id": "456",
        "filename": "test.txt",
        "linked_to": "",
    }
    assert result[1].meta_data == {
        "document_id": "123",
        "knowledge_base_id": "456",
        "filename": "test.txt",
        "linked_to": "",
    }
    assert result[2].meta_data == {
        "document_id": "123",
        "knowledge_base_id": "456",
        "filename": "test.txt",
        "linked_to": "",
    }

    # Verify content_id was set
    for doc in result:
        assert doc.content_id == "content-id-1"


def test_prepare_documents_for_insert_without_metadata():
    """Test that _prepare_documents_for_insert works correctly without metadata."""
    mock_db = MockVectorDb()
    knowledge = Knowledge(vector_db=mock_db)

    # Create test documents
    documents = [
        Document(name="doc1", content="Content 1", meta_data={"existing": "value1"}),
        Document(name="doc2", content="Content 2", meta_data={}),
    ]

    # Call _prepare_documents_for_insert without metadata
    result = knowledge._prepare_documents_for_insert(documents, "content-id-1")

    # Verify existing metadata is preserved (linked_to is always added)
    assert result[0].meta_data == {"existing": "value1", "linked_to": ""}
    assert result[1].meta_data == {"linked_to": ""}

    # Verify content_id was set
    for doc in result:
        assert doc.content_id == "content-id-1"


def test_prepare_documents_for_insert_with_empty_metadata():
    """Test that _prepare_documents_for_insert works correctly with empty metadata dict."""
    mock_db = MockVectorDb()
    knowledge = Knowledge(vector_db=mock_db)

    # Create test documents
    documents = [
        Document(name="doc1", content="Content 1", meta_data={"existing": "value1"}),
    ]

    # Call _prepare_documents_for_insert with empty metadata
    result = knowledge._prepare_documents_for_insert(documents, "content-id-1", metadata={})

    # Verify existing metadata is preserved (linked_to is always added)
    assert result[0].meta_data == {"existing": "value1", "linked_to": ""}


@pytest.mark.asyncio
async def test_aload_from_path_propagates_metadata(temp_text_file, mock_vector_db):
    """Test that _aload_from_path propagates metadata to documents."""
    knowledge = Knowledge(vector_db=mock_vector_db)

    # Create content with metadata
    content = Content(
        path=temp_text_file,
        name="Test Document",
        metadata={"document_id": "123", "knowledge_base_id": "456", "filename": "test.txt"},
    )
    content.content_hash = knowledge._build_content_hash(content)

    with patch.object(knowledge, "_aread", return_value=[Document(name="test", content="Test content")]):
        await knowledge._aload_from_path(content, upsert=False, skip_if_exists=False)

    # Verify documents were inserted with metadata
    assert len(mock_vector_db.inserted_documents) == 1
    doc = mock_vector_db.inserted_documents[0]
    assert doc.meta_data.get("document_id") == "123"
    assert doc.meta_data.get("knowledge_base_id") == "456"
    assert doc.meta_data.get("filename") == "test.txt"


@pytest.mark.asyncio
async def test_aload_from_path_upsert_propagates_metadata(temp_text_file, mock_vector_db):
    """Test that _aload_from_path propagates metadata to documents when using upsert."""
    knowledge = Knowledge(vector_db=mock_vector_db)

    # Create content with metadata
    content = Content(
        path=temp_text_file,
        name="Test Document",
        metadata={"source": "test", "category": "documentation"},
    )
    content.content_hash = knowledge._build_content_hash(content)

    with patch.object(knowledge, "_aread", return_value=[Document(name="test", content="Test content")]):
        await knowledge._aload_from_path(content, upsert=True, skip_if_exists=False)

    # Verify documents were upserted with metadata
    assert len(mock_vector_db.upserted_documents) == 1
    doc = mock_vector_db.upserted_documents[0]
    assert doc.meta_data.get("source") == "test"
    assert doc.meta_data.get("category") == "documentation"


def test_load_from_path_propagates_metadata(temp_text_file, mock_vector_db):
    """Test that _load_from_path propagates metadata to documents."""
    knowledge = Knowledge(vector_db=mock_vector_db)

    # Create content with metadata
    content = Content(
        path=temp_text_file,
        name="Test Document",
        metadata={"document_id": "789", "author": "test_author"},
    )
    content.content_hash = knowledge._build_content_hash(content)

    with patch.object(knowledge, "_read", return_value=[Document(name="test", content="Test content")]):
        knowledge._load_from_path(content, upsert=False, skip_if_exists=False)

    # Verify documents were inserted with metadata
    assert len(mock_vector_db.inserted_documents) == 1
    doc = mock_vector_db.inserted_documents[0]
    assert doc.meta_data.get("document_id") == "789"
    assert doc.meta_data.get("author") == "test_author"


def test_load_from_path_upsert_propagates_metadata(temp_text_file, mock_vector_db):
    """Test that _load_from_path propagates metadata to documents when using upsert."""
    knowledge = Knowledge(vector_db=mock_vector_db)

    # Create content with metadata
    content = Content(
        path=temp_text_file,
        name="Test Document",
        metadata={"version": "1.0", "language": "en"},
    )
    content.content_hash = knowledge._build_content_hash(content)

    with patch.object(knowledge, "_read", return_value=[Document(name="test", content="Test content")]):
        knowledge._load_from_path(content, upsert=True, skip_if_exists=False)

    # Verify documents were upserted with metadata
    assert len(mock_vector_db.upserted_documents) == 1
    doc = mock_vector_db.upserted_documents[0]
    assert doc.meta_data.get("version") == "1.0"
    assert doc.meta_data.get("language") == "en"


def test_load_from_path_without_metadata(temp_text_file, mock_vector_db):
    """Test that _load_from_path works correctly without metadata."""
    knowledge = Knowledge(vector_db=mock_vector_db)

    # Create content without metadata
    content = Content(
        path=temp_text_file,
        name="Test Document",
    )
    content.content_hash = knowledge._build_content_hash(content)

    with patch.object(
        knowledge, "_read", return_value=[Document(name="test", content="Test content", meta_data={"original": "data"})]
    ):
        knowledge._load_from_path(content, upsert=False, skip_if_exists=False)

    # Verify documents were inserted with original metadata preserved (linked_to is always added)
    assert len(mock_vector_db.inserted_documents) == 1
    doc = mock_vector_db.inserted_documents[0]
    assert doc.meta_data == {"original": "data", "linked_to": ""}


def test_metadata_merges_with_existing_document_metadata(temp_text_file, mock_vector_db):
    """Test that content metadata merges with existing document metadata."""
    knowledge = Knowledge(vector_db=mock_vector_db)

    # Create content with metadata
    content = Content(
        path=temp_text_file,
        name="Test Document",
        metadata={"new_field": "new_value", "shared_field": "content_value"},
    )
    content.content_hash = knowledge._build_content_hash(content)

    # Mock reader returns document with existing metadata
    with patch.object(
        knowledge,
        "_read",
        return_value=[
            Document(
                name="test",
                content="Test content",
                meta_data={"existing_field": "existing_value", "shared_field": "doc_value"},
            )
        ],
    ):
        knowledge._load_from_path(content, upsert=False, skip_if_exists=False)

    # Verify metadata was merged (content metadata should override document metadata for shared keys)
    assert len(mock_vector_db.inserted_documents) == 1
    doc = mock_vector_db.inserted_documents[0]
    assert doc.meta_data.get("existing_field") == "existing_value"
    assert doc.meta_data.get("new_field") == "new_value"
    assert doc.meta_data.get("shared_field") == "content_value"  # Content metadata overrides
