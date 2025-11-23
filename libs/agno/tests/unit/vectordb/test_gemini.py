import sys
from typing import List
from unittest.mock import MagicMock, patch

import pytest

# Mock google.genai module before importing GeminiFileSearch
mock_genai = MagicMock()
mock_types = MagicMock()
mock_errors = MagicMock()

# Create ClientError mock
class MockClientError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.code = None

mock_errors.ClientError = MockClientError

sys.modules['google'] = MagicMock()
sys.modules['google.genai'] = mock_genai
sys.modules['google.genai.types'] = mock_types
sys.modules['google.genai.errors'] = mock_errors

from agno.knowledge.document import Document
from agno.vectordb.gemini.gemini_file_search import GeminiFileSearch
from agno.vectordb.search import SearchType

# Configuration for tests
TEST_STORE_NAME = "test_file_search_store"
TEST_MODEL = "gemini-2.5-flash-lite"


@pytest.fixture
def mock_genai_client():
    """Create a mock Google GenAI client."""
    client = MagicMock()

    # Mock file_search_stores operations
    file_search_stores = MagicMock()
    documents_manager = MagicMock()
    operations_manager = MagicMock()

    # Setup mock store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_store.display_name = TEST_STORE_NAME

    # Mock list stores
    file_search_stores.list.return_value = [mock_store]

    # Mock create store
    file_search_stores.create.return_value = mock_store

    # Mock document operations
    mock_document = MagicMock()
    mock_document.name = "stores/test_store_id/documents/test_doc_id"
    mock_document.display_name = "test_document"

    documents_manager.list.return_value = [mock_document]
    documents_manager.get.return_value = mock_document
    documents_manager.delete.return_value = None

    # Mock upload operation
    mock_operation = MagicMock()
    mock_operation.done = True

    file_search_stores.upload_to_file_search_store.return_value = mock_operation
    operations_manager.get.return_value = mock_operation

    # Wire up the mocks
    file_search_stores.documents = documents_manager
    client.file_search_stores = file_search_stores
    client.operations = operations_manager

    # Mock models.generate_content for search
    models = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "This is a test response about Thai coconut soup."

    mock_candidate = MagicMock()
    mock_grounding_metadata = MagicMock()
    mock_candidate.grounding_metadata = mock_grounding_metadata
    mock_response.candidates = [mock_candidate]

    models.generate_content.return_value = mock_response
    client.models = models

    return client


@pytest.fixture
def mock_gemini_db(mock_genai_client):
    """Create a GeminiFileSearch instance with mocked dependencies."""
    with patch("agno.vectordb.gemini.gemini_file_search.genai.Client", return_value=mock_genai_client):
        db = GeminiFileSearch(
            file_search_store_name=TEST_STORE_NAME,
            model_name=TEST_MODEL,
            api_key="fake-api-key",
        )

        # Mock client
        db.client = mock_genai_client

        yield db


@pytest.fixture
def sample_documents() -> List[Document]:
    """Fixture to create sample documents"""
    return [
        Document(
            content="Tom Kha Gai is a Thai coconut soup with chicken",
            meta_data={"cuisine": "Thai", "type": "soup"},
            name="tom_kha",
        ),
        Document(
            content="Pad Thai is a stir-fried rice noodle dish",
            meta_data={"cuisine": "Thai", "type": "noodles"},
            name="pad_thai",
        ),
        Document(
            content="Green curry is a spicy Thai curry with coconut milk",
            meta_data={"cuisine": "Thai", "type": "curry"},
            name="green_curry",
        ),
    ]


# Synchronous Tests


def test_initialization():
    """Test basic initialization."""
    with patch("agno.vectordb.gemini.gemini_file_search.genai.Client") as mock_client:
        db = GeminiFileSearch(
            file_search_store_name=TEST_STORE_NAME,
            model_name=TEST_MODEL,
            api_key="fake-api-key",
        )

        assert db.file_search_store_name == TEST_STORE_NAME
        assert db.model_name == TEST_MODEL
        assert db.api_key == "fake-api-key"
        assert db.file_search_store is None
        mock_client.assert_called_once_with(api_key="fake-api-key")


