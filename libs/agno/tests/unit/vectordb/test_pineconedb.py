import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.document import Document
from agno.vectordb.pineconedb import PineconeDb

# Configuration for tests
TEST_INDEX_NAME = f"test_index_{uuid.uuid4().hex[:8]}"
TEST_DIMENSION = 1024
TEST_NAMESPACE = "test_namespace"


@pytest.fixture
def mock_pinecone_client():
    """Create a mock Pinecone client."""
    client = MagicMock()
    list_indexes_mock = MagicMock()
    list_indexes_mock.names.return_value = []
    client.list_indexes.return_value = list_indexes_mock
    return client


@pytest.fixture
def mock_pinecone_index():
    """Create a mock Pinecone index."""
    index = MagicMock()

    # Mock fetch method
    fetch_response = MagicMock()
    fetch_response.vectors = {}
    index.fetch.return_value = fetch_response

    # Mock query method
    query_response = MagicMock()
    match1 = MagicMock()
    match1.id = "doc_1"
    match1.metadata = {"text": "Test document 1", "type": "test"}
    match1.values = [0.1] * 1024
    match2 = MagicMock()
    match2.id = "doc_2"
    match2.metadata = {"text": "Test document 2", "type": "test"}
    match2.values = [0.2] * 1024
    query_response.matches = [match1, match2]
    index.query.return_value = query_response

    return index


@pytest.fixture
def mock_pinecone_db(mock_pinecone_client, mock_pinecone_index, mock_embedder):
    """Create a PineconeDb instance with mocked dependencies."""
    with patch("agno.vectordb.pineconedb.pineconedb.Pinecone", return_value=mock_pinecone_client):
        db = PineconeDb(
            name=TEST_INDEX_NAME,
            dimension=TEST_DIMENSION,
            namespace=TEST_NAMESPACE,
            spec={"serverless": {"cloud": "aws", "region": "us-west-2"}},
            embedder=mock_embedder,
            api_key="fake-api-key",
        )

        # Mock client and index
        db._client = mock_pinecone_client
        db._index = mock_pinecone_index

        yield db


def create_test_documents(num_docs=3):
    """Helper to create test documents."""
    return [
        Document(
            id=f"doc_{i}",
            content=f"This is test document {i}",
            meta_data={"type": "test", "index": i},
            name=f"test_doc_{i}",
        )
        for i in range(num_docs)
    ]


# Synchronous Tests
def test_initialization():
    """Test basic initialization."""
    with patch("agno.vectordb.pineconedb.pineconedb.Pinecone"):
        db = PineconeDb(
            name=TEST_INDEX_NAME,
            dimension=TEST_DIMENSION,
            namespace=TEST_NAMESPACE,
            spec={"serverless": {"cloud": "aws", "region": "us-west-2"}},
            api_key="fake-api-key",
        )

        assert db.name == TEST_INDEX_NAME
        assert db.dimension == TEST_DIMENSION
        assert db.namespace == TEST_NAMESPACE
        assert db.api_key == "fake-api-key"
        assert db._client is None
        assert db._index is None


def test_client_property(mock_pinecone_db, mock_pinecone_client):
    """Test client property."""
    # Reset client to None
    mock_pinecone_db._client = None

    # Test client property
    with patch("agno.vectordb.pineconedb.pineconedb.Pinecone", return_value=mock_pinecone_client):
        client = mock_pinecone_db.client

        assert client is not None
        assert client == mock_pinecone_client


def test_index_property(mock_pinecone_db, mock_pinecone_index):
    """Test index property."""
    # Reset index to None
    mock_pinecone_db._index = None

    # Mock client.Index to return mock_pinecone_index
    mock_pinecone_db.client.Index.return_value = mock_pinecone_index

    # Test index property
    index = mock_pinecone_db.index

    assert index is not None
    assert index == mock_pinecone_index
    mock_pinecone_db.client.Index.assert_called_once_with(TEST_INDEX_NAME)


def test_exists(mock_pinecone_db):
    """Test exists method."""
    # Test when index doesn't exist
    list_indexes_mock = MagicMock()
    list_indexes_mock.names.return_value = ["other_index"]
    mock_pinecone_db.client.list_indexes.return_value = list_indexes_mock

    assert mock_pinecone_db.exists() is False

    # Test when index exists
    list_indexes_mock.names.return_value = [TEST_INDEX_NAME]
    mock_pinecone_db.client.list_indexes.return_value = list_indexes_mock

    assert mock_pinecone_db.exists() is True


