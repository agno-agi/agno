from typing import List
from unittest.mock import Mock, patch

import pytest

from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.knowledge.reranker import Reranker
from agno.vectordb.s3vectors import S3VectorsDb

TEST_BUCKET_NAME = "test-vector-bucket"
TEST_INDEX_NAME = "test-index"
TEST_DIMENSION = 1024
TEST_REGION = "us-east-1"


@pytest.fixture
def mock_embedder():
    """Mock embedder fixture."""
    embedder = Mock(spec=Embedder)
    embedder.get_embedding_and_usage.return_value = ([0.1] * TEST_DIMENSION, {"tokens": 10})
    return embedder


@pytest.fixture
def mock_reranker():
    """Mock reranker fixture."""
    reranker = Mock(spec=Reranker)
    reranker.rerank.return_value = []
    return reranker


@pytest.fixture
def mock_s3vectors_client():
    """Mock S3Vectors client."""
    client = Mock()

    # Default successful responses
    client.list_vector_buckets.return_value = {"vectorBuckets": []}
    client.create_vector_bucket.return_value = {}
    client.get_vector_bucket.return_value = {
        "vectorBucket": {
            "vectorBucketName": TEST_BUCKET_NAME,
            "vectorBucketArn": f"arn:aws:s3vectors:{TEST_REGION}:123456789012:bucket/{TEST_BUCKET_NAME}",
            "creationTime": "2023-01-01T00:00:00Z",
            "encryptionConfiguration": {"sseType": "AES256"},
        }
    }
    client.delete_vector_bucket.return_value = {}

    client.create_index.return_value = {}
    client.get_index.return_value = {
        "index": {
            "vectorBucketName": TEST_BUCKET_NAME,
            "indexName": TEST_INDEX_NAME,
            "indexArn": f"arn:aws:s3vectors:{TEST_REGION}:123456789012:bucket/{TEST_BUCKET_NAME}/index/{TEST_INDEX_NAME}",
            "creationTime": "2023-01-01T00:00:00Z",
            "dataType": "float32",
            "dimension": TEST_DIMENSION,
            "distanceMetric": "cosine",
            "metadataConfiguration": {},
        }
    }
    client.delete_index.return_value = {}
    client.list_indexes.return_value = {"indexes": []}

    client.put_vectors.return_value = {}
    client.get_vectors.return_value = {"vectors": []}
    client.list_vectors.return_value = {"vectors": [], "nextToken": None}
    client.query_vectors.return_value = {"vectors": []}
    client.delete_vectors.return_value = {}

    return client


@pytest.fixture
def s3vectors_db(mock_embedder):
    """S3VectorsDb instance with mock embedder."""
    with patch("boto3.client"):
        db = S3VectorsDb(
            bucket_name=TEST_BUCKET_NAME,
            index_name=TEST_INDEX_NAME,
            dimension=TEST_DIMENSION,
            embedder=mock_embedder,
            region_name=TEST_REGION,
        )
        return db


@pytest.fixture
def s3vectors_db_with_reranker(mock_embedder, mock_reranker):
    """S3VectorsDb instance with mock embedder and reranker."""
    with patch("boto3.client"):
        db = S3VectorsDb(
            bucket_name=TEST_BUCKET_NAME,
            index_name=TEST_INDEX_NAME,
            dimension=TEST_DIMENSION,
            embedder=mock_embedder,
            reranker=mock_reranker,
            region_name=TEST_REGION,
        )
        return db


@pytest.fixture
def create_test_documents():
    """Create test documents."""

    def _create_documents(count: int = 3) -> List[Document]:
        documents = []
        for i in range(count):
            doc = Document(
                id=f"doc_{i}",
                content=f"Test content {i}",
                name=f"test_doc_{i}",
                meta_data={"category": f"category_{i}", "index": i},
                embedding=[0.1 + i * 0.1] * TEST_DIMENSION,
            )
            documents.append(doc)
        return documents

    return _create_documents