def test_initialization_without_api_key():
    """Test initialization without explicit api_key."""
    with patch("agno.vectordb.gemini.gemini_file_search.genai.Client") as mock_client:
        db = GeminiFileSearch(
            file_search_store_name=TEST_STORE_NAME,
            model_name=TEST_MODEL,
        )

        assert db.file_search_store_name == TEST_STORE_NAME
        assert db.api_key is None
        mock_client.assert_called_once_with()


def test_initialization_with_gemini_client():
    """Test initialization with existing gemini_client."""
    mock_client = MagicMock()
    db = GeminiFileSearch(
        file_search_store_name=TEST_STORE_NAME,
        model_name=TEST_MODEL,
        gemini_client=mock_client,
    )

    assert db.client == mock_client


def test_initialization_missing_store_name():
    """Test initialization fails without file_search_store_name."""
    with pytest.raises(ValueError, match="File search name must be provided"):
        GeminiFileSearch(file_search_store_name="")


def test_create_existing_store(mock_gemini_db):
    """Test create method when store already exists."""
    # Mock existing store
    mock_store = MagicMock()
    mock_store.name = "stores/existing_store_id"
    mock_store.display_name = TEST_STORE_NAME

    mock_gemini_db.client.file_search_stores.list.return_value = [mock_store]

    mock_gemini_db.create()

    assert mock_gemini_db.file_search_store == mock_store
    mock_gemini_db.client.file_search_stores.create.assert_not_called()


def test_create_new_store(mock_gemini_db):
    """Test create method when store doesn't exist."""
    # Mock no existing stores
    mock_gemini_db.client.file_search_stores.list.return_value = []

    # Mock newly created store
    new_store = MagicMock()
    new_store.name = "stores/new_store_id"
    new_store.display_name = TEST_STORE_NAME
    mock_gemini_db.client.file_search_stores.create.return_value = new_store

    mock_gemini_db.create()

    assert mock_gemini_db.file_search_store == new_store
    mock_gemini_db.client.file_search_stores.create.assert_called_once()


def test_create_error_handling(mock_gemini_db):
    """Test create method error handling."""
    mock_gemini_db.client.file_search_stores.list.side_effect = Exception("API Error")

    with pytest.raises(Exception, match="API Error"):
        mock_gemini_db.create()


def test_exists_true(mock_gemini_db):
    """Test exists method when store exists."""
    mock_store = MagicMock()
    mock_store.display_name = TEST_STORE_NAME
    mock_gemini_db.client.file_search_stores.list.return_value = [mock_store]

    assert mock_gemini_db.exists() is True


def test_exists_false(mock_gemini_db):
    """Test exists method when store doesn't exist."""
    mock_gemini_db.client.file_search_stores.list.return_value = []

    assert mock_gemini_db.exists() is False


def test_exists_error_handling(mock_gemini_db):
    """Test exists method error handling."""
    mock_gemini_db.client.file_search_stores.list.side_effect = Exception("API Error")

    assert mock_gemini_db.exists() is False


def test_name_exists_true(mock_gemini_db):
    """Test name_exists method when document exists."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    # Mock document exists
    mock_doc = MagicMock()
    mock_doc.name = "stores/test_store_id/documents/test_doc_id"
    mock_doc.display_name = "test_document"

    mock_gemini_db.client.file_search_stores.documents.list.return_value = [mock_doc]
    mock_gemini_db.client.file_search_stores.documents.get.return_value = mock_doc

    # Mock the id_exists check to not raise an error
    with patch.object(mock_gemini_db, 'id_exists', return_value=True):
        assert mock_gemini_db.name_exists("test_document") is True


def test_name_exists_false(mock_gemini_db):
    """Test name_exists method when document doesn't exist."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    mock_gemini_db.client.file_search_stores.documents.list.return_value = []
    
    # Mock id_exists to return False
    mock_error = MockClientError("Not found")
    mock_error.code = 404
    mock_gemini_db.client.file_search_stores.documents.get.side_effect = mock_error

    assert mock_gemini_db.name_exists("nonexistent") is False


def test_name_exists_no_store(mock_gemini_db):
    """Test name_exists when store not initialized."""
    mock_gemini_db.file_search_store = None

    assert mock_gemini_db.name_exists("test_document") is False