def test_create(mock_pinecone_db):
    """Test create method."""
    # Test when index doesn't exist
    with patch.object(mock_pinecone_db, "exists", return_value=False):
        mock_pinecone_db.create()

        mock_pinecone_db.client.create_index.assert_called_once_with(
            name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, spec=mock_pinecone_db.spec, metric="cosine", timeout=None
        )

    # Test when index exists
    with patch.object(mock_pinecone_db, "exists", return_value=True):
        mock_pinecone_db.client.create_index.reset_mock()
        mock_pinecone_db.create()

        mock_pinecone_db.client.create_index.assert_not_called()


def test_drop(mock_pinecone_db):
    """Test drop method."""
    # Test when index exists
    with patch.object(mock_pinecone_db, "exists", return_value=True):
        mock_pinecone_db.drop()

        mock_pinecone_db.client.delete_index.assert_called_once_with(name=TEST_INDEX_NAME, timeout=None)

    # Test when index doesn't exist
    with patch.object(mock_pinecone_db, "exists", return_value=False):
        mock_pinecone_db.client.delete_index.reset_mock()
        mock_pinecone_db.drop()

        mock_pinecone_db.client.delete_index.assert_not_called()


def test_doc_exists(mock_pinecone_db):
    """Test doc_exists method."""
    doc = create_test_documents(1)[0]

    # Test when document doesn't exist
    mock_pinecone_db.index.fetch.return_value.vectors = {}

    assert mock_pinecone_db.doc_exists(doc) is False
    mock_pinecone_db.index.fetch.assert_called_with(ids=[doc.id], namespace=TEST_NAMESPACE)

    # Test when document exists
    mock_pinecone_db.index.fetch.return_value.vectors = {doc.id: {"id": doc.id}}

    assert mock_pinecone_db.doc_exists(doc) is True


def test_name_exists(mock_pinecone_db):
    """Test name_exists method."""
    # Test when index exists
    mock_pinecone_db.client.describe_index.return_value = {}

    assert mock_pinecone_db.name_exists(TEST_INDEX_NAME) is True
    mock_pinecone_db.client.describe_index.assert_called_with(TEST_INDEX_NAME)

    # Test when index doesn't exist
    mock_pinecone_db.client.describe_index.side_effect = Exception("Index not found")

    assert mock_pinecone_db.name_exists(TEST_INDEX_NAME) is False


def test_upsert(mock_pinecone_db, mock_embedder):
    """Test upsert method."""
    docs = create_test_documents(2)

    # Mock embedder
    mock_embedder.get_embedding.return_value = [0.1] * 1024

    # Test upsert
    mock_pinecone_db.upsert(docs)

    # Check that index.upsert was called with the right arguments
    mock_pinecone_db.index.upsert.assert_called_once()

    # Extract the vectors argument from the call
    call_kwargs = mock_pinecone_db.index.upsert.call_args[1]
    vectors = call_kwargs.get("vectors", [])

    # Verify the vectors
    assert len(vectors) == 2
    assert vectors[0]["id"] == docs[0].id
    assert vectors[0]["metadata"]["text"] == docs[0].content
    assert "values" in vectors[0]


def test_insert_not_supported(mock_pinecone_db):
    """Test that insert raises NotImplementedError."""
    with pytest.raises(NotImplementedError):
        mock_pinecone_db.insert([])


def test_search(mock_pinecone_db, mock_embedder):
    """Test search method."""
    query = "test query"

    # Mock embedder
    mock_embedder.get_embedding.return_value = [0.1] * 1024

    # Test search
    results = mock_pinecone_db.search(query, limit=2)

    # Check that embedder.get_embedding was called
    mock_embedder.get_embedding.assert_called_with(query)

    # Check that index.query was called with the right arguments
    mock_pinecone_db.index.query.assert_called_with(
        vector=[0.1] * 1024, top_k=2, namespace=TEST_NAMESPACE, include_values=None, include_metadata=True
    )

    # Check the results
    assert len(results) == 2
    assert results[0].id == "doc_1"
    assert results[0].content == "Test document 1"
    assert results[1].id == "doc_2"
    assert results[1].content == "Test document 2"


def test_delete(mock_pinecone_db):
    """Test delete method."""
    # Test successful delete
    result = mock_pinecone_db.delete()

    assert result is True
    mock_pinecone_db.index.delete.assert_called_with(delete_all=True, namespace=None)

    # Test failed delete
    mock_pinecone_db.index.delete.side_effect = Exception("Delete failed")

    result = mock_pinecone_db.delete()

    assert result is False


def test_upsert_available(mock_pinecone_db):
    """Test upsert_available method."""
    assert mock_pinecone_db.upsert_available() is True