class TestS3VectorsDbInitialization:
    """Test S3VectorsDb initialization."""

    def test_init_with_default_embedder(self):
        """Test initialization with default embedder."""
        mock_openai_instance = Mock(spec=Embedder)
        mock_openai_class = Mock(return_value=mock_openai_instance)

        with patch("boto3.client"):
            with patch.dict("sys.modules", {"agno.knowledge.embedder.openai": Mock(OpenAIEmbedder=mock_openai_class)}):
                db = S3VectorsDb(
                    bucket_name=TEST_BUCKET_NAME,
                    index_name=TEST_INDEX_NAME,
                    dimension=TEST_DIMENSION,
                    region_name=TEST_REGION,
                )

                assert db.bucket_name == TEST_BUCKET_NAME
                assert db.index_name == TEST_INDEX_NAME
                assert db.dimension == TEST_DIMENSION
                assert db.distance_metric == "cosine"
                assert db.data_type == "float32"
                assert db.embedder == mock_openai_instance
                mock_openai_class.assert_called_once()

    def test_init_with_custom_parameters(self, mock_embedder, mock_reranker):
        """Test initialization with custom parameters."""
        with patch("boto3.client"):
            db = S3VectorsDb(
                bucket_name=TEST_BUCKET_NAME,
                index_name=TEST_INDEX_NAME,
                dimension=TEST_DIMENSION,
                embedder=mock_embedder,
                distance_metric="euclidean",
                data_type="float32",
                aws_access_key_id="test_key",
                aws_secret_access_key="test_secret",
                region_name=TEST_REGION,
                reranker=mock_reranker,
                non_filterable_metadata_keys=["description"],
            )

            assert db.distance_metric == "euclidean"
            assert db.data_type == "float32"
            assert db.embedder == mock_embedder
            assert db.reranker == mock_reranker
            assert db.non_filterable_metadata_keys == ["description"]

    def test_init_with_invalid_data_type(self, mock_embedder):
        """Test initialization with invalid data type."""
        with patch("boto3.client"):
            with pytest.raises(ValueError, match="Unsupported data type"):
                S3VectorsDb(
                    bucket_name=TEST_BUCKET_NAME,
                    index_name=TEST_INDEX_NAME,
                    dimension=TEST_DIMENSION,
                    embedder=mock_embedder,
                    data_type="float64",  # Invalid
                )

    def test_init_with_invalid_distance_metric(self, mock_embedder):
        """Test initialization with invalid distance metric."""
        with patch("boto3.client"):
            with pytest.raises(ValueError, match="Unsupported distance metric"):
                S3VectorsDb(
                    bucket_name=TEST_BUCKET_NAME,
                    index_name=TEST_INDEX_NAME,
                    dimension=TEST_DIMENSION,
                    embedder=mock_embedder,
                    distance_metric="manhattan",  # Invalid
                )

    def test_init_with_invalid_dimension(self, mock_embedder):
        """Test initialization with invalid dimension."""
        with patch("boto3.client"):
            with pytest.raises(ValueError, match="Dimension must be positive"):
                S3VectorsDb(
                    bucket_name=TEST_BUCKET_NAME,
                    index_name=TEST_INDEX_NAME,
                    dimension=0,  # Invalid
                    embedder=mock_embedder,
                )


class TestS3VectorsDbClient:
    """Test client creation and management."""

    def test_client_property(self, s3vectors_db, mock_s3vectors_client):
        """Test client property creation and caching."""
        with patch("boto3.client", return_value=mock_s3vectors_client):
            # First access should create client
            client1 = s3vectors_db.client
            assert client1 == mock_s3vectors_client
            mock_s3vectors_client.list_vector_buckets.assert_called_once()

            # Second access should return cached client
            client2 = s3vectors_db.client
            assert client1 is client2

    def test_client_creation_failure(self, s3vectors_db):
        """Test client creation failure."""
        with patch("boto3.client") as mock_boto3:
            mock_boto3.side_effect = Exception("Connection failed")

            with pytest.raises(Exception, match="Connection failed"):
                _ = s3vectors_db.client