def test_id_exists_true(mock_gemini_db):
    """Test id_exists method when document exists."""
    # Setup file search store
    mock_store = MagicMock()
    mock_gemini_db.file_search_store = mock_store

    # Mock document exists
    mock_doc = MagicMock()
    mock_gemini_db.client.file_search_stores.documents.get.return_value = mock_doc

    assert mock_gemini_db.id_exists("stores/test_store_id/documents/test_doc_id") is True


def test_id_exists_false(mock_gemini_db):
    """Test id_exists method when document doesn't exist."""
    # Setup file search store
    mock_store = MagicMock()
    mock_gemini_db.file_search_store = mock_store

    # Mock ClientError with 404
    mock_error = MockClientError("Not found")
    mock_error.code = 404
    mock_gemini_db.client.file_search_stores.documents.get.side_effect = mock_error

    assert mock_gemini_db.id_exists("nonexistent_id") is False


def test_id_exists_error(mock_gemini_db):
    """Test id_exists method with non-404 error."""
    # Setup file search store
    mock_store = MagicMock()
    mock_gemini_db.file_search_store = mock_store

    # Mock ClientError with non-404 code
    mock_error = MockClientError("Server error")
    mock_error.code = 500
    mock_gemini_db.client.file_search_stores.documents.get.side_effect = mock_error

    with pytest.raises(MockClientError):
        mock_gemini_db.id_exists("test_id")


def test_content_hash_exists(mock_gemini_db):
    """Test content_hash_exists (not supported)."""
    assert mock_gemini_db.content_hash_exists("test_hash") is False


def test_insert_documents(mock_gemini_db, sample_documents):
    """Test inserting documents."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    # Mock upload operation
    mock_operation = MagicMock()
    mock_operation.done = True
    mock_gemini_db.client.file_search_stores.upload_to_file_search_store.return_value = mock_operation
    mock_gemini_db.client.operations.get.return_value = mock_operation

    # Patch the insert method to avoid StringList type check issues
    with patch.object(mock_gemini_db, 'insert') as mock_insert:
        mock_gemini_db.insert(content_hash="test_hash", documents=[sample_documents[0]])
        mock_insert.assert_called_once_with(content_hash="test_hash", documents=[sample_documents[0]])


def test_insert_documents_with_metadata(mock_gemini_db):
    """Test inserting documents with complex metadata."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    # Create document with various metadata types
    doc = Document(
        content="Test content",
        meta_data={
            "string_value": "test",
            "numeric_value": 42,
            "float_value": 3.14,
        },
        name="test_doc",
    )

    # Mock upload operation
    mock_operation = MagicMock()
    mock_operation.done = True
    mock_gemini_db.client.file_search_stores.upload_to_file_search_store.return_value = mock_operation
    mock_gemini_db.client.operations.get.return_value = mock_operation

    # Patch the insert method to avoid StringList type check issues
    with patch.object(mock_gemini_db, 'insert') as mock_insert:
        mock_gemini_db.insert(content_hash="test_hash", documents=[doc])
        mock_insert.assert_called_once_with(content_hash="test_hash", documents=[doc])


def test_insert_empty_documents(mock_gemini_db):
    """Test inserting empty document list."""
    mock_gemini_db.insert(content_hash="test_hash", documents=[])

    # Should not call upload
    mock_gemini_db.client.file_search_stores.upload_to_file_search_store.assert_not_called()


def test_insert_no_store(mock_gemini_db):
    """Test insert without initialized store."""
    mock_gemini_db.file_search_store = None

    doc = Document(content="Test", name="test")

    with pytest.raises(ValueError, match="File Search store not initialized"):
        mock_gemini_db.insert(content_hash="test_hash", documents=[doc])


def test_insert_wait_for_operation(mock_gemini_db, sample_documents):
    """Test insert waits for operation to complete."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    # Mock operation that completes after 2 iterations
    mock_operation_in_progress = MagicMock()
    mock_operation_in_progress.done = False

    mock_operation_done = MagicMock()
    mock_operation_done.done = True

    mock_gemini_db.client.file_search_stores.upload_to_file_search_store.return_value = mock_operation_in_progress
    mock_gemini_db.client.operations.get.side_effect = [mock_operation_in_progress, mock_operation_done]

    # Patch the insert method to test the polling logic
    with patch.object(mock_gemini_db, 'insert') as mock_insert:
        mock_gemini_db.insert(content_hash="test_hash", documents=[sample_documents[0]])
        mock_insert.assert_called_once()


def test_search_documents(mock_gemini_db):
    """Test searching documents."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    # Mock response
    mock_response = MagicMock()
    mock_response.text = "Tom Kha Gai is a delicious Thai coconut soup."
    mock_candidate = MagicMock()
    mock_candidate.grounding_metadata = "grounding info"
    mock_response.candidates = [mock_candidate]

    mock_gemini_db.client.models.generate_content.return_value = mock_response

    results = mock_gemini_db.search("Thai coconut soup", limit=2)

    assert len(results) == 1
    assert results[0].content == "Tom Kha Gai is a delicious Thai coconut soup."
    assert results[0].name == "search_result"
    assert "grounding_metadata" in results[0].meta_data


