"""Integration tests for knowledge router endpoints."""

import json
from io import BytesIO
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

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
    knowledge.get_content = Mock()
    knowledge.get_content_by_id = Mock()
    knowledge.remove_content_by_id = Mock()
    knowledge.remove_all_content = Mock()
    knowledge.get_content_status = Mock()
    knowledge.get_readers = Mock()
    knowledge.get_filters = Mock()
    knowledge._load_content = Mock()

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
def test_app(mock_knowledge):
    """Create a FastAPI test app with knowledge routes."""
    app = FastAPI()
    router = attach_routes(APIRouter(), [mock_knowledge])
    app.include_router(router)
    return TestClient(app)


class TestKnowledgeContentEndpoints:
    """Test suite for knowledge content endpoints."""

    def test_upload_content_success(self, test_app, mock_knowledge, mock_content):
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

    def test_upload_content_with_url(self, test_app, mock_knowledge):
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

    def test_upload_content_invalid_json(self, test_app):
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

    def test_edit_content_success(self, test_app, mock_knowledge):
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

    def test_edit_content_with_invalid_reader(self, test_app, mock_knowledge):
        """Test content editing with invalid reader_id."""
        content_id = str(uuid4())
        mock_knowledge.readers = {"valid_reader": Mock()}

        response = test_app.patch(
            f"/knowledge/content/{content_id}", data={"name": "Updated Content", "reader_id": "invalid_reader"}
        )

        assert response.status_code == 400
        assert "Invalid reader_id" in response.json()["detail"]

    def test_get_content_list(self, test_app, mock_knowledge, mock_content):
        """Test getting content list with pagination."""
        # Mock the knowledge.get_content method
        mock_knowledge.get_content.return_value = ([mock_content], 1)

        response = test_app.get("/knowledge/content?limit=10&page=1&sort_by=created_at&sort_order=desc")

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "meta" in data
        assert len(data["data"]) == 1
        assert data["meta"]["total_count"] == 1
        assert data["meta"]["page"] == 1
        assert data["meta"]["limit"] == 10

    def test_get_content_by_id(self, test_app, mock_knowledge, mock_content):
        """Test getting content by ID."""
        mock_knowledge.get_content_by_id.return_value = mock_content

        response = test_app.get(f"/knowledge/content/{mock_content.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == mock_content.id
        assert data["name"] == mock_content.name
        assert data["description"] == mock_content.description
        assert data["status"] == mock_content.status

    def test_get_content_by_id_not_found(self, test_app, mock_knowledge):
        """Test getting content by ID when not found."""
        content_id = str(uuid4())
        mock_knowledge.get_content_by_id.return_value = None

        # Mock the Content constructor to handle None case
        with patch("agno.knowledge.content.Content") as mock_content_class:
            mock_content_instance = Mock()
            mock_content_instance.name = "test"
            mock_content_class.return_value = mock_content_instance

            response = test_app.get(f"/knowledge/content/{content_id}")

            # The response depends on how the Knowledge class handles None returns
            assert response.status_code in [200, 404]

    def test_delete_content_by_id(self, test_app, mock_knowledge):
        """Test deleting content by ID."""
        content_id = str(uuid4())

        response = test_app.delete(f"/knowledge/content/{content_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == content_id

        # Verify knowledge.remove_content_by_id was called
        mock_knowledge.remove_content_by_id.assert_called_once_with(content_id=content_id)

    def test_delete_all_content(self, test_app, mock_knowledge):
        """Test deleting all content."""
        response = test_app.delete("/knowledge/content")

        assert response.status_code == 200
        assert response.text == '"success"'

        # Verify knowledge.remove_all_content was called
        mock_knowledge.remove_all_content.assert_called_once()

    def test_get_content_status(self, test_app, mock_knowledge):
        """Test getting content status."""
        content_id = str(uuid4())
        # Mock the method to return a tuple (status, status_message)
        mock_knowledge.get_content_status.return_value = (ContentStatus.FAILED, "Could not read content")

        response = test_app.get(f"/knowledge/content/{content_id}/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == ContentStatus.FAILED
        assert data["status_message"] == "Could not read content"

    def test_get_config(self, test_app, mock_knowledge):
        """Test getting configuration."""
        # Mock the get_readers method to return a proper dictionary
        mock_reader = Mock()
        mock_reader.name = "Text Reader"
        mock_reader.description = "Test reader description"

        # Mock get_readers to return a dictionary
        mock_knowledge.get_readers.return_value = {"text_reader": mock_reader}

        # Mock get_filters to return a list
        mock_knowledge.get_filters.return_value = ["filter_tag_1", "filter_tag2"]

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


class TestBackgroundTaskProcessing:
    """Test suite for background task processing."""

    async def test_process_content_success(self, mock_knowledge, mock_content):
        """Test successful content processing."""
        from agno.os.routers.knowledge.knowledge import process_content

        reader_id = "text_reader"

        # Set up the readers dictionary in the mock
        mock_reader = Mock()
        mock_knowledge.readers = {"text_reader": mock_reader}

        # Mock the knowledge.process_content method
        with patch.object(mock_knowledge, "_load_content") as mock_add:
            # Call the function with correct parameter order: (knowledge, content, reader_id)
            await process_content(mock_knowledge, mock_content, reader_id)

            # Verify the content was added
            mock_add.assert_called_once_with(mock_content, upsert=False, skip_if_exists=True)

            # Verify that the reader was set
            assert mock_content.reader == mock_reader

    async def test_process_content_with_exception(self, mock_knowledge, mock_content):
        """Test content processing with exception."""
        from agno.os.routers.knowledge.knowledge import process_content

        reader_id = "test_reader"

        # Mock the knowledge.process_content method to raise an exception
        with patch.object(mock_knowledge, "_load_content", side_effect=Exception("Test error")):
            # Should not raise an exception
            await process_content(mock_knowledge, mock_content, reader_id)


class TestFileUploadScenarios:
    """Test suite for file upload scenarios."""

    def test_upload_large_file(self, test_app):
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

    def test_upload_without_file(self, test_app):
        """Test uploading content without a file."""
        with patch("agno.os.routers.knowledge.knowledge.process_content"):
            response = test_app.post(
                "/knowledge/content",
                data={"name": "Text Content", "description": "Content without file", "metadata": '{"type": "text"}'},
            )

            assert response.status_code == 202
            data = response.json()
            assert "id" in data

    def test_upload_with_special_characters(self, test_app):
        """Test uploading content with special characters in metadata."""
        with patch("agno.os.routers.knowledge.knowledge.process_content"):
            special_metadata = {"special_chars": "!@#$%^&*()", "unicode": "测试内容", "quotes": '{"nested": "value"}'}

            response = test_app.post(
                "/knowledge/content", data={"name": "Special Content", "metadata": json.dumps(special_metadata)}
            )

            assert response.status_code == 202
            data = response.json()
            assert "id" in data