class TestS3VectorsDbBucketOperations:
    """Test bucket and index operations."""

    def test_exists_true(self, s3vectors_db, mock_s3vectors_client):
        """Test exists returns True when bucket and index exist."""
        s3vectors_db._client = mock_s3vectors_client

        assert s3vectors_db.exists() is True
        mock_s3vectors_client.get_vector_bucket.assert_called_once_with(vectorBucketName=TEST_BUCKET_NAME)
        mock_s3vectors_client.get_index.assert_called_once_with(
            vectorBucketName=TEST_BUCKET_NAME, indexName=TEST_INDEX_NAME
        )

    def test_exists_false_bucket_not_found(self, s3vectors_db, mock_s3vectors_client):
        """Test exists returns False when bucket doesn't exist."""
        from botocore.exceptions import ClientError

        mock_s3vectors_client.get_vector_bucket.side_effect = ClientError(
            {"Error": {"Code": "NotFoundException"}}, "GetVectorBucket"
        )
        s3vectors_db._client = mock_s3vectors_client

        assert s3vectors_db.exists() is False

    def test_exists_false_index_not_found(self, s3vectors_db, mock_s3vectors_client):
        """Test exists returns False when index doesn't exist."""
        from botocore.exceptions import ClientError

        mock_s3vectors_client.get_index.side_effect = ClientError({"Error": {"Code": "NotFoundException"}}, "GetIndex")
        s3vectors_db._client = mock_s3vectors_client

        assert s3vectors_db.exists() is False

    def test_exists_exception(self, s3vectors_db, mock_s3vectors_client):
        """Test exists handles exceptions."""
        mock_s3vectors_client.get_vector_bucket.side_effect = Exception("Connection error")
        s3vectors_db._client = mock_s3vectors_client

        assert s3vectors_db.exists() is False

    @pytest.mark.asyncio
    async def test_async_exists(self, s3vectors_db, mock_s3vectors_client):
        """Test async exists method."""
        s3vectors_db._client = mock_s3vectors_client

        assert await s3vectors_db.async_exists() is True

    def test_create_bucket_and_index_not_exist(self, s3vectors_db, mock_s3vectors_client):
        """Test create when bucket and index don't exist."""
        from botocore.exceptions import ClientError

        # Mock bucket and index don't exist initially
        mock_s3vectors_client.get_vector_bucket.side_effect = ClientError(
            {"Error": {"Code": "NotFoundException"}}, "GetVectorBucket"
        )
        mock_s3vectors_client.get_index.side_effect = ClientError({"Error": {"Code": "NotFoundException"}}, "GetIndex")
        s3vectors_db._client = mock_s3vectors_client

        s3vectors_db.create()

        mock_s3vectors_client.create_vector_bucket.assert_called_once()
        mock_s3vectors_client.create_index.assert_called_once()

    def test_create_bucket_exists(self, s3vectors_db, mock_s3vectors_client):
        """Test create when bucket already exists."""
        from botocore.exceptions import ClientError

        # Bucket exists, index doesn't
        mock_s3vectors_client.get_index.side_effect = ClientError({"Error": {"Code": "NotFoundException"}}, "GetIndex")
        s3vectors_db._client = mock_s3vectors_client

        s3vectors_db.create()

        mock_s3vectors_client.create_vector_bucket.assert_not_called()
        mock_s3vectors_client.create_index.assert_called_once()

    def test_create_bucket_conflict(self, s3vectors_db, mock_s3vectors_client):
        """Test create handles bucket conflict exception."""
        from botocore.exceptions import ClientError

        mock_s3vectors_client.get_vector_bucket.side_effect = ClientError(
            {"Error": {"Code": "NotFoundException"}}, "GetVectorBucket"
        )
        mock_s3vectors_client.get_index.side_effect = ClientError({"Error": {"Code": "NotFoundException"}}, "GetIndex")
        mock_s3vectors_client.create_vector_bucket.side_effect = ClientError(
            {"Error": {"Code": "ConflictException"}}, "CreateVectorBucket"
        )
        s3vectors_db._client = mock_s3vectors_client

        s3vectors_db.create()  # Should not raise exception

        mock_s3vectors_client.create_index.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_create(self, s3vectors_db, mock_s3vectors_client):
        """Test async create method."""
        from botocore.exceptions import ClientError

        mock_s3vectors_client.get_vector_bucket.side_effect = ClientError(
            {"Error": {"Code": "NotFoundException"}}, "GetVectorBucket"
        )
        mock_s3vectors_client.get_index.side_effect = ClientError({"Error": {"Code": "NotFoundException"}}, "GetIndex")
        s3vectors_db._client = mock_s3vectors_client

        await s3vectors_db.async_create()

        mock_s3vectors_client.create_vector_bucket.assert_called_once()
        mock_s3vectors_client.create_index.assert_called_once()

    def test_drop_index_exists(self, s3vectors_db, mock_s3vectors_client):
        """Test drop when index exists."""
        s3vectors_db._client = mock_s3vectors_client

        s3vectors_db.drop()

        mock_s3vectors_client.delete_index.assert_called_once_with(
            vectorBucketName=TEST_BUCKET_NAME, indexName=TEST_INDEX_NAME
        )
        # Should also check for other indexes and potentially delete bucket
        mock_s3vectors_client.list_indexes.assert_called_once()

    def test_drop_index_not_exists(self, s3vectors_db, mock_s3vectors_client):
        """Test drop when index doesn't exist."""
        from botocore.exceptions import ClientError

        mock_s3vectors_client.get_index.side_effect = ClientError({"Error": {"Code": "NotFoundException"}}, "GetIndex")
        s3vectors_db._client = mock_s3vectors_client

        s3vectors_db.drop()

        mock_s3vectors_client.delete_index.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_drop(self, s3vectors_db, mock_s3vectors_client):
        """Test async drop method."""
        s3vectors_db._client = mock_s3vectors_client

        await s3vectors_db.async_drop()

        mock_s3vectors_client.delete_index.assert_called_once()


