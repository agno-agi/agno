"""
Unit tests for Gemini File Search functionality.

To run these tests:
    pytest libs/agno/tests/unit/models/google/test_gemini_file_search.py -v
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from agno.models.google import Gemini
from agno.models.response import ModelResponse


@pytest.fixture
def mock_gemini_client():
    """Create a mock Gemini client."""
    client = MagicMock()
    client.file_search_stores = MagicMock()
    client.file_search_stores.documents = MagicMock()
    client.operations = MagicMock()
    client.aio = MagicMock()
    return client


@pytest.fixture
def gemini_model(mock_gemini_client):
    """Create a Gemini model instance with mocked client."""
    model = Gemini(id="gemini-2.5-flash")
    model.client = mock_gemini_client
    return model


class TestFileSearchStoreManagement:
    """Test File Search store CRUD operations."""

    def test_create_file_search_store(self, gemini_model, mock_gemini_client):
        """Test creating a File Search store."""
        # Setup mock
        mock_store = MagicMock()
        mock_store.name = "fileSearchStores/test-store-123"
        mock_gemini_client.file_search_stores.create.return_value = mock_store

        # Execute
        store = gemini_model.create_file_search_store(display_name="Test Store")

        # Verify
        assert store.name == "fileSearchStores/test-store-123"
        mock_gemini_client.file_search_stores.create.assert_called_once()

    def test_list_file_search_stores(self, gemini_model, mock_gemini_client):
        """Test listing File Search stores."""
        # Setup mock
        mock_stores = [MagicMock(name=f"fileSearchStores/store-{i}") for i in range(3)]
        mock_gemini_client.file_search_stores.list.return_value = iter(mock_stores)

        # Execute
        stores = gemini_model.list_file_search_stores()

        # Verify
        assert len(stores) == 3
        assert all(store.name.startswith("fileSearchStores/") for store in stores)

    def test_get_file_search_store(self, gemini_model, mock_gemini_client):
        """Test getting a specific File Search store."""
        # Setup mock
        mock_store = MagicMock()
        mock_store.name = "fileSearchStores/test-store-123"
        mock_store.display_name = "Test Store"
        mock_gemini_client.file_search_stores.get.return_value = mock_store

        # Execute
        store = gemini_model.get_file_search_store("fileSearchStores/test-store-123")

        # Verify
        assert store.name == "fileSearchStores/test-store-123"
        assert store.display_name == "Test Store"

    def test_delete_file_search_store(self, gemini_model, mock_gemini_client):
        """Test deleting a File Search store."""
        # Execute
        gemini_model.delete_file_search_store("fileSearchStores/test-store-123")

        # Verify
        mock_gemini_client.file_search_stores.delete.assert_called_once_with(
            name="fileSearchStores/test-store-123", config={"force": True}
        )


class TestFileUploadAndImport:
    """Test file upload and import operations."""

    def test_upload_to_file_search_store(self, gemini_model, mock_gemini_client, tmp_path):
        """Test uploading a file to File Search store."""
        # Create a temporary file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content")

        # Setup mock
        mock_operation = MagicMock()
        mock_operation.done = False
        mock_gemini_client.file_search_stores.upload_to_file_search_store.return_value = mock_operation

        # Execute
        operation = gemini_model.upload_to_file_search_store(
            file_path=test_file,
            store_name="fileSearchStores/test-store-123",
            display_name="Test Document",
        )

        # Verify
        assert operation == mock_operation
        mock_gemini_client.file_search_stores.upload_to_file_search_store.assert_called_once()

    def test_upload_with_chunking_config(self, gemini_model, mock_gemini_client, tmp_path):
        """Test uploading with custom chunking configuration."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content")

        mock_operation = MagicMock()
        mock_gemini_client.file_search_stores.upload_to_file_search_store.return_value = mock_operation

        chunking_config = {"white_space_config": {"max_tokens_per_chunk": 200, "max_overlap_tokens": 20}}

        operation = gemini_model.upload_to_file_search_store(
            file_path=test_file,
            store_name="fileSearchStores/test-store-123",
            chunking_config=chunking_config,
        )

        # Verify chunking_config was included in the call
        call_args = mock_gemini_client.file_search_stores.upload_to_file_search_store.call_args
        assert "config" in call_args.kwargs
        assert call_args.kwargs["config"]["chunking_config"] == chunking_config

    def test_upload_with_metadata(self, gemini_model, mock_gemini_client, tmp_path):
        """Test uploading with custom metadata."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content")

        mock_operation = MagicMock()
        mock_gemini_client.file_search_stores.upload_to_file_search_store.return_value = mock_operation

        metadata = [{"key": "author", "string_value": "Test Author"}, {"key": "year", "numeric_value": 2024}]

        operation = gemini_model.upload_to_file_search_store(
            file_path=test_file, store_name="fileSearchStores/test-store-123", custom_metadata=metadata
        )

        # Verify metadata was included
        call_args = mock_gemini_client.file_search_stores.upload_to_file_search_store.call_args
        assert "config" in call_args.kwargs
        assert call_args.kwargs["config"]["custom_metadata"] == metadata

    def test_import_file_to_store(self, gemini_model, mock_gemini_client):
        """Test importing an existing file to store."""
        mock_operation = MagicMock()
        mock_gemini_client.file_search_stores.import_file.return_value = mock_operation

        operation = gemini_model.import_file_to_store(
            file_name="files/test-file", store_name="fileSearchStores/test-store-123"
        )

        assert operation == mock_operation
        mock_gemini_client.file_search_stores.import_file.assert_called_once()


class TestDocumentManagement:
    """Test document management operations."""

    def test_list_documents(self, gemini_model, mock_gemini_client):
        """Test listing documents in a store."""
        mock_docs = [MagicMock(name=f"doc-{i}", display_name=f"Document {i}") for i in range(5)]
        mock_gemini_client.file_search_stores.documents.list.return_value = iter(mock_docs)

        documents = gemini_model.list_documents("fileSearchStores/test-store-123")

        assert len(documents) == 5
        assert all(doc.display_name.startswith("Document") for doc in documents)

    def test_get_document(self, gemini_model, mock_gemini_client):
        """Test getting a specific document."""
        mock_doc = MagicMock()
        mock_doc.name = "fileSearchStores/test-store-123/documents/doc-456"
        mock_doc.display_name = "Test Document"
        mock_gemini_client.file_search_stores.documents.get.return_value = mock_doc

        doc = gemini_model.get_document("fileSearchStores/test-store-123/documents/doc-456")

        assert doc.name == "fileSearchStores/test-store-123/documents/doc-456"
        assert doc.display_name == "Test Document"

    def test_delete_document(self, gemini_model, mock_gemini_client):
        """Test deleting a document."""
        gemini_model.delete_document("fileSearchStores/test-store-123/documents/doc-456")

        mock_gemini_client.file_search_stores.documents.delete.assert_called_once_with(
            name="fileSearchStores/test-store-123/documents/doc-456"
        )

    def test_update_document_metadata(self, gemini_model, mock_gemini_client):
        """Test updating document metadata."""
        mock_updated_doc = MagicMock()
        mock_gemini_client.file_search_stores.documents.update.return_value = mock_updated_doc

        metadata = [{"key": "reviewed", "string_value": "true"}]
        updated_doc = gemini_model.update_document_metadata(
            "fileSearchStores/test-store-123/documents/doc-456", metadata
        )

        assert updated_doc == mock_updated_doc
        call_args = mock_gemini_client.file_search_stores.documents.update.call_args
        assert call_args.kwargs["config"]["custom_metadata"] == metadata


class TestCitationExtraction:
    """Test citation extraction functionality."""

    def test_extract_file_search_citations(self, gemini_model):
        """Test extracting citations from a response."""
        # Create mock response with citations
        response = ModelResponse()
        response.content = "Test response"

        # Create mock citations structure
        from agno.models.message import Citations

        response.citations = Citations()
        response.citations.raw = {
            "grounding_metadata": {
                "grounding_chunks": [
                    {
                        "retrieved_context": {
                            "title": "Technical Manual",
                            "uri": "fileSearchStores/store-123/documents/doc-1",
                            "text": "Sample text from document",
                        }
                    },
                    {
                        "retrieved_context": {
                            "title": "User Guide",
                            "uri": "fileSearchStores/store-123/documents/doc-2",
                            "text": "Another sample text",
                        }
                    },
                ]
            }
        }

        # Extract citations
        citations = gemini_model.extract_file_search_citations(response)

        # Verify
        assert len(citations["sources"]) == 2
        assert "Technical Manual" in citations["sources"]
        assert "User Guide" in citations["sources"]
        assert len(citations["grounding_chunks"]) == 2
        assert citations["grounding_chunks"][0]["type"] == "file_search"

    def test_extract_citations_no_response(self, gemini_model):
        """Test extracting citations when no response is provided."""
        citations = gemini_model.extract_file_search_citations(None)

        assert citations["sources"] == []
        assert citations["grounding_chunks"] == []
        assert citations["raw_metadata"] is None

    def test_format_citations(self, gemini_model):
        """Test formatting citations."""
        citations_data = {
            "sources": ["Document 1", "Document 2"],
            "grounding_chunks": [
                {"title": "Document 1", "uri": "doc-1", "text": "Sample text", "type": "file_search"},
                {"title": "Document 2", "uri": "doc-2", "text": "Another text", "type": "file_search"},
            ],
        }

        formatted = gemini_model.format_citations(citations_data, include_text=True)

        assert "Citations:" in formatted
        assert "Document 1" in formatted
        assert "Document 2" in formatted
        assert "Sample text" in formatted

    def test_format_citations_no_sources(self, gemini_model):
        """Test formatting citations with no sources."""
        citations_data = {"sources": [], "grounding_chunks": []}

        formatted = gemini_model.format_citations(citations_data)

        assert formatted == "No citations found."


class TestOperationWaiting:
    """Test operation waiting functionality."""

    def test_wait_for_operation_success(self, gemini_model, mock_gemini_client):
        """Test waiting for an operation to complete successfully."""
        mock_operation = MagicMock()
        # Simulate operation completing after first check
        mock_operation.done = True

        completed_op = gemini_model.wait_for_operation(mock_operation, poll_interval=1)

        assert completed_op.done is True

    def test_wait_for_operation_timeout(self, gemini_model, mock_gemini_client):
        """Test operation timeout."""
        mock_operation = MagicMock()
        mock_operation.done = False

        with pytest.raises(TimeoutError):
            gemini_model.wait_for_operation(mock_operation, poll_interval=1, max_wait=2)


class TestFileSearchIntegration:
    """Test File Search tool integration with generate_content."""

    def test_file_search_in_request_params(self):
        """Test that File Search is properly included in request parameters."""
        model = Gemini(
            id="gemini-2.5-flash",
            file_search_store_names=["fileSearchStores/test-store-123"],
            file_search_metadata_filter='type="technical"',
        )

        request_params = model.get_request_params()

        assert "config" in request_params
        config = request_params["config"]
        assert hasattr(config, "tools")
        assert len(config.tools) > 0

        # Check that FileSearch tool is present
        file_search_tool = next((t for t in config.tools if hasattr(t, "file_search")), None)
        assert file_search_tool is not None
        assert file_search_tool.file_search.file_search_store_names == ["fileSearchStores/test-store-123"]
        assert file_search_tool.file_search.metadata_filter == 'type="technical"'

    def test_file_search_without_metadata_filter(self):
        """Test File Search configuration without metadata filter."""
        model = Gemini(id="gemini-2.5-flash", file_search_store_names=["fileSearchStores/test-store-123"])

        request_params = model.get_request_params()
        config = request_params["config"]

        file_search_tool = next((t for t in config.tools if hasattr(t, "file_search")), None)
        assert file_search_tool is not None
        assert not hasattr(file_search_tool.file_search, "metadata_filter") or file_search_tool.file_search.metadata_filter is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