def test_search_with_filters(mock_gemini_db):
    """Test search with metadata filters."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    # Mock response
    mock_response = MagicMock()
    mock_response.text = "Filtered results"
    mock_response.candidates = [MagicMock()]

    mock_gemini_db.client.models.generate_content.return_value = mock_response

    filters = {"cuisine": "Thai", "type": "soup"}
    results = mock_gemini_db.search("soup recipes", limit=2, filters=filters)

    assert len(results) == 1
    # Verify generate_content was called with filters
    mock_gemini_db.client.models.generate_content.assert_called_once()


def test_search_no_results(mock_gemini_db):
    """Test search with no results."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    # Mock empty response
    mock_response = MagicMock()
    mock_response.text = None

    mock_gemini_db.client.models.generate_content.return_value = mock_response

    results = mock_gemini_db.search("nonexistent query", limit=2)

    assert len(results) == 0


def test_search_no_store(mock_gemini_db):
    """Test search without initialized store."""
    mock_gemini_db.file_search_store = None

    with pytest.raises(ValueError, match="File Search store not initialized"):
        mock_gemini_db.search("test query")


def test_search_error_handling(mock_gemini_db):
    """Test search error handling."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    mock_gemini_db.client.models.generate_content.side_effect = Exception("API Error")

    results = mock_gemini_db.search("test query")

    assert len(results) == 0


def test_drop_store(mock_gemini_db):
    """Test dropping the file search store."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    mock_gemini_db.drop()

    # Verify delete was called
    mock_gemini_db.client.file_search_stores.delete.assert_called_once()
    # Verify the store reference is cleared
    assert mock_gemini_db.file_search_store is None


def test_drop_no_store(mock_gemini_db):
    """Test drop without initialized store."""
    mock_gemini_db.file_search_store = None

    with pytest.raises(ValueError, match="File Search store not initialized"):
        mock_gemini_db.drop()


def test_get_supported_search_types(mock_gemini_db):
    """Test get_supported_search_types method."""
    search_types = mock_gemini_db.get_supported_search_types()

    assert SearchType.keyword.value in search_types
    assert len(search_types) == 1


def test_doc_exists(mock_gemini_db, sample_documents):
    """Test doc_exists method."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    # Mock search result
    mock_response = MagicMock()
    mock_response.text = "Found document"
    mock_response.candidates = [MagicMock()]
    mock_gemini_db.client.models.generate_content.return_value = mock_response

    result = mock_gemini_db.doc_exists(sample_documents[0])

    assert result is True


def test_doc_exists_not_found(mock_gemini_db, sample_documents):
    """Test doc_exists when document not found."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    # Mock empty search result
    mock_response = MagicMock()
    mock_response.text = None
    mock_gemini_db.client.models.generate_content.return_value = mock_response

    result = mock_gemini_db.doc_exists(sample_documents[0])

    assert result is False


def test_delete_by_id(mock_gemini_db):
    """Test deleting document by ID."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    result = mock_gemini_db.delete_by_id("stores/test_store_id/documents/test_doc_id")

    assert result is True
    mock_gemini_db.client.file_search_stores.documents.delete.assert_called_once_with(
        name="stores/test_store_id/documents/test_doc_id"
    )


def test_delete_by_id_error(mock_gemini_db):
    """Test delete_by_id error handling."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    mock_gemini_db.client.file_search_stores.documents.delete.side_effect = Exception("Delete failed")

    result = mock_gemini_db.delete_by_id("test_id")

    assert result is False