class TestS3VectorsDbDocumentOperations:
    """Test document operations."""

    def test_doc_exists_true(self, s3vectors_db, mock_s3vectors_client, create_test_documents):
        """Test doc_exists returns True when document exists."""
        documents = create_test_documents(1)
        doc = documents[0]

        mock_s3vectors_client.get_vectors.return_value = {
            "vectors": [{"key": doc.id, "data": {"float32": doc.embedding}}]
        }
        s3vectors_db._client = mock_s3vectors_client

        assert s3vectors_db.doc_exists(doc) is True
        mock_s3vectors_client.get_vectors.assert_called_once_with(
            vectorBucketName=TEST_BUCKET_NAME,
            indexName=TEST_INDEX_NAME,
            keys=[doc.id],
            returnData=False,
            returnMetadata=False,
        )

    def test_doc_exists_false(self, s3vectors_db, mock_s3vectors_client, create_test_documents):
        """Test doc_exists returns False when document doesn't exist."""
        documents = create_test_documents(1)
        doc = documents[0]

        mock_s3vectors_client.get_vectors.return_value = {"vectors": []}
        s3vectors_db._client = mock_s3vectors_client

        assert s3vectors_db.doc_exists(doc) is False

    def test_doc_exists_no_id(self, s3vectors_db):
        """Test doc_exists with document having no ID."""
        doc = Document(content="test content")

        assert s3vectors_db.doc_exists(doc) is False

    def test_doc_exists_exception(self, s3vectors_db, mock_s3vectors_client, create_test_documents):
        """Test doc_exists handles exceptions."""
        documents = create_test_documents(1)
        doc = documents[0]

        mock_s3vectors_client.get_vectors.side_effect = Exception("Connection error")
        s3vectors_db._client = mock_s3vectors_client

        assert s3vectors_db.doc_exists(doc) is False

    @pytest.mark.asyncio
    async def test_async_doc_exists(self, s3vectors_db, mock_s3vectors_client, create_test_documents):
        """Test async doc_exists method."""
        documents = create_test_documents(1)
        doc = documents[0]

        mock_s3vectors_client.get_vectors.return_value = {
            "vectors": [{"key": doc.id, "data": {"float32": doc.embedding}}]
        }
        s3vectors_db._client = mock_s3vectors_client

        assert await s3vectors_db.async_doc_exists(doc) is True

    def test_id_exists_true(self, s3vectors_db, mock_s3vectors_client):
        """Test id_exists returns True when ID exists."""
        mock_s3vectors_client.get_vectors.return_value = {
            "vectors": [{"key": "test_id", "data": {"float32": [0.1] * TEST_DIMENSION}}]
        }
        s3vectors_db._client = mock_s3vectors_client

        assert s3vectors_db.id_exists("test_id") is True

    def test_id_exists_false(self, s3vectors_db, mock_s3vectors_client):
        """Test id_exists returns False when ID doesn't exist."""
        mock_s3vectors_client.get_vectors.return_value = {"vectors": []}
        s3vectors_db._client = mock_s3vectors_client

        assert s3vectors_db.id_exists("test_id") is False


