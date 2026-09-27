"""Tests that metadata reaches the documents when Knowledge loads from a path."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agno.knowledge.content import Content
from agno.knowledge.document import Document


@pytest.fixture
def temp_text_file():
    """Create a temporary text file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Test document content for metadata propagation testing.")
        temp_path = f.name
    yield temp_path
    # Cleanup
    Path(temp_path).unlink(missing_ok=True)


def test_prepare_documents_for_insert_with_metadata(knowledge):
    """Test that _prepare_documents_for_insert correctly merges metadata."""

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


def test_prepare_documents_for_insert_without_metadata(knowledge):
    """Test that _prepare_documents_for_insert works correctly without metadata."""

    # Create test documents
    documents = [
        Document(name="doc1", content="Content 1", meta_data={"existing": "value1"}),
        Document(name="doc2", content="Content 2", meta_data={}),
    ]

    # Call _prepare_documents_for_insert without metadata
    result = knowledge._prepare_documents_for_insert(documents, "content-id-1")

    # Verify existing metadata is preserved (only linked_to is added); user_id is not written into meta_data
    assert result[0].meta_data == {"existing": "value1", "linked_to": ""}
    assert result[1].meta_data == {"linked_to": ""}

    # Verify content_id was set
    for doc in result:
        assert doc.content_id == "content-id-1"


def test_prepare_documents_for_insert_with_empty_metadata(knowledge):
    """Test that _prepare_documents_for_insert works correctly with empty metadata dict."""

    # Create test documents
    documents = [
        Document(name="doc1", content="Content 1", meta_data={"existing": "value1"}),
    ]

    # Call _prepare_documents_for_insert with empty metadata
    result = knowledge._prepare_documents_for_insert(documents, "content-id-1", metadata={})

    # Verify existing metadata is preserved (only linked_to is added)
    assert result[0].meta_data == {"existing": "value1", "linked_to": ""}


@pytest.mark.asyncio
async def test_aload_from_path_propagates_metadata(knowledge, vector_db, temp_text_file):
    """Test that _aload_from_path propagates metadata to documents."""

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
    assert len(vector_db.inserted_documents) == 1
    doc = vector_db.inserted_documents[0]
    assert doc.meta_data.get("document_id") == "123"
    assert doc.meta_data.get("knowledge_base_id") == "456"
    assert doc.meta_data.get("filename") == "test.txt"


@pytest.mark.asyncio
async def test_aload_from_path_upsert_propagates_metadata(knowledge, vector_db, temp_text_file):
    """Test that _aload_from_path propagates metadata to documents when using upsert."""

    # Create content with metadata
    content = Content(
        path=temp_text_file,
        name="Test Document",
        metadata={"source": "test", "category": "documentation"},
    )
    content.content_hash = knowledge._build_content_hash(content)
    vector_db.upsert_supported = True

    with patch.object(knowledge, "_aread", return_value=[Document(name="test", content="Test content")]):
        await knowledge._aload_from_path(content, upsert=True, skip_if_exists=False)

    # Verify documents were upserted with metadata
    assert len(vector_db.upserted_documents) == 1
    doc = vector_db.upserted_documents[0]
    assert doc.meta_data.get("source") == "test"
    assert doc.meta_data.get("category") == "documentation"


def test_load_from_path_propagates_metadata(knowledge, vector_db, temp_text_file):
    """Test that _load_from_path propagates metadata to documents."""

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
    assert len(vector_db.inserted_documents) == 1
    doc = vector_db.inserted_documents[0]
    assert doc.meta_data.get("document_id") == "789"
    assert doc.meta_data.get("author") == "test_author"


def test_load_from_path_upsert_propagates_metadata(knowledge, vector_db, temp_text_file):
    """Test that _load_from_path propagates metadata to documents when using upsert."""

    # Create content with metadata
    content = Content(
        path=temp_text_file,
        name="Test Document",
        metadata={"version": "1.0", "language": "en"},
    )
    content.content_hash = knowledge._build_content_hash(content)
    vector_db.upsert_supported = True

    with patch.object(knowledge, "_read", return_value=[Document(name="test", content="Test content")]):
        knowledge._load_from_path(content, upsert=True, skip_if_exists=False)

    # Verify documents were upserted with metadata
    assert len(vector_db.upserted_documents) == 1
    doc = vector_db.upserted_documents[0]
    assert doc.meta_data.get("version") == "1.0"
    assert doc.meta_data.get("language") == "en"


def test_load_from_path_without_metadata(knowledge, vector_db, temp_text_file):
    """Test that _load_from_path works correctly without metadata."""

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

    # Verify documents were inserted with original metadata preserved (only linked_to is added)
    assert len(vector_db.inserted_documents) == 1
    doc = vector_db.inserted_documents[0]
    assert doc.meta_data == {"original": "data", "linked_to": ""}


def test_metadata_merges_with_existing_document_metadata(knowledge, vector_db, temp_text_file):
    """Test that content metadata merges with existing document metadata."""

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
    assert len(vector_db.inserted_documents) == 1
    doc = vector_db.inserted_documents[0]
    assert doc.meta_data.get("existing_field") == "existing_value"
    assert doc.meta_data.get("new_field") == "new_value"
    assert doc.meta_data.get("shared_field") == "content_value"  # Content metadata overrides