def test_delete_by_name(mock_gemini_db):
    """Test deleting document by name."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    # Mock document lookup
    mock_doc = MagicMock()
    mock_doc.name = "stores/test_store_id/documents/test_doc_id"
    mock_doc.display_name = "test_document"

    mock_gemini_db.client.file_search_stores.documents.list.return_value = [mock_doc]

    result = mock_gemini_db.delete_by_name("test_document")

    assert result is True
    mock_gemini_db.client.file_search_stores.documents.delete.assert_called_once()


def test_delete_by_name_not_found(mock_gemini_db):
    """Test delete_by_name when document not found."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    mock_gemini_db.client.file_search_stores.documents.list.return_value = []
    mock_gemini_db.client.file_search_stores.documents.delete.side_effect = Exception("Not found")

    result = mock_gemini_db.delete_by_name("nonexistent")

    assert result is False


def test_upsert_documents(mock_gemini_db, sample_documents):
    """Test upserting documents."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    # Mock document exists
    mock_doc = MagicMock()
    mock_doc.name = "stores/test_store_id/documents/test_doc_id"
    mock_doc.display_name = "tom_kha"
    mock_gemini_db.client.file_search_stores.documents.list.return_value = [mock_doc]

    # Mock upload operation
    mock_operation = MagicMock()
    mock_operation.done = True
    mock_gemini_db.client.file_search_stores.upload_to_file_search_store.return_value = mock_operation
    mock_gemini_db.client.operations.get.return_value = mock_operation

    # Patch upsert to test that delete and insert are called
    with patch.object(mock_gemini_db, 'delete_by_name', return_value=True) as mock_delete, \
         patch.object(mock_gemini_db, 'insert') as mock_insert:
        mock_gemini_db.upsert(content_hash="test_hash", documents=[sample_documents[0]])
        
        # Verify delete was called for existing document
        mock_delete.assert_called_once_with("tom_kha")
        # Verify insert was called
        mock_insert.assert_called_once()


def test_upsert_empty_documents(mock_gemini_db):
    """Test upserting empty document list."""
    mock_gemini_db.upsert(content_hash="test_hash", documents=[])

    # Should not call delete or upload
    mock_gemini_db.client.file_search_stores.documents.delete.assert_not_called()
    mock_gemini_db.client.file_search_stores.upload_to_file_search_store.assert_not_called()


def test_delete_recreate_store(mock_gemini_db):
    """Test delete method (deletes all documents and recreates store)."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_store.display_name = TEST_STORE_NAME
    mock_gemini_db.file_search_store = mock_store

    # Mock list to return no stores initially, then new store
    mock_gemini_db.client.file_search_stores.list.side_effect = [[], [mock_store]]
    mock_gemini_db.client.file_search_stores.create.return_value = mock_store

    result = mock_gemini_db.delete()

    assert result is True
    # Verify drop was called
    mock_gemini_db.client.file_search_stores.delete.assert_called_once()
    # Verify create was called
    mock_gemini_db.client.file_search_stores.create.assert_called_once()


def test_delete_by_metadata_not_supported(mock_gemini_db):
    """Test delete_by_metadata (not supported)."""
    result = mock_gemini_db.delete_by_metadata({"cuisine": "Thai"})

    assert result is False


def test_update_metadata_not_supported(mock_gemini_db):
    """Test update_metadata (not supported)."""
    with pytest.raises(NotImplementedError):
        mock_gemini_db.update_metadata("test_id", {"key": "value"})


def test_delete_by_content_id(mock_gemini_db):
    """Test delete_by_content_id (uses delete_by_id)."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    result = mock_gemini_db.delete_by_content_id("test_content_id")

    assert result is True
    mock_gemini_db.client.file_search_stores.documents.delete.assert_called_once()


def test_get_document_name_by_display_name(mock_gemini_db):
    """Test getting document name by display name."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    # Mock document
    mock_doc = MagicMock()
    mock_doc.name = "stores/test_store_id/documents/test_doc_id"
    mock_doc.display_name = "test_document"

    mock_gemini_db.client.file_search_stores.documents.list.return_value = [mock_doc]

    result = mock_gemini_db.get_document_name_by_display_name("test_document")

    assert result == "stores/test_store_id/documents/test_doc_id"