class TestS3VectorsDbDocumentPreparation:
    """Test document preparation for indexing."""

    def test_prepare_document_with_embedding(self, s3vectors_db, create_test_documents):
        """Test preparing document that already has embedding."""
        documents = create_test_documents(1)
        doc = documents[0]

        result = s3vectors_db._prepare_document_for_indexing(doc)

        assert result["key"] == doc.id
        assert result["data"]["float32"] == [float(x) for x in doc.embedding]
        assert result["metadata"]["content"] == doc.content
        assert result["metadata"]["name"] == doc.name
        assert result["metadata"]["category"] == doc.meta_data["category"]

    def test_prepare_document_without_embedding(self, s3vectors_db, mock_embedder):
        """Test preparing document without embedding."""
        doc = Document(id="test_doc", content="test content", name="test_name")

        mock_embedder.get_embedding_and_usage.return_value = ([0.1] * TEST_DIMENSION, {"tokens": 10})

        result = s3vectors_db._prepare_document_for_indexing(doc)

        mock_embedder.get_embedding_and_usage.assert_called_once_with("test content")
        assert result["data"]["float32"] == [0.1] * TEST_DIMENSION
        assert doc.embedding == [0.1] * TEST_DIMENSION

    def test_prepare_document_no_id(self, s3vectors_db):
        """Test preparing document without ID generates one."""
        doc = Document(content="test content", embedding=[0.1] * TEST_DIMENSION)

        s3vectors_db._prepare_document_for_indexing(doc)
        assert doc.id is not None

    def test_prepare_document_dimension_mismatch(self, s3vectors_db):
        """Test preparing document with wrong embedding dimension."""
        doc = Document(
            id="test_doc",
            content="test content",
            embedding=[0.1] * (TEST_DIMENSION - 1),  # Wrong dimension
        )

        with pytest.raises(ValueError, match="Embedding dimension mismatch"):
            s3vectors_db._prepare_document_for_indexing(doc)

    def test_prepare_document_no_embedding_no_embedder(self, s3vectors_db):
        """Test preparing document without embedding and no embedder."""
        s3vectors_db.embedder = None
        doc = Document(id="test_doc", content="test content")

        with pytest.raises(ValueError, match="No embedder available"):
            s3vectors_db._prepare_document_for_indexing(doc)


class TestS3VectorsDbInsertOperations:
    """Test insert operations."""

    def test_insert_success(self, s3vectors_db, mock_s3vectors_client, create_test_documents):
        """Test successful document insertion."""
        documents = create_test_documents(2)

        s3vectors_db._client = mock_s3vectors_client

        s3vectors_db.insert(documents)

        mock_s3vectors_client.put_vectors.assert_called()
        call_args = mock_s3vectors_client.put_vectors.call_args
        assert call_args[1]["vectorBucketName"] == TEST_BUCKET_NAME
        assert call_args[1]["indexName"] == TEST_INDEX_NAME
        assert len(call_args[1]["vectors"]) == 2

    def test_insert_creates_bucket_and_index_if_not_exists(
        self, s3vectors_db, mock_s3vectors_client, create_test_documents
    ):
        """Test insert creates bucket and index if they don't exist."""
        from botocore.exceptions import ClientError

        documents = create_test_documents(1)

        mock_s3vectors_client.get_vector_bucket.side_effect = ClientError(
            {"Error": {"Code": "NotFoundException"}}, "GetVectorBucket"
        )
        mock_s3vectors_client.get_index.side_effect = ClientError({"Error": {"Code": "NotFoundException"}}, "GetIndex")
        s3vectors_db._client = mock_s3vectors_client

        s3vectors_db.insert(documents)

        mock_s3vectors_client.create_vector_bucket.assert_called_once()
        mock_s3vectors_client.create_index.assert_called_once()
        mock_s3vectors_client.put_vectors.assert_called()

    def test_insert_empty_documents(self, s3vectors_db):
        """Test insert with empty document list."""
        s3vectors_db.insert([])
        # Should not raise any exception

    @pytest.mark.asyncio
    async def test_async_insert(self, s3vectors_db, mock_s3vectors_client, create_test_documents):
        """Test async insert method."""
        documents = create_test_documents(2)

        s3vectors_db._client = mock_s3vectors_client

        await s3vectors_db.async_insert(documents)

        mock_s3vectors_client.put_vectors.assert_called()


class TestS3VectorsDbUpsertOperations:
    """Test upsert operations."""

    def test_upsert_available(self, s3vectors_db):
        """Test upsert_available returns True."""
        assert s3vectors_db.upsert_available() is True

    def test_upsert_success(self, s3vectors_db, mock_s3vectors_client, create_test_documents):
        """Test successful document upsert."""
        documents = create_test_documents(2)

        s3vectors_db._client = mock_s3vectors_client

        s3vectors_db.upsert(documents)

        mock_s3vectors_client.put_vectors.assert_called()
        call_args = mock_s3vectors_client.put_vectors.call_args
        assert len(call_args[1]["vectors"]) == 2

    @pytest.mark.asyncio
    async def test_async_upsert(self, s3vectors_db, mock_s3vectors_client, create_test_documents):
        """Test async upsert method."""
        documents = create_test_documents(2)

        s3vectors_db._client = mock_s3vectors_client

        await s3vectors_db.async_upsert(documents)

        mock_s3vectors_client.put_vectors.assert_called()


