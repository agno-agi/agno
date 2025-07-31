import json
import time
from typing import List
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agno.document import Document
from agno.embedder.base import Embedder
from agno.reranker.base import Reranker
from agno.vectordb.redis import RedisVector
from agno.vectordb.distance import Distance
from agno.vectordb.pgvector.index import HNSW, Ivfflat
from agno.vectordb.search import SearchType

# Test constants
TEST_INDEX_NAME = "test_index"
TEST_PREFIX = "test_doc:"
TEST_DIMENSION = 768
TEST_HOST = "localhost"
TEST_PORT = 6379


@pytest.fixture
def mock_embedder():
    """Mock embedder fixture."""
    embedder = Mock(spec=Embedder)
    embedder.dimensions = TEST_DIMENSION
    embedder.get_embedding.return_value = [0.1] * TEST_DIMENSION
    embedder.get_embedding_and_usage.return_value = ([0.1] * TEST_DIMENSION, {"tokens": 10})
    return embedder


@pytest.fixture
def mock_reranker():
    """Mock reranker fixture."""
    reranker = Mock(spec=Reranker)
    reranker.rerank.return_value = []
    return reranker


@pytest.fixture
def mock_redis_client():
    """Mock Redis client."""
    client = Mock()
    client.ping.return_value = True
    client.ft.return_value.info.side_effect = Exception("Index not found")
    client.ft.return_value.create_index.return_value = True
    client.ft.return_value.dropindex.return_value = True
    client.ft.return_value.search.return_value = Mock(docs=[], total=0)
    client.exists.return_value = 0
    client.pipeline.return_value.execute.return_value = [True] * 10
    client.hset.return_value = True
    client.scan_iter.return_value = []
    client.delete.return_value = 0
    return client


@pytest.fixture
def mock_redis_pipeline():
    """Mock Redis pipeline."""
    pipeline = Mock()
    pipeline.hset.return_value = pipeline
    pipeline.expire.return_value = pipeline
    pipeline.execute.return_value = [True] * 10
    pipeline.command_stack = []  # Empty list initially
    return pipeline


@pytest.fixture
def redis_vector_db(mock_embedder):
    """RedisVector instance with mock embedder."""
    with patch("agno.vectordb.redis.redis.Redis") as mock_redis_class:
        mock_client = Mock()
        mock_redis_class.return_value = mock_client
        
        db = RedisVector(
            index_name=TEST_INDEX_NAME,
            prefix=TEST_PREFIX,
            host=TEST_HOST,
            port=TEST_PORT,
            embedder=mock_embedder,
        )
        db.redis_client = mock_client
        return db


@pytest.fixture
def redis_vector_db_with_reranker(mock_embedder, mock_reranker):
    """RedisVector instance with mock embedder and reranker."""
    with patch("agno.vectordb.redis.redis.Redis") as mock_redis_class:
        mock_client = Mock()
        mock_redis_class.return_value = mock_client
        
        db = RedisVector(
            index_name=TEST_INDEX_NAME,
            prefix=TEST_PREFIX,
            host=TEST_HOST,
            port=TEST_PORT,
            embedder=mock_embedder,
            reranker=mock_reranker,
        )
        db.redis_client = mock_client
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


