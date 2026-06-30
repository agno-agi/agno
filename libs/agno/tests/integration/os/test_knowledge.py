"""Integration tests for knowledge router endpoints."""

import json
from io import BytesIO
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agno.db.schemas.knowledge import KnowledgeRow
from agno.knowledge.content import Content, FileData
from agno.knowledge.knowledge import ContentStatus, Knowledge
from agno.os.routers.knowledge.knowledge import attach_routes


@pytest.fixture
def mock_knowledge():
    """Create a real Knowledge instance with mocked dependencies and methods."""
    from unittest.mock import Mock

    # Create real Knowledge instance
    knowledge = Knowledge(name="test_knowledge")

    # Mock external dependencies
    knowledge.vector_db = Mock()
    knowledge.vector_db.id = "test_vector_db_id"  # Add ID for VectorDbSchema validation
    knowledge.contents_db = Mock()
    knowledge.readers = {}

    # Configure vector_db mock to prevent actual operations
    knowledge.vector_db.content_hash_exists.return_value = False
    knowledge.vector_db.async_insert = Mock()
    knowledge.vector_db.async_upsert = Mock()
    knowledge.vector_db.upsert_available.return_value = True

    # Configure contents_db mock
    knowledge.contents_db.upsert_knowledge_content = Mock()

    # Mock specific Knowledge methods that tests expect to interact with
    knowledge.patch_content = Mock()
    knowledge.apatch_content = AsyncMock()
    knowledge.get_content = Mock()
    knowledge.get_content_by_id = Mock()
    knowledge.remove_content_by_id = Mock()
    knowledge.aremove_content_by_id = AsyncMock()
    knowledge.remove_all_content = Mock()
    knowledge.aremove_all_content = AsyncMock()  # Router calls async version
    knowledge.get_content_status = Mock()
    knowledge.aget_content_status = AsyncMock()
    knowledge.get_readers = Mock()
    knowledge.get_valid_filters = Mock()
    knowledge.aget_valid_filters = AsyncMock()
    knowledge._load_content = Mock()
    knowledge.search = Mock()  # Mock the search method for search endpoint tests
    knowledge.asearch = AsyncMock()  # Router calls async version

    return knowledge


@pytest.fixture
def mock_content():
    """Create a mock Content instance."""
    file_data = FileData(content=b"test content", type="text/plain")
    return Content(
        id=str(uuid4()),
        name="test_content",
        description="Test content description",
        file_data=file_data,
        size=len(b"test content"),
        status=ContentStatus.COMPLETED,
        created_at=1234567890,
        updated_at=1234567890,
    )


@pytest.fixture
def mock_content_row():
    return KnowledgeRow(
        id=str(uuid4()),
        name="test_content",
        description="Test content description",
        type="text/plain",
        size=len(b"test content"),
        status=ContentStatus.COMPLETED,
        created_at=1234567890,
        updated_at=1234567890,
    )


@pytest.fixture
def test_app(mock_knowledge):
    """Create a FastAPI test app with knowledge routes."""
    app = FastAPI()
    router = attach_routes(APIRouter(), [mock_knowledge])
    app.include_router(router)
    return TestClient(app)