class TestS3VectorsDbSearchOperations:
    """Test search operations."""

    def test_search_success(self, s3vectors_db, mock_s3vectors_client, mock_embedder):
        """Test successful search."""
        mock_s3vectors_client.query_vectors.return_value = {
            "vectors": [
                {
                    "key": "doc_1",
                    "distance": 0.1,
                    "metadata": {"content": "test content", "name": "test_doc", "category": "test"},
                    "data": {"float32": [0.1] * TEST_DIMENSION},
                }
            ]
        }
        s3vectors_db._client = mock_s3vectors_client

        results = s3vectors_db.search("test query", limit=5)

        assert len(results) == 1
        assert results[0].id == "doc_1"
        assert results[0].content == "test content"
        assert "search_score" in results[0].meta_data

        mock_embedder.get_embedding_and_usage.assert_called_once_with("test query")
        mock_s3vectors_client.query_vectors.assert_called_once()

    def test_search_with_filters(self, s3vectors_db, mock_s3vectors_client, mock_embedder):
        """Test search with filters."""
        filters = {"category": "test"}

        mock_s3vectors_client.query_vectors.return_value = {"vectors": []}
        s3vectors_db._client = mock_s3vectors_client

        s3vectors_db.search("test query", filters=filters)

        call_args = mock_s3vectors_client.query_vectors.call_args
        assert call_args[1]["filter"] == filters

    def test_search_bucket_not_exists(self, s3vectors_db, mock_s3vectors_client):
        """Test search when bucket doesn't exist."""
        from botocore.exceptions import ClientError

        mock_s3vectors_client.get_vector_bucket.side_effect = ClientError(
            {"Error": {"Code": "NotFoundException"}}, "GetVectorBucket"
        )
        s3vectors_db._client = mock_s3vectors_client

        results = s3vectors_db.search("test query")

        assert results == []
        mock_s3vectors_client.query_vectors.assert_not_called()

    def test_search_no_embedder(self, s3vectors_db, mock_s3vectors_client):
        """Test search when no embedder is configured."""
        s3vectors_db.embedder = None
        s3vectors_db._client = mock_s3vectors_client

        results = s3vectors_db.search("test query")

        assert results == []

    def test_search_with_reranker(self, s3vectors_db_with_reranker, mock_s3vectors_client, mock_reranker):
        """Test search with reranker."""
        mock_s3vectors_client.query_vectors.return_value = {
            "vectors": [
                {
                    "key": "doc_1",
                    "distance": 0.1,
                    "metadata": {"content": "test content"},
                    "data": {"float32": [0.1] * TEST_DIMENSION},
                }
            ]
        }
        s3vectors_db_with_reranker._client = mock_s3vectors_client

        reranked_docs = [Document(id="reranked_doc", content="reranked content")]
        mock_reranker.rerank.return_value = reranked_docs

        results = s3vectors_db_with_reranker.search("test query")

        assert results == reranked_docs
        mock_reranker.rerank.assert_called_once()

    def test_search_exception(self, s3vectors_db, mock_s3vectors_client, mock_embedder):
        """Test search handles exceptions."""
        mock_s3vectors_client.query_vectors.side_effect = Exception("Search failed")
        s3vectors_db._client = mock_s3vectors_client

        results = s3vectors_db.search("test query")

        assert results == []

    def test_keyword_search_not_supported(self, s3vectors_db):
        """Test keyword search returns empty list (not supported)."""
        results = s3vectors_db.keyword_search("test query")
        assert results == []

    def test_hybrid_search_fallback(self, s3vectors_db, mock_s3vectors_client, mock_embedder):
        """Test hybrid search falls back to vector search."""
        mock_s3vectors_client.query_vectors.return_value = {"vectors": []}
        s3vectors_db._client = mock_s3vectors_client

        results = s3vectors_db.hybrid_search("test query")

        # Should call vector search
        mock_s3vectors_client.query_vectors.assert_called_once()
        assert results == []