class TestRedisVectorInitialization:
    """Test RedisVector initialization."""

    def test_init_with_default_embedder(self):
        """Test initialization with default embedder."""
        with patch("agno.vectordb.redis.redis.Redis"), patch(
            "agno.embedder.openai.OpenAIEmbedder"
        ) as mock_openai:
            mock_embedder_instance = Mock()
            mock_embedder_instance.dimensions = TEST_DIMENSION
            mock_openai.return_value = mock_embedder_instance
            
            db = RedisVector(
                index_name=TEST_INDEX_NAME,
                prefix=TEST_PREFIX,
                host=TEST_HOST,
                port=TEST_PORT,
            )

            assert db.index_name == TEST_INDEX_NAME
            assert db.prefix == TEST_PREFIX
            assert db.dimensions == TEST_DIMENSION
            assert db.distance == Distance.cosine
            mock_openai.assert_called_once()

    def test_init_with_custom_parameters(self, mock_embedder, mock_reranker):
        """Test initialization with custom parameters."""
        vector_index = HNSW(m=32, ef_construction=256)

        with patch("agno.vectordb.redis.redis.Redis") as mock_redis_class:
            db = RedisVector(
                index_name=TEST_INDEX_NAME,
                prefix=TEST_PREFIX,
                host=TEST_HOST,
                port=TEST_PORT,
                db=1,
                password="test_password",
                ssl=True,
                embedder=mock_embedder,
                search_type=SearchType.hybrid,
                vector_index=vector_index,
                distance=Distance.l2,
                reranker=mock_reranker,
                expire=3600,
            )

            assert db.search_type == SearchType.hybrid
            assert db.distance == Distance.l2
            assert isinstance(db.vector_index, HNSW)
            assert db.vector_index.m == 32
            assert db.embedder == mock_embedder
            assert db.reranker == mock_reranker
            assert db.expire == 3600

            # Check Redis client was created with correct parameters
            mock_redis_class.assert_called_once_with(
                host=TEST_HOST,
                port=TEST_PORT,
                db=1,
                password="test_password",
                decode_responses=True,
                ssl=True,
            )

    def test_init_no_index_name_raises_error(self, mock_embedder):
        """Test initialization without index name raises error."""
        with pytest.raises(ValueError, match="Index name must be provided"):
            RedisVector(
                index_name="",
                embedder=mock_embedder,
            )

    def test_init_no_embedder_dimensions_raises_error(self):
        """Test initialization with embedder without dimensions raises error."""
        mock_embedder = Mock()
        mock_embedder.dimensions = None
        
        with patch("agno.vectordb.redis.redis.Redis"):
            with pytest.raises(ValueError, match="Embedder.dimensions must be set"):
                RedisVector(
                    index_name=TEST_INDEX_NAME,
                    embedder=mock_embedder,
                )

    def test_get_key(self, redis_vector_db):
        """Test _get_key method."""
        key = redis_vector_db._get_key("test_doc_id")
        assert key == f"{TEST_PREFIX}test_doc_id"

    def test_get_distance_metric(self, redis_vector_db):
        """Test _get_distance_metric method."""
        # Test default cosine
        assert redis_vector_db._get_distance_metric() == "COSINE"
        
        # Test L2
        redis_vector_db.distance = Distance.l2
        assert redis_vector_db._get_distance_metric() == "L2"
        
        # Test inner product
        redis_vector_db.distance = Distance.max_inner_product
        assert redis_vector_db._get_distance_metric() == "IP"

    def test_get_vector_algorithm(self, redis_vector_db):
        """Test _get_vector_algorithm method."""
        # Test HNSW (default)
        assert redis_vector_db._get_vector_algorithm() == "HNSW"
        
        # Test Ivfflat (maps to FLAT)
        redis_vector_db.vector_index = Ivfflat()
        assert redis_vector_db._get_vector_algorithm() == "FLAT"


class TestRedisVectorIndexOperations:
    """Test index operations."""

    def test_index_exists_true(self, redis_vector_db, mock_redis_client):
        """Test index_exists returns True when index exists."""
        # Mock the ft(index_name).info() call specifically
        mock_ft_instance = Mock()
        mock_ft_instance.info.return_value = {"index_name": TEST_INDEX_NAME}
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        assert redis_vector_db.index_exists() is True
        mock_redis_client.ft.assert_called_with(TEST_INDEX_NAME)

    def test_index_exists_false(self, redis_vector_db, mock_redis_client):
        """Test index_exists returns False when index doesn't exist."""
        mock_redis_client.ft.return_value.info.side_effect = Exception("Index not found")
        redis_vector_db.redis_client = mock_redis_client

        assert redis_vector_db.index_exists() is False

    def test_create_index_not_exists(self, redis_vector_db, mock_redis_client):
        """Test create when index doesn't exist."""
        # Mock the ft(index_name) to raise exception (index doesn't exist)
        mock_ft_instance = Mock()
        mock_ft_instance.info.side_effect = Exception("Index not found")
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        redis_vector_db.create()

        # Should call create_index since index doesn't exist
        mock_ft_instance.create_index.assert_called_once()
        call_args = mock_ft_instance.create_index.call_args
        assert call_args[1]["fields"] is not None
        assert call_args[1]["definition"] is not None

    def test_create_index_exists(self, redis_vector_db, mock_redis_client):
        """Test create when index already exists."""
        # Mock the ft(index_name).info() call to simulate existing index
        mock_ft_instance = Mock()
        mock_ft_instance.info.return_value = {"index_name": TEST_INDEX_NAME}
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        redis_vector_db.create()

        # Should not call create_index since index exists
        mock_ft_instance.create_index.assert_not_called()

    def test_create_exception(self, redis_vector_db, mock_redis_client):
        """Test create handles exceptions."""
        mock_redis_client.ft.return_value.info.side_effect = Exception("Index not found")
        mock_redis_client.ft.return_value.create_index.side_effect = Exception("Creation failed")
        redis_vector_db.redis_client = mock_redis_client

        with pytest.raises(Exception, match="Creation failed"):
            redis_vector_db.create()

    @pytest.mark.asyncio
    async def test_async_create(self, redis_vector_db):
        """Test async create method."""
        with patch.object(redis_vector_db, "create") as mock_create:
            await redis_vector_db.async_create()
            mock_create.assert_called_once()

    def test_drop_index_exists(self, redis_vector_db, mock_redis_client):
        """Test drop when index exists."""
        # Mock the ft(index_name) to simulate existing index
        mock_ft_instance = Mock()
        mock_ft_instance.info.return_value = {"index_name": TEST_INDEX_NAME}
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        redis_vector_db.drop()

        mock_ft_instance.dropindex.assert_called_once_with(delete_documents=True)

    def test_drop_index_not_exists(self, redis_vector_db, mock_redis_client):
        """Test drop when index doesn't exist."""
        mock_redis_client.ft.return_value.info.side_effect = Exception("Index not found")
        redis_vector_db.redis_client = mock_redis_client

        redis_vector_db.drop()

        mock_redis_client.ft.return_value.dropindex.assert_not_called()

    def test_drop_exception(self, redis_vector_db, mock_redis_client):
        """Test drop handles exceptions."""
        # Mock the ft(index_name) to simulate existing index but dropindex fails
        mock_ft_instance = Mock()
        mock_ft_instance.info.return_value = {"index_name": TEST_INDEX_NAME}
        mock_ft_instance.dropindex.side_effect = Exception("Delete failed")
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        with pytest.raises(Exception, match="Delete failed"):
            redis_vector_db.drop()

    async def test_async_drop(self, redis_vector_db):
        """Test async drop method."""
        with patch.object(redis_vector_db, "drop") as mock_drop:
            await redis_vector_db.async_drop()
            mock_drop.assert_called_once()