def test_upload_content_success(test_app, mock_knowledge, mock_content):
    """Test successful content upload."""
    # Mock the background task processing
    with patch("agno.os.routers.knowledge.knowledge.process_content") as mock_process:  # Fixed import path
        # Create test file
        test_file_content = b"test file content"
        test_file = BytesIO(test_file_content)

        response = test_app.post(
            "/knowledge/content",
            files={"file": ("test.txt", test_file, "text/plain")},
            data={
                "name": "Test Content",
                "description": "Test description",
                "metadata": '{"key": "value"}',
                "reader_id": "test_reader",
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert "id" in data
        assert data["status"] == "processing"

        # Verify background task was added
        mock_process.assert_called_once()


def test_upload_content_with_url(test_app, mock_knowledge):
    """Test content upload with URL."""
    with patch("agno.os.routers.knowledge.knowledge.process_content"):
        response = test_app.post(
            "/knowledge/content",
            data={
                "name": "URL Content",
                "description": "Content from URL",
                "url": "https://example.com",
                "metadata": '{"source": "web"}',
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert "id" in data
        assert data["status"] == "processing"


def test_upload_content_invalid_json(test_app):
    """Test content upload with invalid JSON metadata."""
    with patch("agno.os.routers.knowledge.knowledge.process_content"):
        response = test_app.post(
            "/knowledge/content",
            data={
                "name": "Test Content",
                "description": "Test description",
                "metadata": "invalid json",
                "url": "invalid json",
            },
        )

        # Should still succeed as the code handles invalid JSON gracefully
        assert response.status_code == 202
        data = response.json()
        assert "id" in data


def test_edit_content_success(test_app, mock_knowledge):
    """Test successful content editing."""
    content_id = str(uuid4())

    # Mock the return value of patch_content
    mock_content_dict = {
        "id": content_id,
        "name": "Updated Content",
        "description": "Updated description",
        "file_type": "text/plain",
        "size": 100,
        "metadata": {"updated": "true"},
        "status": "completed",
        "status_message": "Successfully updated",
        "created_at": 1234567890,
        "updated_at": 1234567900,
    }
    mock_knowledge.patch_content.return_value = mock_content_dict

    response = test_app.patch(
        f"/knowledge/content/{content_id}",
        data={"name": "Updated Content", "description": "Updated description", "metadata": '{"updated": "true"}'},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == content_id
    assert data["name"] == "Updated Content"
    assert data["description"] == "Updated description"
    assert data["status"] == "completed"

    # Verify knowledge.patch_content was called
    mock_knowledge.patch_content.assert_called_once()


def test_edit_content_with_invalid_reader(test_app, mock_knowledge):
    """Test content editing with invalid reader_id."""
    content_id = str(uuid4())
    mock_knowledge.readers = {"valid_reader": Mock()}

    response = test_app.patch(
        f"/knowledge/content/{content_id}", data={"name": "Updated Content", "reader_id": "invalid_reader"}
    )

    assert response.status_code == 400
    assert "Invalid reader_id" in response.json()["detail"]


def test_get_content_list(test_app, mock_knowledge, mock_content_row):
    """Test getting content list with pagination."""
    # Mock the knowledge.get_content method
    mock_knowledge.contents_db.get_knowledge_contents.return_value = ([mock_content_row], 1)

    response = test_app.get("/knowledge/content?limit=10&page=1&sort_by=created_at&sort_order=desc")

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "meta" in data
    assert len(data["data"]) == 1
    assert data["meta"]["total_count"] == 1
    assert data["meta"]["page"] == 1
    assert data["meta"]["limit"] == 10


def test_get_content_by_id(test_app, mock_knowledge, mock_content_row):
    """Test getting content by ID."""
    mock_knowledge.contents_db.get_knowledge_content.return_value = mock_content_row

    response = test_app.get(f"/knowledge/content/{mock_content_row.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == mock_content_row.id
    assert data["name"] == mock_content_row.name
    assert data["description"] == mock_content_row.description
    assert data["status"] == mock_content_row.status


def test_get_content_by_id_not_found(test_app, mock_knowledge):
    """Test getting content by ID when not found."""
    content_id = str(uuid4())
    mock_knowledge.contents_db.get_knowledge_content.return_value = None

    # Mock the Content constructor to handle None case
    with patch("agno.knowledge.content.Content") as mock_content_class:
        mock_content_instance = Mock()
        mock_content_instance.name = "test"
        mock_content_class.return_value = mock_content_instance

        response = test_app.get(f"/knowledge/content/{content_id}")

        # The response depends on how the Knowledge class handles None returns
        assert response.status_code in [200, 404]


def test_delete_content_by_id(test_app, mock_knowledge, mock_content_row):
    """Test deleting content by ID."""
    mock_knowledge.contents_db.get_knowledge_content.return_value = mock_content_row

    response = test_app.delete(f"/knowledge/content/{mock_content_row.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == mock_content_row.id

    # Verify knowledge.remove_content_by_id was called
    mock_knowledge.aremove_content_by_id.assert_called_once_with(content_id=mock_content_row.id)


def test_delete_all_content(test_app, mock_knowledge):
    """Test deleting all content."""
    response = test_app.delete("/knowledge/content")

    assert response.status_code == 200
    assert response.text == '"success"'

    # Verify knowledge.aremove_all_content was called (router uses async version)
    mock_knowledge.aremove_all_content.assert_called_once()


def test_get_content_status(test_app, mock_knowledge):
    """Test getting content status."""
    content_id = str(uuid4())
    # Mock the method to return a tuple (status, status_message)
    mock_knowledge.aget_content_status.return_value = (ContentStatus.FAILED, "Could not read content")

    response = test_app.get(f"/knowledge/content/{content_id}/status")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == ContentStatus.FAILED
    assert data["status_message"] == "Could not read content"


def test_get_config(test_app, mock_knowledge, mock_content_row):
    """Test getting configuration."""
    # Mock the get_readers method to return a proper dictionary
    mock_reader = Mock()
    mock_reader.name = "Text Reader"
    mock_reader.description = "Test reader description"

    # Mock get_readers to return a dictionary
    mock_knowledge.get_readers.return_value = {"text_reader": mock_reader}

    # Mock get_filters to return a list
    mock_knowledge.aget_valid_filters.return_value = ["filter_tag_1", "filter_tag2"]

    mock_knowledge.contents_db.get_knowledge_contents.return_value = ([mock_content_row], 1)

    # Set vector_db to None so the config endpoint doesn't try to process it
    mock_knowledge.vector_db = None

    response = test_app.get("/knowledge/config")

    assert response.status_code == 200
    data = response.json()
    assert "readers" in data
    assert "filters" in data

    latest_reader = next(reversed(data["readers"]))
    assert data["readers"][latest_reader]["id"] == "text_reader"
    assert data["readers"][latest_reader]["name"] == "Text Reader"
    assert data["readers"][latest_reader]["description"] == "Test reader description"
    assert data["filters"] == ["filter_tag_1", "filter_tag2"]


def test_get_config_with_vector_db(test_app, mock_knowledge):
    """Test getting configuration with vector database that has search types."""
    # Mock the get_readers method to return a proper dictionary
    mock_reader = Mock()
    mock_reader.name = "Text Reader"
    mock_reader.description = "Test reader description"
    mock_knowledge.get_readers.return_value = {"text_reader": mock_reader}

    # Mock get_filters to return a list
    mock_knowledge.aget_valid_filters.return_value = ["filter_tag_1", "filter_tag2"]

    # Configure the existing vector_db mock (from fixture) with the properties we need
    mock_knowledge.vector_db.name = "Test Vector DB"
    mock_knowledge.vector_db.description = "Test vector database for search"
    mock_knowledge.vector_db.get_supported_search_types.return_value = ["vector", "keyword", "hybrid"]
    mock_knowledge.vector_db.__class__.__name__ = "MockVectorDb"

    response = test_app.get("/knowledge/config")

    assert response.status_code == 200
    data = response.json()

    # Verify basic structure
    assert "readers" in data
    assert "filters" in data
    assert "vector_dbs" in data

    # Verify vector database information
    assert len(data["vector_dbs"]) == 1
    vector_db_info = data["vector_dbs"][0]

    assert "id" in vector_db_info
    assert vector_db_info["name"] == "Test Vector DB"
    assert vector_db_info["description"] == "Test vector database for search"
    assert vector_db_info["search_types"] == ["vector", "keyword", "hybrid"]

    # Verify other expected fields
    assert data["filters"] == ["filter_tag_1", "filter_tag2"]


def test_get_config_with_vector_db_no_name(test_app, mock_knowledge):
    """Test getting configuration with vector database that has no name (returns None)."""
    # Mock the get_readers and filters
    mock_knowledge.get_readers.return_value = {}
    mock_knowledge.get_valid_filters.return_value = []

    # Configure the existing vector_db mock (from fixture) without a name
    mock_knowledge.vector_db.name = None  # No name provided
    mock_knowledge.vector_db.description = "Vector DB without name"
    mock_knowledge.vector_db.get_supported_search_types.return_value = ["vector"]
    mock_knowledge.vector_db.__class__.__name__ = "PgVector"

    response = test_app.get("/knowledge/config")

    assert response.status_code == 200
    data = response.json()

    # Verify vector database name is None when not set
    assert len(data["vector_dbs"]) == 1
    vector_db_info = data["vector_dbs"][0]

    assert vector_db_info["name"] is None  # Should be None as no fallback is implemented
    assert vector_db_info["description"] == "Vector DB without name"
    assert vector_db_info["search_types"] == ["vector"]


def test_search_knowledge_basic(test_app, mock_knowledge):
    """Test basic search without search_type specified."""
    from agno.knowledge.document import Document

    # Mock search results
    mock_documents = [
        Document(
            id="doc_1",
            content="Jordan Mitchell is a software engineer with Python skills",
            name="cv_1",
            meta_data={"page": 1, "chunk": 1},
            usage={"total_tokens": 12},
        ),
        Document(
            id="doc_2",
            content="Experience with React and JavaScript frameworks",
            name="cv_1",
            meta_data={"page": 1, "chunk": 2},
            usage={"total_tokens": 8},
        ),
    ]

    mock_knowledge.asearch.return_value = mock_documents

    response = test_app.post("/knowledge/search", json={"query": "Jordan Mitchell skills"})

    assert response.status_code == 200
    data = response.json()

    # Verify response structure - now using paginated format
    assert "data" in data
    assert "meta" in data

    # Verify content
    assert data["meta"]["total_count"] == 2
    assert len(data["data"]) == 2

    # Verify document structure
    doc = data["data"][0]
    assert doc["id"] == "doc_1"
    assert doc["content"] == "Jordan Mitchell is a software engineer with Python skills"
    assert doc["name"] == "cv_1"
    assert doc["meta_data"] == {"page": 1, "chunk": 1}
    assert doc["usage"] == {"total_tokens": 12}

    # Verify knowledge.asearch was called correctly
    mock_knowledge.asearch.assert_called_once_with(
        query="Jordan Mitchell skills", max_results=None, filters=None, search_type=None
    )


def test_search_knowledge_with_search_type(test_app, mock_knowledge):
    """Test search with specific search_type."""
    from agno.knowledge.document import Document

    mock_documents = [
        Document(id="doc_1", content="Vector search result", name="test_doc", meta_data={}, usage={"total_tokens": 5})
    ]

    mock_knowledge.asearch.return_value = mock_documents

    response = test_app.post("/knowledge/search", json={"query": "test query", "search_type": "vector"})

    assert response.status_code == 200
    data = response.json()

    assert data["meta"]["total_count"] == 1
    assert len(data["data"]) == 1

    # Verify knowledge.asearch was called with search_type
    mock_knowledge.asearch.assert_called_once_with(
        query="test query", max_results=None, filters=None, search_type="vector"
    )


def test_search_knowledge_with_db_id(test_app, mock_knowledge):
    """Test search with specific database ID."""
    from agno.knowledge.document import Document

    # Configure mock_knowledge.contents_db to have the expected ID
    mock_knowledge.contents_db.id = "test_db"

    mock_documents = [
        Document(id="doc_1", content="Database specific result", name="db_doc", meta_data={}, usage={"total_tokens": 4})
    ]

    mock_knowledge.asearch.return_value = mock_documents

    response = test_app.post("/knowledge/search", json={"query": "test", "db_id": "test_db"})

    assert response.status_code == 200
    data = response.json()

    assert data["meta"]["total_count"] == 1

    # Note: db_id affects which knowledge instance is selected, not the search call itself
    mock_knowledge.asearch.assert_called_once_with(query="test", max_results=None, filters=None, search_type=None)


def test_search_knowledge_no_results(test_app, mock_knowledge):
    """Test search that returns no results."""
    mock_knowledge.asearch.return_value = []

    response = test_app.post("/knowledge/search", json={"query": "nonexistent content"})

    assert response.status_code == 200
    data = response.json()

    assert data["meta"]["total_count"] == 0
    assert len(data["data"]) == 0


def test_search_knowledge_empty_query(test_app, mock_knowledge):
    """Test search with empty query."""
    mock_knowledge.asearch.return_value = []

    response = test_app.post("/knowledge/search", json={"query": ""})

    assert response.status_code == 200, response.text
    data = response.json()

    assert data["meta"]["total_count"] == 0
    assert len(data["data"]) == 0


def test_search_knowledge_missing_query(test_app, mock_knowledge):
    """Test search without query parameter."""
    response = test_app.post("/knowledge/search", json={})

    # Should return 422 for missing required parameter
    assert response.status_code == 422


def test_search_knowledge_with_all_parameters(test_app, mock_knowledge):
    """Test search with all parameters specified."""
    from agno.knowledge.document import Document

    # Configure mock_knowledge.contents_db to have the expected ID
    mock_knowledge.contents_db.id = "test_db"

    mock_documents = [
        Document(
            id="doc_full",
            content="Full parameter test result",
            name="full_test",
            meta_data={"test": "full"},
            usage={"total_tokens": 6},
            reranking_score=0.95,
            content_id="content_123",
            content_origin="test_origin",
            size=100,
        )
    ]

    mock_knowledge.asearch.return_value = mock_documents

    response = test_app.post(
        "/knowledge/search", json={"query": "full test", "search_type": "hybrid", "db_id": "test_db"}
    )

    assert response.status_code == 200
    data = response.json()

    assert data["meta"]["total_count"] == 1

    # Verify all document fields are properly serialized
    doc = data["data"][0]
    assert doc["id"] == "doc_full"
    assert doc["content"] == "Full parameter test result"
    assert doc["name"] == "full_test"
    assert doc["meta_data"] == {"test": "full"}
    assert doc["usage"] == {"total_tokens": 6}
    assert doc["reranking_score"] == 0.95
    assert doc["content_id"] == "content_123"
    assert doc["content_origin"] == "test_origin"
    assert doc["size"] == 100

    mock_knowledge.asearch.assert_called_once_with(
        query="full test", max_results=None, filters=None, search_type="hybrid"
    )


def test_search_knowledge_timing(test_app, mock_knowledge):
    """Test that search timing is properly recorded."""
    from agno.knowledge.document import Document

    mock_documents = [Document(id="timing_doc", content="Timing test", name="timing", meta_data={}, usage={})]

    mock_knowledge.asearch.return_value = mock_documents

    response = test_app.post("/knowledge/search", json={"query": "timing test"})

    assert response.status_code == 200
    data = response.json()

    # Verify basic response structure
    assert "data" in data
    assert "meta" in data
    assert data["meta"]["total_count"] >= 0


def test_search_knowledge_document_serialization(test_app, mock_knowledge):
    """Test that Document objects are properly serialized without numpy arrays."""
    import numpy as np

    from agno.knowledge.document import Document

    # Create a document with complex objects that shouldn't be serialized
    mock_doc = Document(
        id="serialization_test",
        content="Test serialization",
        name="serialize_test",
        meta_data={"key": "value"},
        usage={"tokens": 5},
    )

    # Add properties that should NOT be serialized (like embeddings)
    mock_doc.embedding = np.array([0.1, 0.2, 0.3])  # This should be excluded
    mock_doc.embedder = object()  # This should be excluded

    mock_knowledge.asearch.return_value = [mock_doc]

    response = test_app.post("/knowledge/search", json={"query": "serialization test"})

    assert response.status_code == 200
    data = response.json()

    doc = data["data"][0]

    # Verify included fields
    assert doc["id"] == "serialization_test"
    assert doc["content"] == "Test serialization"
    assert doc["name"] == "serialize_test"
    assert doc["meta_data"] == {"key": "value"}
    assert doc["usage"] == {"tokens": 5}

    # Verify excluded fields (should not be present)
    assert "embedding" not in doc
    assert "embedder" not in doc


async def test_process_content_success(mock_knowledge, mock_content):
    """Test successful content processing."""
    from agno.os.routers.knowledge.knowledge import process_content

    reader_id = "text_reader"

    # Set up the readers dictionary in the mock
    mock_reader = Mock()
    mock_knowledge.readers = {"text_reader": mock_reader}
    # Configure get_readers() to return the dictionary (process_content calls get_readers())
    mock_knowledge.get_readers.return_value = {"text_reader": mock_reader}

    # Mock the knowledge._aload_content method (async version)
    with patch.object(mock_knowledge, "_aload_content", new_callable=AsyncMock) as mock_add:
        # Call the function with correct parameter order: (knowledge, content, reader_id)
        await process_content(mock_knowledge, mock_content, reader_id)

        # Verify the content was added
        mock_add.assert_called_once_with(mock_content, upsert=False, skip_if_exists=True)

        # Verify that the reader was set
        assert mock_content.reader == mock_reader


async def test_process_content_with_exception(mock_knowledge, mock_content):
    """Test content processing with exception."""
    from agno.os.routers.knowledge.knowledge import process_content

    reader_id = "test_reader"

    # Mock the knowledge.process_content method to raise an exception
    with patch.object(mock_knowledge, "_load_content", side_effect=Exception("Test error")):
        # Should not raise an exception
        await process_content(mock_knowledge, mock_content, reader_id)


def test_upload_large_file(test_app):
    """Test uploading a large file."""
    with patch("agno.os.routers.knowledge.knowledge.process_content"):
        # Create a large file content
        large_content = b"x" * (10 * 1024 * 1024)  # 10MB
        test_file = BytesIO(large_content)

        response = test_app.post(
            "/knowledge/content",
            files={"file": ("large_file.txt", test_file, "text/plain")},
            data={"name": "Large File"},
        )

        assert response.status_code == 202
        data = response.json()
        assert "id" in data


def test_upload_without_file(test_app):
    """Test uploading content without a file."""
    with patch("agno.os.routers.knowledge.knowledge.process_content"):
        response = test_app.post(
            "/knowledge/content",
            data={"name": "Text Content", "description": "Content without file", "metadata": '{"type": "text"}'},
        )

        assert response.status_code == 202
        data = response.json()
        assert "id" in data


def test_upload_with_special_characters(test_app):
    """Test uploading content with special characters in metadata."""
    with patch("agno.os.routers.knowledge.knowledge.process_content"):
        special_metadata = {"special_chars": "!@#$%^&*()", "unicode": "测试内容", "quotes": '{"nested": "value"}'}

        response = test_app.post(
            "/knowledge/content", data={"name": "Special Content", "metadata": json.dumps(special_metadata)}
        )

        assert response.status_code == 202
        data = response.json()
        assert "id" in data