class TestS3VectorsDbUtilityOperations:
    """Test utility operations."""

    def test_get_document_by_id_found(self, s3vectors_db, mock_s3vectors_client):
        """Test getting document by ID when found."""
        mock_s3vectors_client.get_vectors.return_value = {
            "vectors": [
                {
                    "key": "test_id",
                    "data": {"float32": [0.1] * TEST_DIMENSION},
                    "metadata": {"content": "test content", "category": "test"},
                }
            ]
        }
        s3vectors_db._client = mock_s3vectors_client

        doc = s3vectors_db.get_document_by_id("test_id")

        assert doc is not None
        assert doc.id == "test_id"
        assert doc.content == "test content"
        assert doc.meta_data["category"] == "test"

    def test_get_document_by_id_not_found(self, s3vectors_db, mock_s3vectors_client):
        """Test getting document by ID when not found."""
        mock_s3vectors_client.get_vectors.return_value = {"vectors": []}
        s3vectors_db._client = mock_s3vectors_client

        doc = s3vectors_db.get_document_by_id("test_id")

        assert doc is None

    def test_get_document_by_id_bucket_not_exists(self, s3vectors_db, mock_s3vectors_client):
        """Test getting document by ID when bucket doesn't exist."""
        from botocore.exceptions import ClientError

        mock_s3vectors_client.get_vector_bucket.side_effect = ClientError(
            {"Error": {"Code": "NotFoundException"}}, "GetVectorBucket"
        )
        s3vectors_db._client = mock_s3vectors_client

        doc = s3vectors_db.get_document_by_id("test_id")

        assert doc is None

    def test_count_documents(self, s3vectors_db, mock_s3vectors_client):
        """Test counting documents."""
        mock_s3vectors_client.list_vectors.return_value = {
            "vectors": [{"key": f"doc_{i}"} for i in range(5)],
            "nextToken": None,
        }
        s3vectors_db._client = mock_s3vectors_client

        count = s3vectors_db.count()

        assert count == 5
        mock_s3vectors_client.list_vectors.assert_called()

    def test_count_documents_pagination(self, s3vectors_db, mock_s3vectors_client):
        """Test counting documents with pagination."""
        # First call returns 3 documents with nextToken
        # Second call returns 2 documents without nextToken
        mock_s3vectors_client.list_vectors.side_effect = [
            {"vectors": [{"key": f"doc_{i}"} for i in range(3)], "nextToken": "token1"},
            {"vectors": [{"key": f"doc_{i}"} for i in range(3, 5)], "nextToken": None},
        ]
        s3vectors_db._client = mock_s3vectors_client

        count = s3vectors_db.count()

        assert count == 5
        assert mock_s3vectors_client.list_vectors.call_count == 2

    def test_count_documents_bucket_not_exists(self, s3vectors_db, mock_s3vectors_client):
        """Test counting documents when bucket doesn't exist."""
        from botocore.exceptions import ClientError

        mock_s3vectors_client.get_vector_bucket.side_effect = ClientError(
            {"Error": {"Code": "NotFoundException"}}, "GetVectorBucket"
        )
        s3vectors_db._client = mock_s3vectors_client

        count = s3vectors_db.count()

        assert count == 0

    def test_delete_documents_success(self, s3vectors_db, mock_s3vectors_client):
        """Test deleting documents by IDs."""
        s3vectors_db._client = mock_s3vectors_client

        s3vectors_db.delete_documents(["doc1", "doc2"])

        mock_s3vectors_client.delete_vectors.assert_called_once_with(
            vectorBucketName=TEST_BUCKET_NAME, indexName=TEST_INDEX_NAME, keys=["doc1", "doc2"]
        )

    def test_delete_documents_empty_list(self, s3vectors_db, mock_s3vectors_client):
        """Test deleting documents with empty ID list."""
        s3vectors_db._client = mock_s3vectors_client

        s3vectors_db.delete_documents([])

        mock_s3vectors_client.delete_vectors.assert_not_called()

    def test_delete_documents_bucket_not_exists(self, s3vectors_db, mock_s3vectors_client):
        """Test deleting documents when bucket doesn't exist."""
        from botocore.exceptions import ClientError

        mock_s3vectors_client.get_vector_bucket.side_effect = ClientError(
            {"Error": {"Code": "NotFoundException"}}, "GetVectorBucket"
        )
        s3vectors_db._client = mock_s3vectors_client

        s3vectors_db.delete_documents(["doc1"])

        mock_s3vectors_client.delete_vectors.assert_not_called()

    def test_delete_all_documents(self, s3vectors_db, mock_s3vectors_client):
        """Test deleting all documents."""
        mock_s3vectors_client.list_vectors.return_value = {
            "vectors": [{"key": f"doc_{i}"} for i in range(3)],
            "nextToken": None,
        }
        s3vectors_db._client = mock_s3vectors_client

        result = s3vectors_db.delete()

        assert result is True
        mock_s3vectors_client.list_vectors.assert_called()
        mock_s3vectors_client.delete_vectors.assert_called_once()

    def test_delete_all_documents_bucket_not_exists(self, s3vectors_db, mock_s3vectors_client):
        """Test deleting all documents when bucket doesn't exist."""
        from botocore.exceptions import ClientError

        mock_s3vectors_client.get_vector_bucket.side_effect = ClientError(
            {"Error": {"Code": "NotFoundException"}}, "GetVectorBucket"
        )
        s3vectors_db._client = mock_s3vectors_client

        result = s3vectors_db.delete()

        assert result is False

    def test_optimize_no_op(self, s3vectors_db):
        """Test optimize is a no-op for S3Vectors."""
        s3vectors_db.optimize()
        # Should not raise any exception