class TestRedisVectorDocumentOperations:
    """Test document operations."""

    def test_doc_exists_true(self, redis_vector_db, create_test_documents):
        """Test doc_exists returns True when document exists."""
        documents = create_test_documents(1)
        doc = documents[0]

        with patch.object(redis_vector_db, "content_hash_exists", return_value=True):
            assert redis_vector_db.doc_exists(doc) is True

    def test_doc_exists_false(self, redis_vector_db, create_test_documents):
        """Test doc_exists returns False when document doesn't exist."""
        documents = create_test_documents(1)
        doc = documents[0]

        with patch.object(redis_vector_db, "content_hash_exists", return_value=False):
            assert redis_vector_db.doc_exists(doc) is False

    async def test_async_doc_exists(self, redis_vector_db, create_test_documents):
        """Test async doc_exists method."""
        documents = create_test_documents(1)
        doc = documents[0]

        with patch.object(redis_vector_db, "doc_exists", return_value=True) as mock_doc_exists:
            result = await redis_vector_db.async_doc_exists(doc)
            assert result is True
            mock_doc_exists.assert_called_once_with(doc)

    def test_content_hash_exists_true(self, redis_vector_db, mock_redis_client):
        """Test content_hash_exists returns True when hash exists."""
        mock_search_result = Mock()
        mock_search_result.total = 1
        mock_ft_instance = Mock()
        mock_ft_instance.search.return_value = mock_search_result
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        assert redis_vector_db.content_hash_exists("test_hash") is True

    def test_content_hash_exists_false(self, redis_vector_db, mock_redis_client):
        """Test content_hash_exists returns False when hash doesn't exist."""
        mock_search_result = Mock()
        mock_search_result.total = 0
        mock_ft_instance = Mock()
        mock_ft_instance.search.return_value = mock_search_result
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        assert redis_vector_db.content_hash_exists("test_hash") is False

    def test_content_hash_exists_exception(self, redis_vector_db, mock_redis_client):
        """Test content_hash_exists handles exceptions."""
        mock_ft_instance = Mock()
        mock_ft_instance.search.side_effect = Exception("Search failed")
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        assert redis_vector_db.content_hash_exists("test_hash") is False

    def test_name_exists_true(self, redis_vector_db, mock_redis_client):
        """Test name_exists returns True when name exists."""
        mock_search_result = Mock()
        mock_search_result.total = 1
        mock_ft_instance = Mock()
        mock_ft_instance.search.return_value = mock_search_result
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        assert redis_vector_db.name_exists("test_name") is True

    def test_name_exists_false(self, redis_vector_db, mock_redis_client):
        """Test name_exists returns False when name doesn't exist."""
        mock_search_result = Mock()
        mock_search_result.total = 0
        mock_ft_instance = Mock()
        mock_ft_instance.search.return_value = mock_search_result
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        assert redis_vector_db.name_exists("test_name") is False

    def test_name_exists_exception(self, redis_vector_db, mock_redis_client):
        """Test name_exists handles exceptions."""
        mock_ft_instance = Mock()
        mock_ft_instance.search.side_effect = Exception("Search failed")
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        assert redis_vector_db.name_exists("test_name") is False

    async def test_async_name_exists(self, redis_vector_db):
        """Test async name_exists method."""
        with patch.object(redis_vector_db, "name_exists", return_value=True) as mock_name_exists:
            result = await redis_vector_db.async_name_exists("test_name")
            assert result is True
            mock_name_exists.assert_called_once_with("test_name")

    def test_id_exists_true(self, redis_vector_db, mock_redis_client):
        """Test id_exists returns True when ID exists."""
        mock_redis_client.exists.return_value = 1
        redis_vector_db.redis_client = mock_redis_client

        assert redis_vector_db.id_exists("test_id") is True
        expected_key = redis_vector_db._get_key("test_id")
        mock_redis_client.exists.assert_called_once_with(expected_key)

    def test_id_exists_false(self, redis_vector_db, mock_redis_client):
        """Test id_exists returns False when ID doesn't exist."""
        mock_redis_client.exists.return_value = 0
        redis_vector_db.redis_client = mock_redis_client

        assert redis_vector_db.id_exists("test_id") is False

    def test_id_exists_exception(self, redis_vector_db, mock_redis_client):
        """Test id_exists handles exceptions."""
        mock_redis_client.exists.side_effect = Exception("Connection error")
        redis_vector_db.redis_client = mock_redis_client

        assert redis_vector_db.id_exists("test_id") is False


