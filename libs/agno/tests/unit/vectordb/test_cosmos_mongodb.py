import uuid
from typing import Generator, List
from unittest.mock import MagicMock, patch

import pytest
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from agno.document import Document
from agno.vectordb.mongodb.cosmos_mongodb import AzureCosmosMongoDb


@pytest.fixture
def mock_embedder() -> MagicMock:
    """Create a mock embedder."""
    embedder = MagicMock()
    embedder.dimensions = 384
    embedder.get_embedding.return_value = [0.1] * 384
    embedder.embedding_dim = 384
    return embedder


@pytest.fixture(scope="function")
def mock_cosmos_client() -> Generator[MagicMock, None, None]:
    """Create a mock Cosmos DB client."""
    with patch("pymongo.MongoClient") as mock_client:
        # Create mock instances
        mock_collection = MagicMock(spec=Collection)
        mock_db = MagicMock(spec=Database)
        mock_client_instance = MagicMock(spec=MongoClient)

        # Setup the mock chain
        mock_client.return_value = mock_client_instance
        mock_client_instance.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_collection
        mock_db.list_collection_names = MagicMock(return_value=["test_vectors"])

        # Setup admin for ping
        mock_admin = MagicMock()
        mock_client_instance.admin = mock_admin
        mock_admin.command = MagicMock(return_value={"ok": 1})

        # Setup collection methods specific to Cosmos DB
        mock_collection.create_index = MagicMock(return_value=None)
        mock_collection.index_information = MagicMock(
            return_value={"vector_index_1": {"key": [("embedding", "cosmosSearch")]}}
        )
        mock_collection.aggregate = MagicMock(return_value=[])
        mock_collection.insert_many = MagicMock(return_value=None)
        mock_collection.find_one = MagicMock(return_value=None)
        mock_collection.delete_many = MagicMock(return_value=MagicMock(deleted_count=1))
        mock_collection.drop = MagicMock()

        yield mock_client_instance


@pytest.fixture(scope="function")
def cosmos_db(mock_cosmos_client: MagicMock, mock_embedder: MagicMock) -> AzureCosmosMongoDb:
    """Create a AzureCosmosMongoDb instance."""
    collection_name = f"test_vectors_{uuid.uuid4().hex[:8]}"
    db = AzureCosmosMongoDb(
        collection_name=collection_name,
        embedder=mock_embedder,
        client=mock_cosmos_client,
        database="test_vectordb",
        search_index_name="vector_index_1",
    )

    # Setup specific mocks for this instance
    db._db = mock_cosmos_client["test_vectordb"]
    db._collection = db._db[collection_name]

    return db


def create_test_documents(num_docs: int = 3) -> List[Document]:
    """Helper function to create test documents."""
    return [
        Document(
            id=f"doc_{i}",
            content=f"This is test document {i}",
            meta_data={"type": "test", "index": str(i)},
            name=f"test_doc_{i}",
        )
        for i in range(num_docs)
    ]


def test_cosmos_initialization(mock_cosmos_client: MagicMock, mock_embedder: MagicMock) -> None:
    """Test AzureCosmosMongoDb initialization."""
    db = AzureCosmosMongoDb(
        collection_name="test_vectors", database="test_vectordb", client=mock_cosmos_client, embedder=mock_embedder
    )
    assert db.collection_name == "test_vectors"
    assert db.database == "test_vectordb"
    assert db.is_cosmos_db is True

    # Test initialization with invalid parameters
    with pytest.raises(ValueError):
        AzureCosmosMongoDb(collection_name="", database="test_vectordb")

    with pytest.raises(ValueError):
        AzureCosmosMongoDb(collection_name="test_vectors", database="")


def test_cosmos_search_index_creation(cosmos_db: AzureCosmosMongoDb, mock_cosmos_client: MagicMock) -> None:
    """Test Cosmos DB vector search index creation."""
    collection = mock_cosmos_client["test_vectordb"][cosmos_db.collection_name]

    # Test index creation
    cosmos_db._create_search_index()

    # Verify create_index was called with correct parameters
    collection.create_index.assert_called_once()
    call_args = collection.create_index.call_args[0]
    kwargs = collection.create_index.call_args[1]

    # Check if the index configuration is correct
    assert call_args[0] == [("embedding", "cosmosSearch")]
    assert kwargs["name"] == "vector_index_1"
    assert kwargs["cosmosSearchOptions"]["kind"] == "vector-ivf"
    assert kwargs["cosmosSearchOptions"]["dimensions"] == 384
    assert kwargs["cosmosSearchOptions"]["similarity"] == "COS"


def test_cosmos_vector_search(
    cosmos_db: AzureCosmosMongoDb, mock_cosmos_client: MagicMock, mock_embedder: MagicMock
) -> None:
    """Test Cosmos DB vector search functionality."""
    collection = mock_cosmos_client["test_vectordb"][cosmos_db.collection_name]

    # Setup mock response for search
    mock_search_result = [
        {
            "_id": "doc_0",
            "content": "This is test document 0",
            "meta_data": {"type": "test", "index": "0"},
            "name": "test_doc_0",
            "similarityScore": 0.95,
        }
    ]
    collection.aggregate.return_value = mock_search_result

    # Perform search
    results = cosmos_db.search("test query", limit=5)

    # Verify results
    assert len(results) == 1
    assert results[0].id == "doc_0"
    assert results[0].meta_data["score"] == 0.95

    # Verify search pipeline
    pipeline_args = collection.aggregate.call_args[0][0]
    search_stage = pipeline_args[0]["$search"]
    assert "cosmosSearch" in search_stage
    assert search_stage["cosmosSearch"]["path"] == "embedding"
    assert search_stage["cosmosSearch"]["k"] == 5
    assert search_stage["cosmosSearch"]["nProbes"] == 2


def test_cosmos_index_exists(cosmos_db: AzureCosmosMongoDb, mock_cosmos_client: MagicMock) -> None:
    """Test Cosmos DB index existence check."""
    collection = mock_cosmos_client["test_vectordb"][cosmos_db.collection_name]

    # Test when index exists
    collection.index_information.return_value = {"vector_index_1": {"key": [("embedding", "cosmosSearch")]}}
    assert cosmos_db._search_index_exists() is True

    # Test when index doesn't exist
    collection.index_information.return_value = {"other_index": {"key": [("name", 1)]}}
    assert cosmos_db._search_index_exists() is False


def test_cosmos_similarity_metric(cosmos_db: AzureCosmosMongoDb) -> None:
    """Test Cosmos DB similarity metric conversion."""
    # Test different metrics
    cosmos_db.distance_metric = "cosine"
    assert cosmos_db._get_cosmos_similarity_metric() == "COS"

    cosmos_db.distance_metric = "euclidean"
    assert cosmos_db._get_cosmos_similarity_metric() == "L2"

    cosmos_db.distance_metric = "dotProduct"
    assert cosmos_db._get_cosmos_similarity_metric() == "IP"

    # Test default fallback
    cosmos_db.distance_metric = "unknown"
    assert cosmos_db._get_cosmos_similarity_metric() == "COS"