class TestS3VectorsDbDocumentFromVector:
    """Test document creation from S3Vectors data."""

    def test_create_document_from_vector_complete(self, s3vectors_db):
        """Test creating document from complete vector data."""
        vector_data = {
            "key": "test_id",
            "data": {"float32": [0.1] * TEST_DIMENSION},
            "metadata": {
                "content": "test content",
                "name": "test_name",
                "category": "test",
                "usage": "{'tokens': 10}",
                "reranking_score": 0.8,
            },
        }

        doc = s3vectors_db._create_document_from_vector(vector_data, score=0.95)

        assert doc.id == "test_id"
        assert doc.content == "test content"
        assert doc.name == "test_name"
        assert doc.meta_data["category"] == "test"
        assert doc.meta_data["search_score"] == 0.95
        assert doc.embedding == [0.1] * TEST_DIMENSION
        assert doc.usage == {"tokens": 10}
        assert doc.reranking_score == 0.8

    def test_create_document_from_vector_minimal(self, s3vectors_db):
        """Test creating document from minimal vector data."""
        vector_data = {"key": "test_id", "data": {"float32": [0.1] * TEST_DIMENSION}}

        doc = s3vectors_db._create_document_from_vector(vector_data)

        assert doc.id == "test_id"
        assert doc.content == ""
        assert doc.name is None
        assert doc.embedding == [0.1] * TEST_DIMENSION
        assert doc.usage is None
        assert doc.reranking_score is None


class TestS3VectorsDbEdgeCases:
    """Test edge cases and error conditions."""

    def test_large_document_handling(self, s3vectors_db, mock_s3vectors_client, mock_embedder):
        """Test handling of large documents."""
        large_content = "x" * 10000  # Large content
        doc = Document(id="large_doc", content=large_content, embedding=[0.1] * TEST_DIMENSION)

        s3vectors_db._client = mock_s3vectors_client

        s3vectors_db.insert([doc])

        mock_s3vectors_client.put_vectors.assert_called_once()

    def test_unicode_content_handling(self, s3vectors_db, mock_s3vectors_client):
        """Test handling of unicode content."""
        unicode_content = "Test content with unicode: 你好世界 🌍"
        doc = Document(id="unicode_doc", content=unicode_content, embedding=[0.1] * TEST_DIMENSION)

        s3vectors_db._client = mock_s3vectors_client

        s3vectors_db.insert([doc])

        mock_s3vectors_client.put_vectors.assert_called_once()

    def test_empty_query_search(self, s3vectors_db, mock_s3vectors_client, mock_embedder):
        """Test search with empty query."""
        mock_s3vectors_client.query_vectors.return_value = {"vectors": []}
        s3vectors_db._client = mock_s3vectors_client

        results = s3vectors_db.search("", limit=5)

        assert results == []
        mock_embedder.get_embedding_and_usage.assert_called_once_with("")

    def test_very_large_limit(self, s3vectors_db, mock_s3vectors_client, mock_embedder):
        """Test search with very large limit."""
        mock_s3vectors_client.query_vectors.return_value = {"vectors": []}
        s3vectors_db._client = mock_s3vectors_client

        results = s3vectors_db.search("test", limit=10000)

        assert results == []
        call_args = mock_s3vectors_client.query_vectors.call_args
        assert call_args[1]["topK"] == 10000