class TestRedisVectorInsertOperations:
    """Test insert operations."""

    def test_insert_success(self, redis_vector_db, mock_redis_client, create_test_documents):
        """Test successful document insertion."""
        documents = create_test_documents(2)
        mock_pipeline = Mock()
        mock_pipeline.hset.return_value = mock_pipeline
        mock_pipeline.expire.return_value = mock_pipeline
        mock_pipeline.execute.return_value = [True] * 4
        mock_pipeline.command_stack = []
        
        mock_redis_client.pipeline.return_value = mock_pipeline
        redis_vector_db.redis_client = mock_redis_client

        redis_vector_db.insert(documents)

        mock_redis_client.pipeline.assert_called()
        assert mock_pipeline.hset.call_count == 2

    def test_insert_with_expire(self, redis_vector_db, mock_redis_client, create_test_documents):
        """Test insert with TTL expiration."""
        documents = create_test_documents(1)
        redis_vector_db.expire = 3600
        
        mock_pipeline = Mock()
        mock_pipeline.hset.return_value = mock_pipeline
        mock_pipeline.expire.return_value = mock_pipeline
        mock_pipeline.execute.return_value = [True] * 2
        mock_pipeline.command_stack = []
        
        mock_redis_client.pipeline.return_value = mock_pipeline
        redis_vector_db.redis_client = mock_redis_client

        redis_vector_db.insert(documents)

        mock_pipeline.expire.assert_called()

    def test_insert_with_filters(self, redis_vector_db, mock_redis_client, create_test_documents):
        """Test insert with additional filters."""
        documents = create_test_documents(1)
        filters = {"source": "test", "version": "1.0"}
        
        mock_pipeline = Mock()
        mock_pipeline.hset.return_value = mock_pipeline
        mock_pipeline.execute.return_value = [True]
        mock_pipeline.command_stack = []
        
        mock_redis_client.pipeline.return_value = mock_pipeline
        redis_vector_db.redis_client = mock_redis_client

        redis_vector_db.insert(documents, filters=filters)

        # Check that hset was called with the document data including filters
        mock_pipeline.hset.assert_called()
        call_args = mock_pipeline.hset.call_args
        mapping = call_args[1]["mapping"]
        assert "filters" in mapping
        assert json.loads(mapping["filters"]) == filters

    def test_insert_batch_processing(self, redis_vector_db, mock_redis_client, create_test_documents):
        """Test insert with batch processing."""
        documents = create_test_documents(150)  # More than default batch size
        
        # Track pipeline creation calls
        pipeline_instances = []
        
        def create_pipeline():
            mock_pipeline = Mock()
            
            # Mock hset to add items to command_stack to simulate real behavior
            def mock_hset(*args, **kwargs):
                mock_pipeline.command_stack.append("hset_command")
                return mock_pipeline
            
            mock_pipeline.hset.side_effect = mock_hset
            mock_pipeline.execute.return_value = [True] * 100
            mock_pipeline.command_stack = []  # Start empty
            pipeline_instances.append(mock_pipeline)
            return mock_pipeline
        
        mock_redis_client.pipeline.side_effect = create_pipeline
        redis_vector_db.redis_client = mock_redis_client

        redis_vector_db.insert(documents, batch_size=100)

        # For 150 docs with batch_size=100:
        # Should create 2 pipeline instances (initial + 1 after first batch)
        assert len(pipeline_instances) == 2
        
        # Verify total hset calls across all pipelines (one per document)
        total_hset_calls = sum(p.hset.call_count for p in pipeline_instances)
        assert total_hset_calls == 150

    def test_insert_empty_documents(self, redis_vector_db, mock_redis_client):
        """Test insert with empty document list."""
        mock_pipeline = Mock()
        mock_pipeline.command_stack = []
        mock_redis_client.pipeline.return_value = mock_pipeline
        redis_vector_db.redis_client = mock_redis_client

        redis_vector_db.insert([])

        # Should not execute pipeline if no documents
        mock_pipeline.execute.assert_not_called()

    def test_insert_exception(self, redis_vector_db, mock_redis_client, create_test_documents):
        """Test insert handles exceptions at the method level."""
        documents = create_test_documents(1)
        
        # Make pipeline creation fail to trigger outer exception handler
        mock_redis_client.pipeline.side_effect = Exception("Pipeline creation failed")
        redis_vector_db.redis_client = mock_redis_client

        # The outer exception handler will re-raise the original exception
        with pytest.raises(Exception, match="Pipeline creation failed"):
            redis_vector_db.insert(documents)

    async def test_async_insert(self, redis_vector_db, create_test_documents):
        """Test async insert method."""
        documents = create_test_documents(1)
        
        with patch.object(redis_vector_db, "insert") as mock_insert:
            await redis_vector_db.async_insert(documents)
            mock_insert.assert_called_once_with(documents, None)