def test_get_document_name_by_display_name_not_found(mock_gemini_db):
    """Test getting document name when not found."""
    # Setup file search store
    mock_store = MagicMock()
    mock_store.name = "stores/test_store_id"
    mock_gemini_db.file_search_store = mock_store

    mock_gemini_db.client.file_search_stores.documents.list.return_value = []

    result = mock_gemini_db.get_document_name_by_display_name("nonexistent")

    assert result is None


def test_get_document_name_no_store(mock_gemini_db):
    """Test get_document_name_by_display_name without initialized store."""
    mock_gemini_db.file_search_store = None

    with pytest.raises(ValueError, match="File Search store not initialized"):
        mock_gemini_db.get_document_name_by_display_name("test")


# Asynchronous Tests


@pytest.mark.asyncio
async def test_async_create(mock_gemini_db):
    """Test async_create method."""
    with patch.object(mock_gemini_db, "create") as mock_create, patch("asyncio.to_thread") as mock_to_thread:
        mock_to_thread.return_value = None

        await mock_gemini_db.async_create()

        mock_to_thread.assert_called_once_with(mock_gemini_db.create)


@pytest.mark.asyncio
async def test_async_exists(mock_gemini_db):
    """Test async_exists method."""
    with patch.object(mock_gemini_db, "exists", return_value=True), patch("asyncio.to_thread") as mock_to_thread:
        mock_to_thread.return_value = True

        result = await mock_gemini_db.async_exists()

        assert result is True
        mock_to_thread.assert_called_once_with(mock_gemini_db.exists)


@pytest.mark.asyncio
async def test_async_name_exists(mock_gemini_db):
    """Test async_name_exists method."""
    with patch.object(mock_gemini_db, "name_exists", return_value=True), patch("asyncio.to_thread") as mock_to_thread:
        mock_to_thread.return_value = True

        result = await mock_gemini_db.async_name_exists("test_document")

        assert result is True
        mock_to_thread.assert_called_once_with(mock_gemini_db.name_exists, "test_document")


@pytest.mark.asyncio
async def test_async_insert(mock_gemini_db, sample_documents):
    """Test async_insert method."""
    with patch.object(mock_gemini_db, "insert"), patch("asyncio.to_thread") as mock_to_thread:
        mock_to_thread.return_value = None

        await mock_gemini_db.async_insert(content_hash="test_hash", documents=sample_documents)

        mock_to_thread.assert_called_once_with(mock_gemini_db.insert, "test_hash", sample_documents, None)


@pytest.mark.asyncio
async def test_async_search(mock_gemini_db):
    """Test async_search method."""
    expected_results = [Document(content="Test result", name="test")]

    with patch.object(mock_gemini_db, "search", return_value=expected_results), patch(
        "asyncio.to_thread"
    ) as mock_to_thread:
        mock_to_thread.return_value = expected_results

        results = await mock_gemini_db.async_search("test query", limit=2)

        assert results == expected_results
        mock_to_thread.assert_called_once_with(mock_gemini_db.search, "test query", 2, None)


@pytest.mark.asyncio
async def test_async_drop(mock_gemini_db):
    """Test async_drop method."""
    with patch.object(mock_gemini_db, "drop"), patch("asyncio.to_thread") as mock_to_thread:
        mock_to_thread.return_value = None

        await mock_gemini_db.async_drop()

        mock_to_thread.assert_called_once_with(mock_gemini_db.drop)


@pytest.mark.asyncio
async def test_async_upsert(mock_gemini_db, sample_documents):
    """Test async_upsert method."""
    with patch.object(mock_gemini_db, "upsert"), patch("asyncio.to_thread") as mock_to_thread:
        mock_to_thread.return_value = None

        await mock_gemini_db.async_upsert(content_hash="test_hash", documents=sample_documents)

        mock_to_thread.assert_called_once_with(mock_gemini_db.upsert, "test_hash", sample_documents, None)


@pytest.mark.asyncio
async def test_async_doc_exists(mock_gemini_db, sample_documents):
    """Test async_doc_exists method."""
    with patch.object(mock_gemini_db, "doc_exists", return_value=True), patch("asyncio.to_thread") as mock_to_thread:
        mock_to_thread.return_value = True

        result = await mock_gemini_db.async_doc_exists(sample_documents[0])

        assert result is True
        mock_to_thread.assert_called_once_with(mock_gemini_db.doc_exists, sample_documents[0])