# Asynchronous Tests
@pytest.mark.asyncio
async def test_async_exists(mock_pinecone_db):
    """Test async_exists method."""
    # Mock exists to return True and patch to_thread
    with patch.object(mock_pinecone_db, "exists", return_value=True), patch("asyncio.to_thread") as mock_to_thread:
        mock_to_thread.return_value = True

        result = await mock_pinecone_db.async_exists()

        assert result is True
        mock_to_thread.assert_called_once_with(mock_pinecone_db.exists)


@pytest.mark.asyncio
async def test_async_create(mock_pinecone_db):
    """Test async_create method."""
    with patch.object(mock_pinecone_db, "create"), patch("asyncio.to_thread") as mock_to_thread:
        mock_to_thread.return_value = None

        await mock_pinecone_db.async_create()

        mock_to_thread.assert_called_once_with(mock_pinecone_db.create)


@pytest.mark.asyncio
async def test_async_doc_exists(mock_pinecone_db):
    """Test async_doc_exists method."""
    doc = create_test_documents(1)[0]

    with patch.object(mock_pinecone_db, "doc_exists", return_value=True), patch("asyncio.to_thread") as mock_to_thread:
        mock_to_thread.return_value = True

        result = await mock_pinecone_db.async_doc_exists(doc)

        assert result is True
        mock_to_thread.assert_called_once_with(mock_pinecone_db.doc_exists, doc)


@pytest.mark.asyncio
async def test_async_name_exists(mock_pinecone_db):
    """Test async_name_exists method."""
    with patch.object(mock_pinecone_db, "name_exists", return_value=True), patch("asyncio.to_thread") as mock_to_thread:
        mock_to_thread.return_value = True

        result = await mock_pinecone_db.async_name_exists(TEST_INDEX_NAME)

        assert result is True
        mock_to_thread.assert_called_once_with(mock_pinecone_db.name_exists, TEST_INDEX_NAME)


@pytest.mark.asyncio
async def test_async_upsert(mock_pinecone_db, mock_embedder):
    """Test async_upsert method."""
    docs = create_test_documents(2)

    # Mock embedder
    mock_embedder.get_embedding.return_value = [0.1] * 1024

    # Create the expected prepared vectors
    prepared_vectors_batch = [
        {"id": docs[0].id, "values": [0.1] * 1024, "metadata": {"text": docs[0].content, "type": "test", "index": 0}},
        {"id": docs[1].id, "values": [0.1] * 1024, "metadata": {"text": docs[1].content, "type": "test", "index": 1}},
    ]

    # Create an async mock for asyncio.gather
    gather_mock = AsyncMock()
    gather_mock.return_value = [prepared_vectors_batch]

    # Create an async mock for to_thread
    to_thread_mock = AsyncMock()
    to_thread_mock.return_value = prepared_vectors_batch

    # Mock async functions
    with patch.object(mock_pinecone_db, "_prepare_vectors", return_value=prepared_vectors_batch), patch.object(
        mock_pinecone_db, "_upsert_vectors"
    ), patch("asyncio.to_thread", to_thread_mock), patch("asyncio.gather", gather_mock):
        # Call the method
        await mock_pinecone_db.async_upsert(docs)

        # Verify gather was called
        gather_mock.assert_called_once()

        # Verify to_thread was called for upsert_vectors
        to_thread_mock.assert_any_call(
            mock_pinecone_db._upsert_vectors,
            prepared_vectors_batch,  # Using the flattened vectors
            mock_pinecone_db.namespace,
            None,  # batch_size
            False,  # show_progress
        )


@pytest.mark.asyncio
async def test_async_insert_not_supported(mock_pinecone_db):
    """Test that async_insert raises NotImplementedError."""
    with pytest.raises(NotImplementedError):
        await mock_pinecone_db.async_insert([])


@pytest.mark.asyncio
async def test_async_search(mock_pinecone_db):
    """Test async_search method."""
    query = "test query"
    expected_results = [Document(id="test", content="Test document")]

    with patch.object(mock_pinecone_db, "search", return_value=expected_results), patch(
        "asyncio.to_thread"
    ) as mock_to_thread:
        mock_to_thread.return_value = expected_results

        results = await mock_pinecone_db.async_search(query)

        assert results == expected_results
        mock_to_thread.assert_called_once_with(mock_pinecone_db.search, query, 5, None, None, None)


@pytest.mark.asyncio
async def test_async_drop_not_supported(mock_pinecone_db):
    """Test that async_drop raises NotImplementedError."""
    with pytest.raises(NotImplementedError):
        await mock_pinecone_db.async_drop()