class TestRedisVectorUpsertOperations:
    """Test upsert operations."""

    def test_upsert_available(self, redis_vector_db):
        """Test upsert_available returns True."""
        assert redis_vector_db.upsert_available() is True

    def test_upsert_calls_insert(self, redis_vector_db, create_test_documents):
        """Test upsert calls insert method."""
        documents = create_test_documents(1)
        
        with patch.object(redis_vector_db, "insert") as mock_insert:
            redis_vector_db.upsert(documents)
            mock_insert.assert_called_once_with(documents, None, 100)

    async def test_async_upsert(self, redis_vector_db, create_test_documents):
        """Test async upsert method."""
        documents = create_test_documents(1)
        
        with patch.object(redis_vector_db, "upsert") as mock_upsert:
            await redis_vector_db.async_upsert(documents)
            mock_upsert.assert_called_once_with(documents, None)


class TestRedisVectorSearchOperations:
    """Test search operations."""

    def test_search_vector_type(self, redis_vector_db):
        """Test search delegates to vector_search for vector type."""
        redis_vector_db.search_type = SearchType.vector
        
        with patch.object(redis_vector_db, "vector_search", return_value=[]) as mock_vector_search:
            redis_vector_db.search("test query")
            mock_vector_search.assert_called_once_with(query="test query", limit=5, filters=None)

    def test_search_keyword_type(self, redis_vector_db):
        """Test search delegates to keyword_search for keyword type."""
        redis_vector_db.search_type = SearchType.keyword
        
        with patch.object(redis_vector_db, "keyword_search", return_value=[]) as mock_keyword_search:
            redis_vector_db.search("test query")
            mock_keyword_search.assert_called_once_with(query="test query", limit=5, filters=None)

    def test_search_hybrid_type(self, redis_vector_db):
        """Test search delegates to hybrid_search for hybrid type."""
        redis_vector_db.search_type = SearchType.hybrid
        
        with patch.object(redis_vector_db, "hybrid_search", return_value=[]) as mock_hybrid_search:
            redis_vector_db.search("test query")
            mock_hybrid_search.assert_called_once_with(query="test query", limit=5, filters=None)

    def test_search_invalid_type(self, redis_vector_db):
        """Test search with invalid search type."""
        redis_vector_db.search_type = "invalid"
        
        results = redis_vector_db.search("test query")
        assert results == []

    async def test_async_search(self, redis_vector_db):
        """Test async search method."""
        with patch.object(redis_vector_db, "search", return_value=[]) as mock_search:
            await redis_vector_db.async_search("test query")
            mock_search.assert_called_once_with("test query", 5, None)

    def test_vector_search_success(self, redis_vector_db, mock_redis_client, mock_embedder):
        """Test successful vector search."""
        mock_doc = Mock()
        mock_doc.id = f"{TEST_PREFIX}doc_1"
        mock_doc.name = "test_doc"
        mock_doc.content = "test content"
        mock_doc.meta_data = '{"category": "test"}'
        mock_doc.usage = '{"tokens": 10}'
        
        mock_search_result = Mock()
        mock_search_result.docs = [mock_doc]
        
        mock_ft_instance = Mock()
        mock_ft_instance.search.return_value = mock_search_result
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        results = redis_vector_db.vector_search("test query", limit=5)

        assert len(results) == 1
        assert results[0].id == "doc_1"  # Prefix should be removed
        assert results[0].content == "test content"
        
        mock_embedder.get_embedding.assert_called_once_with("test query")
        mock_ft_instance.search.assert_called_once()

    def test_vector_search_with_filters(self, redis_vector_db, mock_redis_client, mock_embedder):
        """Test vector search with filters."""
        filters = {"category": "test", "status": "active"}
        
        mock_search_result = Mock()
        mock_search_result.docs = []
        mock_ft_instance = Mock()
        mock_ft_instance.search.return_value = mock_search_result
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        redis_vector_db.vector_search("test query", filters=filters)

        # Check that the search was called (filters are handled internally)
        mock_ft_instance.search.assert_called_once()
        call_args = mock_ft_instance.search.call_args
        # Verify that a query object was passed
        assert call_args[0][0] is not None

    def test_vector_search_no_embedding(self, redis_vector_db, mock_embedder):
        """Test vector search when embedder returns None."""
        mock_embedder.get_embedding.return_value = None

        results = redis_vector_db.vector_search("test query")

        assert results == []

    def test_vector_search_index_not_exists(self, redis_vector_db, mock_redis_client, mock_embedder):
        """Test vector search when index doesn't exist."""
        mock_ft_instance = Mock()
        mock_ft_instance.search.side_effect = Exception("Index not found")
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        with patch.object(redis_vector_db, "create") as mock_create:
            results = redis_vector_db.vector_search("test query")
            
            assert results == []
            mock_create.assert_called_once()

    def test_vector_search_with_reranker(self, redis_vector_db_with_reranker, mock_redis_client, mock_reranker):
        """Test vector search with reranker."""
        mock_doc = Mock()
        mock_doc.id = f"{TEST_PREFIX}doc_1"
        mock_doc.name = "test_doc"
        mock_doc.content = "test content"
        mock_doc.meta_data = '{"category": "test"}'
        mock_doc.usage = '{"tokens": 10}'
        
        mock_search_result = Mock()
        mock_search_result.docs = [mock_doc]
        mock_ft_instance = Mock()
        mock_ft_instance.search.return_value = mock_search_result
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db_with_reranker.redis_client = mock_redis_client

        reranked_docs = [Document(id="reranked_doc", content="reranked content")]
        mock_reranker.rerank.return_value = reranked_docs

        results = redis_vector_db_with_reranker.vector_search("test query")

        assert results == reranked_docs
        mock_reranker.rerank.assert_called_once()

    def test_keyword_search_success(self, redis_vector_db, mock_redis_client):
        """Test successful keyword search."""
        mock_doc = Mock()
        mock_doc.id = f"{TEST_PREFIX}doc_1"
        mock_doc.name = "test_doc"
        mock_doc.content = "test content"
        mock_doc.meta_data = '{"category": "test"}'
        mock_doc.usage = '{"tokens": 10}'
        
        mock_search_result = Mock()
        mock_search_result.docs = [mock_doc]
        
        mock_ft_instance = Mock()
        mock_ft_instance.search.return_value = mock_search_result
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        results = redis_vector_db.keyword_search("test query", limit=5)

        assert len(results) == 1
        assert results[0].id == "doc_1"
        
        mock_ft_instance.search.assert_called_once()

    def test_keyword_search_with_filters(self, redis_vector_db, mock_redis_client):
        """Test keyword search with filters."""
        filters = {"category": "test"}
        
        mock_search_result = Mock()
        mock_search_result.docs = []
        mock_ft_instance = Mock()
        mock_ft_instance.search.return_value = mock_search_result
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        redis_vector_db.keyword_search("test query", filters=filters)

        # Check that the search was called (filters are handled internally)
        mock_ft_instance.search.assert_called_once()
        call_args = mock_ft_instance.search.call_args
        # Verify that a query object was passed
        assert call_args[0][0] is not None

    def test_keyword_search_index_not_exists(self, redis_vector_db, mock_redis_client):
        """Test keyword search when index doesn't exist."""
        mock_ft_instance = Mock()
        mock_ft_instance.search.side_effect = Exception("Index not found")
        mock_redis_client.ft.return_value = mock_ft_instance
        redis_vector_db.redis_client = mock_redis_client

        with patch.object(redis_vector_db, "create") as mock_create:
            results = redis_vector_db.keyword_search("test query")
            
            assert results == []
            mock_create.assert_called_once()

    def test_hybrid_search_success(self, redis_vector_db):
        """Test successful hybrid search."""
        vector_results = [Document(id="vec_1", content="vector result")]
        keyword_results = [Document(id="key_1", content="keyword result")]
        
        with patch.object(redis_vector_db, "vector_search", return_value=vector_results), \
             patch.object(redis_vector_db, "keyword_search", return_value=keyword_results):
            
            results = redis_vector_db.hybrid_search("test query", limit=5)
            
            assert len(results) == 2
            assert results[0].id == "vec_1"
            assert results[1].id == "key_1"

    def test_hybrid_search_deduplication(self, redis_vector_db):
        """Test hybrid search removes duplicates."""
        duplicate_doc = Document(id="dup_1", content="duplicate result")
        vector_results = [duplicate_doc, Document(id="vec_1", content="vector result")]
        keyword_results = [duplicate_doc, Document(id="key_1", content="keyword result")]
        
        with patch.object(redis_vector_db, "vector_search", return_value=vector_results), \
             patch.object(redis_vector_db, "keyword_search", return_value=keyword_results):
            
            results = redis_vector_db.hybrid_search("test query", limit=5)
            
            # Should have 3 unique documents (duplicate removed)
            assert len(results) == 3
            doc_ids = [doc.id for doc in results]
            assert doc_ids.count("dup_1") == 1


class TestRedisVectorUtilityOperations:
    """Test utility operations."""

    def test_exists_calls_index_exists(self, redis_vector_db):
        """Test exists method calls index_exists."""
        with patch.object(redis_vector_db, "index_exists", return_value=True) as mock_index_exists:
            result = redis_vector_db.exists()
            assert result is True
            mock_index_exists.assert_called_once()

    async def test_async_exists(self, redis_vector_db):
        """Test async exists method."""
        with patch.object(redis_vector_db, "exists", return_value=True) as mock_exists:
            result = await redis_vector_db.async_exists()
            assert result is True
            mock_exists.assert_called_once()

    def test_get_count_success(self, redis_vector_db, mock_redis_client):
        """Test getting document count."""
        mock_search_result = Mock()
        mock_search_result.total = 42
        
        mock_redis_client.ft.return_value.search.return_value = mock_search_result
        redis_vector_db.redis_client = mock_redis_client

        with patch.object(redis_vector_db, "index_exists", return_value=True):
            count = redis_vector_db.get_count()
            assert count == 42

    def test_get_count_index_not_exists(self, redis_vector_db):
        """Test getting count when index doesn't exist."""
        with patch.object(redis_vector_db, "index_exists", return_value=False):
            count = redis_vector_db.get_count()
            assert count == 0

    def test_get_count_exception(self, redis_vector_db, mock_redis_client):
        """Test get_count handles exceptions."""
        mock_redis_client.ft.return_value.search.side_effect = Exception("Count failed")
        redis_vector_db.redis_client = mock_redis_client

        with patch.object(redis_vector_db, "index_exists", return_value=True):
            count = redis_vector_db.get_count()
            assert count == 0

    def test_optimize_no_recreate(self, redis_vector_db):
        """Test optimize without force recreate."""
        with patch.object(redis_vector_db, "index_exists", return_value=True), \
             patch.object(redis_vector_db, "create") as mock_create, \
             patch.object(redis_vector_db, "drop") as mock_drop:
            
            redis_vector_db.optimize(force_recreate=False)
            
            mock_create.assert_not_called()
            mock_drop.assert_not_called()

    def test_optimize_force_recreate(self, redis_vector_db):
        """Test optimize with force recreate."""
        with patch.object(redis_vector_db, "index_exists", return_value=True), \
             patch.object(redis_vector_db, "create") as mock_create, \
             patch.object(redis_vector_db, "drop") as mock_drop:
            
            redis_vector_db.optimize(force_recreate=True)
            
            mock_drop.assert_called_once()
            mock_create.assert_called_once()

    def test_optimize_create_if_not_exists(self, redis_vector_db):
        """Test optimize creates index if it doesn't exist."""
        with patch.object(redis_vector_db, "index_exists", return_value=False), \
             patch.object(redis_vector_db, "create") as mock_create:
            
            redis_vector_db.optimize(force_recreate=False)
            
            mock_create.assert_called_once()

    def test_delete_success(self, redis_vector_db, mock_redis_client):
        """Test deleting all documents."""
        mock_redis_client.scan_iter.return_value = [f"{TEST_PREFIX}doc1", f"{TEST_PREFIX}doc2"]
        mock_redis_client.delete.return_value = 2
        redis_vector_db.redis_client = mock_redis_client

        with patch.object(redis_vector_db, "index_exists", return_value=True):
            result = redis_vector_db.delete()
            
            assert result is True
            mock_redis_client.scan_iter.assert_called_once_with(match=f"{TEST_PREFIX}*")
            mock_redis_client.delete.assert_called_once()

    def test_delete_no_documents(self, redis_vector_db, mock_redis_client):
        """Test deleting when no documents exist."""
        mock_redis_client.scan_iter.return_value = []
        redis_vector_db.redis_client = mock_redis_client

        with patch.object(redis_vector_db, "index_exists", return_value=True):
            result = redis_vector_db.delete()
            
            assert result is True
            mock_redis_client.delete.assert_not_called()

    def test_delete_index_not_exists(self, redis_vector_db):
        """Test delete when index doesn't exist."""
        with patch.object(redis_vector_db, "index_exists", return_value=False):
            result = redis_vector_db.delete()
            assert result is True

    def test_delete_exception(self, redis_vector_db, mock_redis_client):
        """Test delete handles exceptions."""
        mock_redis_client.scan_iter.side_effect = Exception("Scan failed")
        redis_vector_db.redis_client = mock_redis_client

        with patch.object(redis_vector_db, "index_exists", return_value=True):
            result = redis_vector_db.delete()
            assert result is False


class TestRedisVectorEdgeCases:
    """Test edge cases and error conditions."""

    def test_clean_content(self, redis_vector_db):
        """Test content cleaning."""
        content_with_nulls = "Test content\x00with null\x00characters"
        cleaned = redis_vector_db._clean_content(content_with_nulls)
        
        assert "\x00" not in cleaned
        assert "\ufffd" in cleaned

    def test_large_document_handling(self, redis_vector_db, mock_redis_client, create_test_documents):
        """Test handling of large documents."""
        documents = create_test_documents(1)
        documents[0].content = "x" * 100000  # Large content
        
        mock_pipeline = Mock()
        mock_pipeline.hset.return_value = mock_pipeline
        mock_pipeline.execute.return_value = [True]
        mock_pipeline.command_stack = []
        
        mock_redis_client.pipeline.return_value = mock_pipeline
        redis_vector_db.redis_client = mock_redis_client

        redis_vector_db.insert(documents)

        mock_pipeline.hset.assert_called_once()

    def test_unicode_content_handling(self, redis_vector_db, mock_redis_client):
        """Test handling of unicode content."""
        unicode_content = "Test content with unicode: 你好世界 🌍"
        doc = Document(id="unicode_doc", content=unicode_content, embedding=[0.1] * TEST_DIMENSION)
        
        mock_pipeline = Mock()
        mock_pipeline.hset.return_value = mock_pipeline
        mock_pipeline.execute.return_value = [True]
        mock_pipeline.command_stack = []
        
        mock_redis_client.pipeline.return_value = mock_pipeline
        redis_vector_db.redis_client = mock_redis_client

        redis_vector_db.insert([doc])

        mock_pipeline.hset.assert_called_once()
        call_args = mock_pipeline.hset.call_args
        mapping = call_args[1]["mapping"]
        assert mapping["content"] == unicode_content

    def test_empty_query_search(self, redis_vector_db, mock_redis_client, mock_embedder):
        """Test search with empty query."""
        mock_search_result = Mock()
        mock_search_result.docs = []
        mock_redis_client.ft.return_value.search.return_value = mock_search_result
        redis_vector_db.redis_client = mock_redis_client

        results = redis_vector_db.vector_search("", limit=5)

        assert results == []
        mock_embedder.get_embedding.assert_called_once_with("")

    def test_very_large_limit(self, redis_vector_db, mock_redis_client, mock_embedder):
        """Test search with very large limit."""
        mock_search_result = Mock()
        mock_search_result.docs = []
        mock_redis_client.ft.return_value.search.return_value = mock_search_result
        redis_vector_db.redis_client = mock_redis_client

        results = redis_vector_db.vector_search("test", limit=10000)

        assert results == []
        call_args = mock_redis_client.ft.return_value.search.call_args
        # Check that the query was created with the large limit
        assert call_args is not None

    def test_document_without_id_generation(self, redis_vector_db, mock_redis_client):
        """Test document without ID gets content hash as ID."""
        doc = Document(content="test content", embedding=[0.1] * TEST_DIMENSION)
        
        mock_pipeline = Mock()
        mock_pipeline.hset.return_value = mock_pipeline
        mock_pipeline.execute.return_value = [True]
        mock_pipeline.command_stack = []
        
        mock_redis_client.pipeline.return_value = mock_pipeline
        redis_vector_db.redis_client = mock_redis_client

        redis_vector_db.insert([doc])

        # Check that hset was called with a key (meaning an ID was generated)
        mock_pipeline.hset.assert_called_once()
        call_args = mock_pipeline.hset.call_args
        key = call_args[0][0]  # First argument is the key
        # Key should be in format prefix:id
        assert key.startswith(TEST_PREFIX)
        assert len(key) > len(TEST_PREFIX)  # Should have an ID part

    def test_deepcopy(self, redis_vector_db):
        """Test deep copying RedisVector instance."""
        from copy import deepcopy
        
        copied_db = deepcopy(redis_vector_db)
        
        # Check that basic attributes are copied
        assert copied_db.index_name == redis_vector_db.index_name
        assert copied_db.prefix == redis_vector_db.prefix
        assert copied_db.dimensions == redis_vector_db.dimensions
        
        # Check that redis_client and embedder are reused (not deep copied)
        assert copied_db.redis_client is redis_vector_db.redis_client
        assert copied_db.embedder is redis_vector_db.embedder


class TestRedisVectorErrorHandling:
    """Test error handling in various scenarios."""

    def test_redis_connection_error(self, mock_embedder):
        """Test handling Redis connection errors."""
        with patch("agno.vectordb.redis.redis.Redis") as mock_redis_class:
            mock_redis_class.side_effect = Exception("Connection failed")
            
            with pytest.raises(Exception, match="Connection failed"):
                RedisVector(
                    index_name=TEST_INDEX_NAME,
                    embedder=mock_embedder,
                )

    def test_embedding_dimension_mismatch(self, redis_vector_db):
        """Test handling embedding dimension mismatch."""
        doc = Document(
            id="test_doc",
            content="test content",
            embedding=[0.1] * (TEST_DIMENSION - 1),  # Wrong dimension
        )
        
        # This should be handled gracefully during insert
        with patch.object(redis_vector_db.redis_client, "pipeline") as mock_pipeline_method:
            mock_pipeline = Mock()
            mock_pipeline.hset.return_value = mock_pipeline
            mock_pipeline.execute.return_value = [True]
            mock_pipeline.command_stack = []
            mock_pipeline_method.return_value = mock_pipeline
            
            # Should not raise exception but log error
            redis_vector_db.insert([doc])

    def test_json_serialization_error(self, redis_vector_db, mock_redis_client):
        """Test handling JSON serialization errors."""
        # Create document with non-serializable metadata
        doc = Document(
            id="test_doc",
            content="test content",
            embedding=[0.1] * TEST_DIMENSION,
            meta_data={"func": lambda x: x}  # Non-serializable
        )
        
        mock_pipeline = Mock()
        mock_pipeline.hset.side_effect = Exception("JSON serialization failed")
        mock_redis_client.pipeline.return_value = mock_pipeline
        redis_vector_db.redis_client = mock_redis_client

        with pytest.raises(Exception):
            redis_vector_db.insert([doc])