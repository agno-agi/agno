from typing import List
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agno.knowledge.document import Document
from agno.knowledge.embedder.base import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.vectordb.opensearch import OpenSearch
from agno.vectordb.search import SearchType

# Test constants
TEST_INDEX_NAME = "test_index"
TEST_DIMENSION = 768


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
def mock_opensearch_client():
    """Mock OpenSearch client."""
    client = Mock()
    client.ping.return_value = True
    client.indices.exists.return_value = False
    client.indices.create.return_value = {"acknowledged": True}
    client.indices.delete.return_value = {"acknowledged": True}
    client.exists.return_value = False
    client.search.return_value = {"hits": {"hits": [], "total": {"value": 0}}}
    client.bulk.return_value = {"errors": False, "items": []}
    client.get.return_value = {"found": False}
    client.count.return_value = {"count": 0}
    client.delete_by_query.return_value = {"deleted": 0}
    client.indices.forcemerge.return_value = {"acknowledged": True}
    return client


@pytest.fixture
def mock_async_opensearch_client():
    """Mock async OpenSearch client."""
    client = AsyncMock()
    client.ping.return_value = True
    client.indices.exists.return_value = False
    client.indices.create.return_value = {"acknowledged": True}
    client.indices.delete.return_value = {"acknowledged": True}
    client.exists.return_value = False
    client.search.return_value = {"hits": {"hits": [], "total": {"value": 0}}}
    client.bulk.return_value = {"errors": False, "items": []}
    client.get.return_value = {"found": False}
    client.count.return_value = {"count": 0}
    client.delete_by_query.return_value = {"deleted": 0}
    return client


@pytest.fixture
def opensearch_db(mock_embedder):
    """OpenSearch instance with mock embedder."""
    with (
        patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
        patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
    ):
        db = OpenSearch(index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, embedder=mock_embedder)
        return db


@pytest.fixture
def opensearch_db_with_reranker(mock_embedder, mock_reranker):
    """OpenSearch instance with mock embedder and reranker."""
    with (
        patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
        patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
    ):
        db = OpenSearch(
            index_name=TEST_INDEX_NAME,
            dimension=TEST_DIMENSION,
            embedder=mock_embedder,
            reranker=mock_reranker,
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


class TestOpenSearchInitialization:
    """Test OpenSearch initialization."""

    def test_init_with_default_embedder(self):
        """Test initialization with default embedder."""
        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
            patch("agno.knowledge.embedder.openai.OpenAIEmbedder") as mock_openai,
        ):
            db = OpenSearch(index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION)

            assert db.index_name == TEST_INDEX_NAME
            assert db.dimension == TEST_DIMENSION
            # lucene supports cosinesimil on every supported OpenSearch version, unlike
            # faiss which only gained it in 2.19
            assert db.engine == "lucene"
            assert db.space_type == "cosinesimil"
            mock_openai.assert_called_once()

    def test_index_name_is_the_only_required_argument(self, mock_embedder):
        """The common case must need nothing but an index name."""
        mock_embedder.dimensions = TEST_DIMENSION

        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
        ):
            db = OpenSearch(index_name=TEST_INDEX_NAME, embedder=mock_embedder)

            assert db.hosts == ["http://localhost:9200"]
            assert db.dimension == TEST_DIMENSION
            assert db.mapping["mappings"]["properties"]["embedding"]["dimension"] == TEST_DIMENSION

    def test_url_accepts_a_list_for_multi_node_clusters(self, mock_embedder):
        """A list of urls must be passed through to the client as multiple hosts."""
        urls = ["https://n1.example.com:9243", "https://n2.example.com:9243"]
        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient") as mock_client,
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
        ):
            db = OpenSearch(index_name=TEST_INDEX_NAME, url=urls, embedder=mock_embedder)
            _ = db.client

            assert db.hosts == urls
            assert mock_client.call_args[1]["hosts"] == urls

    def test_explicit_dimension_overrides_the_embedder(self, mock_embedder):
        """An explicit dimension must win over the embedder's dimensions."""
        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
        ):
            db = OpenSearch(index_name=TEST_INDEX_NAME, dimension=32, embedder=mock_embedder)

            assert db.dimension == 32
            assert db.mapping["mappings"]["properties"]["embedding"]["dimension"] == 32

    def test_undeterminable_dimension_raises(self):
        """A dimensionless embedder with no explicit dimension must fail loudly."""
        embedder = Mock(spec=Embedder)
        embedder.dimensions = None

        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
            pytest.raises(ValueError, match="dimension"),
        ):
            OpenSearch(index_name=TEST_INDEX_NAME, embedder=embedder)

    def test_empty_url_list_raises(self, mock_embedder):
        """An empty url list is a configuration error, not a silent default."""
        with pytest.raises(ValueError, match="url"):
            OpenSearch(index_name=TEST_INDEX_NAME, url=[], embedder=mock_embedder)

    def test_extra_kwargs_are_forwarded_to_the_client(self, mock_embedder):
        """Unrecognised kwargs must reach the underlying opensearch-py clients."""
        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient") as mock_client,
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient") as mock_async_client,
        ):
            db = OpenSearch(index_name=TEST_INDEX_NAME, embedder=mock_embedder, http_compress=True)
            _ = db.client
            _ = db.async_client

            assert mock_client.call_args[1]["http_compress"] is True
            assert mock_async_client.call_args[1]["http_compress"] is True

    def test_base_class_attributes_are_initialized(self, mock_embedder):
        """VectorDb base attributes must be set so the db can be registered and named."""
        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
        ):
            db = OpenSearch(
                index_name=TEST_INDEX_NAME,
                dimension=TEST_DIMENSION,
                embedder=mock_embedder,
            )

            assert db.id is not None
            assert db.name == "OpenSearch"
            assert db.description is None

    def test_explicit_id_and_name_are_preserved(self, mock_embedder):
        """Explicitly supplied id/name must override the generated defaults."""
        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
        ):
            db = OpenSearch(
                index_name=TEST_INDEX_NAME,
                dimension=TEST_DIMENSION,
                embedder=mock_embedder,
                id="custom-id",
                name="custom-name",
                description="custom description",
            )

            assert db.id == "custom-id"
            assert db.name == "custom-name"
            assert db.description == "custom description"

    def test_get_supported_search_types(self, mock_embedder):
        """Test that all three search types are reported as supported."""
        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
        ):
            db = OpenSearch(
                index_name=TEST_INDEX_NAME,
                dimension=TEST_DIMENSION,
                embedder=mock_embedder,
            )

            assert db.get_supported_search_types() == [
                SearchType.vector,
                SearchType.keyword,
                SearchType.hybrid,
            ]

    def test_init_with_custom_parameters(self, mock_embedder, mock_reranker):
        """Test initialization with custom parameters."""
        custom_params = {"ef_construction": 256, "m": 32}

        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
        ):
            db = OpenSearch(
                index_name=TEST_INDEX_NAME,
                dimension=TEST_DIMENSION,
                embedder=mock_embedder,
                distance="cosine",
                engine="faiss",
                search_type="vector",
                parameters=custom_params,
                http_auth=("user", "pass"),
                use_ssl=True,
                verify_certs=True,
                timeout=60,
                max_retries=5,
                retry_on_timeout=False,
                reranker=mock_reranker,
            )

            assert db.engine == "faiss"
            assert db.distance == "cosine"
            assert db.parameters["ef_construction"] == 256
            assert db.parameters["m"] == 32
            assert db.embedder == mock_embedder
            assert db.reranker == mock_reranker

    def test_create_mapping(self, opensearch_db):
        """Test mapping creation."""
        mapping = opensearch_db._create_mapping()

        assert "settings" in mapping
        assert "mappings" in mapping
        assert mapping["settings"]["index"]["knn"] is True
        assert mapping["mappings"]["properties"]["embedding"]["type"] == "knn_vector"
        assert mapping["mappings"]["properties"]["embedding"]["dimension"] == TEST_DIMENSION


class TestOpenSearchClient:
    """Test client creation and management."""

    def test_client_property(self, opensearch_db, mock_opensearch_client):
        """Test client property creation and caching."""
        with patch("agno.vectordb.opensearch.opensearch.OpenSearchClient", return_value=mock_opensearch_client):
            # First access should create client
            client1 = opensearch_db.client
            assert client1 == mock_opensearch_client
            mock_opensearch_client.ping.assert_called_once()

            # Second access should return cached client
            client2 = opensearch_db.client
            assert client1 is client2

    def test_client_creation_failure(self, opensearch_db):
        """Test client creation failure."""
        with patch("agno.vectordb.opensearch.opensearch.OpenSearchClient") as mock_class:
            mock_class.side_effect = Exception("Connection failed")

            with pytest.raises(Exception, match="Connection failed"):
                _ = opensearch_db.client

    def test_async_client_property(self, opensearch_db, mock_async_opensearch_client):
        """Test async client property creation and caching."""
        with patch(
            "agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient", return_value=mock_async_opensearch_client
        ):
            # First access should create client
            client1 = opensearch_db.async_client
            assert client1 == mock_async_opensearch_client

            # Second access should return cached client
            client2 = opensearch_db.async_client
            assert client1 is client2

    def test_async_client_forwards_connection_settings(self, opensearch_db, mock_async_opensearch_client):
        """Async client must honour the configured timeout and retry settings."""
        with patch(
            "agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient", return_value=mock_async_opensearch_client
        ) as mock_class:
            _ = opensearch_db.async_client

            kwargs = mock_class.call_args[1]
            assert kwargs["timeout"] == opensearch_db.timeout
            assert kwargs["max_retries"] == opensearch_db.max_retries
            assert kwargs["retry_on_timeout"] == opensearch_db.retry_on_timeout
            # connection_class is sync-only and must not leak into the async client
            assert "connection_class" not in kwargs

    def test_close_releases_sync_client(self, opensearch_db, mock_opensearch_client):
        """close() must close and clear the cached sync client."""
        opensearch_db._client = mock_opensearch_client

        opensearch_db.close()

        mock_opensearch_client.close.assert_called_once()
        assert opensearch_db._client is None

    @pytest.mark.asyncio
    async def test_async_close_releases_async_client(self, opensearch_db, mock_async_opensearch_client):
        """async_close() must close the aiohttp-backed client so it is not leaked."""
        opensearch_db._async_client = mock_async_opensearch_client

        await opensearch_db.async_close()

        mock_async_opensearch_client.close.assert_awaited_once()
        assert opensearch_db._async_client is None

    @pytest.mark.asyncio
    async def test_async_close_is_safe_without_client(self, opensearch_db):
        """async_close() must be a no-op when no client was ever created."""
        opensearch_db._async_client = None

        await opensearch_db.async_close()

        assert opensearch_db._async_client is None

    def test_async_client_creation_failure(self, opensearch_db):
        """Test async client creation failure."""
        with patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient") as mock_class:
            mock_class.side_effect = Exception("Connection failed")

            with pytest.raises(Exception, match="Connection failed"):
                _ = opensearch_db.async_client


class TestOpenSearchIndexOperations:
    """Test index operations."""

    def test_exists_true(self, opensearch_db, mock_opensearch_client):
        """Test exists returns True when index exists."""
        mock_opensearch_client.indices.exists.return_value = True
        opensearch_db._client = mock_opensearch_client

        assert opensearch_db.exists() is True
        mock_opensearch_client.indices.exists.assert_called_once_with(index=TEST_INDEX_NAME)

    def test_exists_false(self, opensearch_db, mock_opensearch_client):
        """Test exists returns False when index doesn't exist."""
        mock_opensearch_client.indices.exists.return_value = False
        opensearch_db._client = mock_opensearch_client

        assert opensearch_db.exists() is False

    def test_exists_exception(self, opensearch_db, mock_opensearch_client):
        """Test exists handles exceptions."""
        mock_opensearch_client.indices.exists.side_effect = Exception("Connection error")
        opensearch_db._client = mock_opensearch_client

        assert opensearch_db.exists() is False

    @pytest.mark.asyncio
    async def test_async_exists(self, opensearch_db, mock_async_opensearch_client):
        """Test async exists method."""
        mock_async_opensearch_client.indices.exists.return_value = True
        opensearch_db._async_client = mock_async_opensearch_client

        assert await opensearch_db.async_exists() is True
        mock_async_opensearch_client.indices.exists.assert_called_once_with(index=TEST_INDEX_NAME)

    def test_create_index_not_exists(self, opensearch_db, mock_opensearch_client):
        """Test create when index doesn't exist."""
        mock_opensearch_client.indices.exists.return_value = False
        opensearch_db._client = mock_opensearch_client

        opensearch_db.create()

        mock_opensearch_client.indices.create.assert_called_once_with(index=TEST_INDEX_NAME, body=opensearch_db.mapping)

    def test_create_index_exists(self, opensearch_db, mock_opensearch_client):
        """Test create when index already exists."""
        mock_opensearch_client.indices.exists.return_value = True
        opensearch_db._client = mock_opensearch_client

        opensearch_db.create()

        mock_opensearch_client.indices.create.assert_not_called()

    def test_create_exception(self, opensearch_db, mock_opensearch_client):
        """Test create handles exceptions."""
        mock_opensearch_client.indices.exists.return_value = False
        mock_opensearch_client.indices.create.side_effect = Exception("Creation failed")
        opensearch_db._client = mock_opensearch_client

        with pytest.raises(Exception, match="Creation failed"):
            opensearch_db.create()

    @pytest.mark.asyncio
    async def test_async_create(self, opensearch_db, mock_async_opensearch_client):
        """Test async create method."""
        mock_async_opensearch_client.indices.exists.return_value = False
        opensearch_db._async_client = mock_async_opensearch_client

        await opensearch_db.async_create()

        mock_async_opensearch_client.indices.create.assert_called_once_with(
            index=TEST_INDEX_NAME, body=opensearch_db.mapping
        )

    def test_drop_index_exists(self, opensearch_db, mock_opensearch_client):
        """Test drop when index exists."""
        mock_opensearch_client.indices.exists.return_value = True
        opensearch_db._client = mock_opensearch_client

        opensearch_db.drop()

        mock_opensearch_client.indices.delete.assert_called_once_with(index=TEST_INDEX_NAME)

    def test_drop_index_not_exists(self, opensearch_db, mock_opensearch_client):
        """Test drop when index doesn't exist."""
        mock_opensearch_client.indices.exists.return_value = False
        opensearch_db._client = mock_opensearch_client

        opensearch_db.drop()

        mock_opensearch_client.indices.delete.assert_not_called()

    def test_drop_exception(self, opensearch_db, mock_opensearch_client):
        """Test drop handles exceptions."""
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.indices.delete.side_effect = Exception("Delete failed")
        opensearch_db._client = mock_opensearch_client

        with pytest.raises(Exception, match="Delete failed"):
            opensearch_db.drop()

    @pytest.mark.asyncio
    async def test_async_drop(self, opensearch_db, mock_async_opensearch_client):
        """Test async drop method."""
        mock_async_opensearch_client.indices.exists.return_value = True
        opensearch_db._async_client = mock_async_opensearch_client

        await opensearch_db.async_drop()

        mock_async_opensearch_client.indices.delete.assert_called_once_with(index=TEST_INDEX_NAME)


class TestOpenSearchDocumentOperations:
    """Test document operations."""

    def test_doc_exists_true(self, opensearch_db, mock_opensearch_client, create_test_documents):
        """Test doc_exists returns True when document exists."""
        documents = create_test_documents(1)
        doc = documents[0]

        mock_opensearch_client.exists.return_value = True
        opensearch_db._client = mock_opensearch_client

        assert opensearch_db.doc_exists(doc) is True
        mock_opensearch_client.exists.assert_called_once_with(index=TEST_INDEX_NAME, id=doc.id)

    def test_doc_exists_false(self, opensearch_db, mock_opensearch_client, create_test_documents):
        """Test doc_exists returns False when document doesn't exist."""
        documents = create_test_documents(1)
        doc = documents[0]

        mock_opensearch_client.exists.return_value = False
        opensearch_db._client = mock_opensearch_client

        assert opensearch_db.doc_exists(doc) is False

    def test_doc_exists_no_id(self, opensearch_db):
        """Test doc_exists with document having no ID."""
        doc = Document(content="test content")

        assert opensearch_db.doc_exists(doc) is False

    def test_doc_exists_exception(self, opensearch_db, mock_opensearch_client, create_test_documents):
        """Test doc_exists handles exceptions."""
        documents = create_test_documents(1)
        doc = documents[0]

        mock_opensearch_client.exists.side_effect = Exception("Connection error")
        opensearch_db._client = mock_opensearch_client

        assert opensearch_db.doc_exists(doc) is False

    @pytest.mark.asyncio
    async def test_async_doc_exists(self, opensearch_db, mock_async_opensearch_client, create_test_documents):
        """Test async doc_exists method."""
        documents = create_test_documents(1)
        doc = documents[0]

        mock_async_opensearch_client.exists.return_value = True
        opensearch_db._async_client = mock_async_opensearch_client

        assert await opensearch_db.async_doc_exists(doc) is True
        mock_async_opensearch_client.exists.assert_called_once_with(index=TEST_INDEX_NAME, id=doc.id)

    def test_name_exists_true(self, opensearch_db, mock_opensearch_client):
        """Test name_exists returns True when name exists."""
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.search.return_value = {"hits": {"total": {"value": 1}}}
        opensearch_db._client = mock_opensearch_client

        assert opensearch_db.name_exists("test_name") is True

    def test_name_exists_false(self, opensearch_db, mock_opensearch_client):
        """Test name_exists returns False when name doesn't exist."""
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.search.return_value = {"hits": {"total": {"value": 0}}}
        opensearch_db._client = mock_opensearch_client

        assert opensearch_db.name_exists("test_name") is False

    def test_name_exists_index_not_exists(self, opensearch_db, mock_opensearch_client):
        """Test name_exists when index doesn't exist."""
        mock_opensearch_client.indices.exists.return_value = False
        opensearch_db._client = mock_opensearch_client

        assert opensearch_db.name_exists("test_name") is False

    @pytest.mark.asyncio
    async def test_async_name_exists(self, opensearch_db, mock_async_opensearch_client):
        """Test async name_exists method."""
        mock_async_opensearch_client.indices.exists.return_value = True
        mock_async_opensearch_client.search.return_value = {"hits": {"total": {"value": 1}}}
        opensearch_db._async_client = mock_async_opensearch_client

        assert await opensearch_db.async_name_exists("test_name") is True

    def test_id_exists_true(self, opensearch_db, mock_opensearch_client):
        """Test id_exists returns True when ID exists."""
        mock_opensearch_client.exists.return_value = True
        opensearch_db._client = mock_opensearch_client

        assert opensearch_db.id_exists("test_id") is True
        mock_opensearch_client.exists.assert_called_once_with(index=TEST_INDEX_NAME, id="test_id")

    def test_id_exists_false(self, opensearch_db, mock_opensearch_client):
        """Test id_exists returns False when ID doesn't exist."""
        mock_opensearch_client.exists.return_value = False
        opensearch_db._client = mock_opensearch_client

        assert opensearch_db.id_exists("test_id") is False

    def test_id_exists_exception(self, opensearch_db, mock_opensearch_client):
        """Test id_exists handles exceptions."""
        mock_opensearch_client.exists.side_effect = Exception("Connection error")
        opensearch_db._client = mock_opensearch_client

        assert opensearch_db.id_exists("test_id") is False


class TestOpenSearchDocumentPreparation:
    """Test document preparation for indexing."""

    def test_prepare_document_with_embedding(self, opensearch_db, create_test_documents):
        """Test preparing document that already has embedding."""
        documents = create_test_documents(1)
        doc = documents[0]

        result = opensearch_db._prepare_document_for_indexing(doc)

        expected_keys = {"embedding", "content", "meta_data", "name"}
        assert set(result.keys()) == expected_keys
        assert result["embedding"] == doc.embedding
        assert result["content"] == doc.content
        assert result["name"] == doc.name
        assert result["meta_data"] == doc.meta_data

    def test_prepare_document_without_embedding(self, opensearch_db, mock_embedder):
        """Test preparing document without embedding."""
        doc = Document(id="test_doc", content="test content", name="test_name")

        # The actual implementation calls doc.embed() which internally uses the embedder
        # So we need to mock the embedder's get_embedding_and_usage method
        mock_embedder.get_embedding_and_usage.return_value = ([0.1] * TEST_DIMENSION, {"tokens": 10})

        result = opensearch_db._prepare_document_for_indexing(doc)

        # Verify the embedder was called through the document's embed method
        mock_embedder.get_embedding_and_usage.assert_called_once_with("test content")
        assert result["embedding"] == [0.1] * TEST_DIMENSION
        assert doc.embedding == [0.1] * TEST_DIMENSION

    def test_build_doc_id_is_deterministic(self, opensearch_db):
        """Documents without an explicit ID must map to a stable _id, not a random one."""
        doc_a = Document(content="test content", meta_data={"content_hash": "hash1"})
        doc_b = Document(content="test content", meta_data={"content_hash": "hash1"})

        assert opensearch_db._build_doc_id(doc_a) == opensearch_db._build_doc_id(doc_b)

    def test_build_doc_id_varies_by_content_hash(self, opensearch_db):
        """The same content under a different content_hash must map to a different _id."""
        doc = Document(content="test content", meta_data={"content_hash": "hash1"})
        other = Document(content="test content", meta_data={"content_hash": "hash2"})

        assert opensearch_db._build_doc_id(doc) != opensearch_db._build_doc_id(other)

    def test_build_doc_id_uses_explicit_document_id(self, opensearch_db):
        """Documents with different explicit IDs must not collide."""
        doc = Document(id="doc-1", content="same", meta_data={"content_hash": "hash1"})
        other = Document(id="doc-2", content="same", meta_data={"content_hash": "hash1"})

        assert opensearch_db._build_doc_id(doc) != opensearch_db._build_doc_id(other)

    def test_prepare_document_no_id_does_not_mutate(self, opensearch_db):
        """Preparing a document must not assign a random ID onto the document."""
        doc = Document(content="test content", embedding=[0.1] * TEST_DIMENSION)

        opensearch_db._prepare_document_for_indexing(doc)

        assert doc.id is None

    def test_prepare_document_dimension_mismatch(self, opensearch_db):
        """Test preparing document with wrong embedding dimension."""
        doc = Document(
            id="test_doc",
            content="test content",
            embedding=[0.1] * (TEST_DIMENSION - 1),  # Wrong dimension
        )

        with pytest.raises(ValueError, match="Embedding dimension mismatch"):
            opensearch_db._prepare_document_for_indexing(doc)

    def test_prepare_document_no_embedding_no_embedder(self, opensearch_db):
        """Test preparing document without embedding and no embedder."""
        opensearch_db.embedder = None
        doc = Document(id="test_doc", content="test content")

        with pytest.raises(ValueError, match="No embedder available"):
            opensearch_db._prepare_document_for_indexing(doc)

    def test_prepare_document_embedding_generation_fails(self, opensearch_db, mock_embedder):
        """Test preparing document when embedding generation fails."""
        doc = Document(id="test_doc", content="test content")

        with patch.object(doc, "embed") as mock_embed:
            mock_embed.side_effect = Exception("Embedding failed")

            with pytest.raises(Exception, match="Embedding failed"):
                opensearch_db._prepare_document_for_indexing(doc)

    def test_prepare_document_with_optional_fields(self, opensearch_db):
        """Test preparing document with all optional fields."""
        doc = Document(
            id="test_doc",
            content="test content",
            name="test_name",
            meta_data={"key": "value"},
            embedding=[0.1] * TEST_DIMENSION,
            usage={"tokens": 10},
            reranking_score=0.9,
        )

        result = opensearch_db._prepare_document_for_indexing(doc)

        assert result["usage"] == doc.usage
        assert result["reranking_score"] == doc.reranking_score


class TestOpenSearchInsertOperations:
    """Test insert operations."""

    def test_insert_success(self, opensearch_db, mock_opensearch_client, create_test_documents):
        """Test successful document insertion."""
        documents = create_test_documents(2)

        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.bulk.return_value = {"errors": False, "items": []}
        opensearch_db._client = mock_opensearch_client

        opensearch_db.insert("test_hash", documents)

        mock_opensearch_client.bulk.assert_called_once()
        call_args = mock_opensearch_client.bulk.call_args
        assert call_args[1]["refresh"] is True

    def test_insert_merges_filters_into_metadata(self, opensearch_db, mock_opensearch_client, create_test_documents):
        """Filters passed to insert must be stored in metadata so they are searchable."""
        documents = create_test_documents(1)

        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.bulk.return_value = {"errors": False, "items": []}
        opensearch_db._client = mock_opensearch_client

        opensearch_db.insert("test_hash", documents, filters={"cuisine": "thai"})

        assert documents[0].meta_data["cuisine"] == "thai"
        assert documents[0].meta_data["content_hash"] == "test_hash"

    def test_insert_promotes_content_hash_to_top_level(
        self, opensearch_db, mock_opensearch_client, create_test_documents
    ):
        """content_hash must be indexed top-level so content_hash_exists() can match it."""
        documents = create_test_documents(1)

        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.bulk.return_value = {"errors": False, "items": []}
        opensearch_db._client = mock_opensearch_client

        opensearch_db.insert("test_hash", documents)

        bulk_body = mock_opensearch_client.bulk.call_args[1]["body"]
        indexed_docs = [entry for entry in bulk_body if "content" in entry]
        assert all(entry["content_hash"] == "test_hash" for entry in indexed_docs)

    def test_content_hash_is_mapped_as_keyword(self, opensearch_db):
        """content_hash must be an exact-match keyword field, with no length cap."""
        content_hash_mapping = opensearch_db.mapping["mappings"]["properties"]["content_hash"]

        assert content_hash_mapping == {"type": "keyword"}

    def test_metadata_keyword_subfields_come_from_a_dynamic_template(self, opensearch_db):
        """Metadata strings must get .keyword via a dynamic template, not a literal "*" field."""
        mappings = opensearch_db.mapping["mappings"]

        assert "*" not in mappings["properties"]["meta_data"].get("properties", {})

        template = mappings["dynamic_templates"][0]["meta_data_strings"]
        assert template["path_match"] == "meta_data.*"
        assert template["match_mapping_type"] == "string"
        assert template["mapping"]["fields"]["keyword"]["type"] == "keyword"

    def test_insert_creates_index_if_not_exists(self, opensearch_db, mock_opensearch_client, create_test_documents):
        """Test insert creates index if it doesn't exist."""
        documents = create_test_documents(1)

        mock_opensearch_client.indices.exists.return_value = False
        mock_opensearch_client.bulk.return_value = {"errors": False, "items": []}
        opensearch_db._client = mock_opensearch_client

        opensearch_db.insert("test_hash", documents)

        mock_opensearch_client.indices.create.assert_called_once()
        mock_opensearch_client.bulk.assert_called_once()

    def test_insert_empty_documents(self, opensearch_db, mock_opensearch_client):
        """Test insert with empty document list."""
        mock_opensearch_client.indices.exists.return_value = True
        opensearch_db._client = mock_opensearch_client

        opensearch_db.insert("test_hash", [])

        mock_opensearch_client.bulk.assert_not_called()

    def test_insert_bulk_error(self, opensearch_db, mock_opensearch_client, create_test_documents):
        """Test insert handles bulk operation errors."""
        documents = create_test_documents(1)

        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.bulk.return_value = {
            "errors": True,
            "items": [{"index": {"error": "Something went wrong"}}],
        }
        opensearch_db._client = mock_opensearch_client

        # Should not raise exception but log errors
        opensearch_db.insert("test_hash", documents)

        mock_opensearch_client.bulk.assert_called_once()

    def test_insert_exception(self, opensearch_db, mock_opensearch_client, create_test_documents):
        """Test insert handles exceptions."""
        documents = create_test_documents(1)

        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.bulk.side_effect = Exception("Bulk operation failed")
        opensearch_db._client = mock_opensearch_client

        with pytest.raises(Exception, match="Bulk operation failed"):
            opensearch_db.insert("test_hash", documents)

    @pytest.mark.asyncio
    async def test_async_insert(self, opensearch_db, mock_async_opensearch_client, create_test_documents):
        """Test async insert method."""
        documents = create_test_documents(2)

        mock_async_opensearch_client.indices.exists.return_value = True
        mock_async_opensearch_client.bulk.return_value = {"errors": False, "items": []}
        opensearch_db._async_client = mock_async_opensearch_client

        await opensearch_db.async_insert("test_hash", documents)

        mock_async_opensearch_client.bulk.assert_called_once()


class TestOpenSearchUpsertOperations:
    """Test upsert operations."""

    def test_upsert_available(self, opensearch_db):
        """Test upsert_available returns True."""
        assert opensearch_db.upsert_available() is True

    def test_upsert_targets_same_id_across_calls(self, opensearch_db, mock_opensearch_client, create_test_documents):
        """Re-upserting the same content must reuse the same _id instead of duplicating."""
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.bulk.return_value = {"errors": False, "items": []}
        opensearch_db._client = mock_opensearch_client

        def upsert_ids():
            opensearch_db.upsert("test_hash", create_test_documents(2))
            body = mock_opensearch_client.bulk.call_args[1]["body"]
            return [entry["update"]["_id"] for entry in body if "update" in entry]

        first_ids = upsert_ids()
        second_ids = upsert_ids()

        assert first_ids == second_ids

    def test_upsert_success(self, opensearch_db, mock_opensearch_client, create_test_documents):
        """Test successful document upsert."""
        documents = create_test_documents(2)

        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.bulk.return_value = {"errors": False, "items": []}
        opensearch_db._client = mock_opensearch_client

        opensearch_db.upsert("test_hash", documents)

        mock_opensearch_client.bulk.assert_called_once()
        call_args = mock_opensearch_client.bulk.call_args
        bulk_data = call_args[1]["body"]

        # Check that it uses update operations
        assert any("update" in item for item in bulk_data if isinstance(item, dict))

    def test_upsert_creates_index_if_not_exists(self, opensearch_db, mock_opensearch_client, create_test_documents):
        """Test upsert creates index if it doesn't exist."""
        documents = create_test_documents(1)

        mock_opensearch_client.indices.exists.return_value = False
        mock_opensearch_client.bulk.return_value = {"errors": False, "items": []}
        opensearch_db._client = mock_opensearch_client

        opensearch_db.upsert("test_hash", documents)

        mock_opensearch_client.indices.create.assert_called_once()
        mock_opensearch_client.bulk.assert_called_once()

    def test_upsert_empty_documents(self, opensearch_db, mock_opensearch_client):
        """Test upsert with empty document list."""
        mock_opensearch_client.indices.exists.return_value = True
        opensearch_db._client = mock_opensearch_client

        opensearch_db.upsert("test_hash", [])

        mock_opensearch_client.bulk.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_upsert(self, opensearch_db, mock_async_opensearch_client, create_test_documents):
        """Test async upsert method."""
        documents = create_test_documents(2)

        mock_async_opensearch_client.indices.exists.return_value = True
        mock_async_opensearch_client.bulk.return_value = {"errors": False, "items": []}
        opensearch_db._async_client = mock_async_opensearch_client

        await opensearch_db.async_upsert("test_hash", documents)

        mock_async_opensearch_client.bulk.assert_called_once()


class TestOpenSearchSearchOperations:
    """Test search operations."""

    def test_search_success(self, opensearch_db, mock_opensearch_client, mock_embedder):
        """Test successful search."""
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_id": "doc_1",
                        "_score": 0.9,
                        "_source": {
                            "content": "test content",
                            "name": "test_doc",
                            "meta_data": {"category": "test"},
                            "embedding": [0.1] * TEST_DIMENSION,
                        },
                    }
                ]
            }
        }
        opensearch_db._client = mock_opensearch_client

        results = opensearch_db.search("test query", limit=5)

        assert len(results) == 1
        assert results[0].id == "doc_1"
        assert results[0].content == "test content"
        assert results[0].meta_data["search_score"] == 0.9

        mock_embedder.get_embedding_and_usage.assert_called_once_with("test query")
        mock_opensearch_client.search.assert_called_once()

    def test_search_with_filters(self, opensearch_db, mock_opensearch_client, mock_embedder):
        """Test search with filters."""
        filters = {"category": "test", "status": {"$in": ["active", "pending"]}}

        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.search.return_value = {"hits": {"hits": []}}
        opensearch_db._client = mock_opensearch_client

        opensearch_db.search("test query", filters=filters)

        call_args = mock_opensearch_client.search.call_args
        search_body = call_args[1]["body"]

        # Should use bool query with filters
        assert "bool" in search_body["query"]
        assert "filter" in search_body["query"]["bool"]

    def test_search_index_not_exists(self, opensearch_db, mock_opensearch_client):
        """Test search when index doesn't exist."""
        mock_opensearch_client.indices.exists.return_value = False
        opensearch_db._client = mock_opensearch_client

        results = opensearch_db.search("test query")

        assert results == []
        mock_opensearch_client.search.assert_not_called()

    def test_search_no_embedder(self, opensearch_db, mock_opensearch_client):
        """Test search when no embedder is configured."""
        opensearch_db.embedder = None
        mock_opensearch_client.indices.exists.return_value = True
        opensearch_db._client = mock_opensearch_client

        results = opensearch_db.search("test query")

        assert results == []

    def test_search_with_reranker(self, opensearch_db_with_reranker, mock_opensearch_client, mock_reranker):
        """Test search with reranker."""
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_id": "doc_1",
                        "_score": 0.9,
                        "_source": {"content": "test content", "meta_data": {}, "embedding": [0.1] * TEST_DIMENSION},
                    }
                ]
            }
        }
        opensearch_db_with_reranker._client = mock_opensearch_client

        reranked_docs = [Document(id="reranked_doc", content="reranked content")]
        mock_reranker.rerank.return_value = reranked_docs

        results = opensearch_db_with_reranker.search("test query")

        assert results == reranked_docs
        mock_reranker.rerank.assert_called_once()

    def test_search_exception(self, opensearch_db, mock_opensearch_client, mock_embedder):
        """Test search handles exceptions."""
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.search.side_effect = Exception("Search failed")
        opensearch_db._client = mock_opensearch_client

        results = opensearch_db.search("test query")

        assert results == []

    def test_keyword_search(self, opensearch_db, mock_opensearch_client):
        """Test keyword search."""
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.search.return_value = {"hits": {"hits": []}}
        opensearch_db._client = mock_opensearch_client

        opensearch_db.keyword_search("test query", limit=5)

        call_args = mock_opensearch_client.search.call_args
        search_body = call_args[1]["body"]

        assert "multi_match" in search_body["query"]
        assert search_body["query"]["multi_match"]["query"] == "test query"

    def test_hybrid_search(self, opensearch_db, mock_opensearch_client, mock_embedder):
        """Test hybrid search."""
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.search.return_value = {"hits": {"hits": []}}
        opensearch_db._client = mock_opensearch_client

        opensearch_db.hybrid_search("test query", limit=5)

        call_args = mock_opensearch_client.search.call_args
        search_body = call_args[1]["body"]

        assert "bool" in search_body["query"]
        assert "should" in search_body["query"]["bool"]
        assert len(search_body["query"]["bool"]["should"]) == 2  # KNN + multi_match


class TestOpenSearchFilterOperations:
    """Test filter building operations."""

    def test_build_filter_exact_match(self, opensearch_db):
        """Test building filter for exact match."""
        filters = {"category": "test"}

        conditions = opensearch_db._build_filter_conditions(filters)

        assert len(conditions) == 1
        assert conditions[0] == {"term": {"meta_data.category.keyword": "test"}}

    def test_build_filter_in_operator(self, opensearch_db):
        """Test building filter for $in operator."""
        filters = {"category": {"$in": ["test1", "test2"]}}

        conditions = opensearch_db._build_filter_conditions(filters)

        assert len(conditions) == 1
        assert conditions[0] == {"terms": {"meta_data.category.keyword": ["test1", "test2"]}}

    def test_build_filter_range_operators(self, opensearch_db):
        """Test building filter for range operators."""
        filters = {"score": {"gte": 0.5, "lt": 1.0}}

        conditions = opensearch_db._build_filter_conditions(filters)

        assert len(conditions) == 1
        assert conditions[0] == {"range": {"meta_data.score": {"gte": 0.5, "lt": 1.0}}}

    def test_build_filter_list_values(self, opensearch_db):
        """Test building filter for list values."""
        filters = {"tags": ["tag1", "tag2"]}

        conditions = opensearch_db._build_filter_conditions(filters)

        assert len(conditions) == 1
        assert conditions[0] == {"terms": {"meta_data.tags.keyword": ["tag1", "tag2"]}}

    def test_build_filter_multiple_conditions(self, opensearch_db):
        """Test building multiple filter conditions."""
        filters = {"category": "test", "score": {"gte": 0.5}, "tags": ["tag1", "tag2"]}

        conditions = opensearch_db._build_filter_conditions(filters)

        assert len(conditions) == 3

    def test_scalar_list_and_in_filters_target_the_same_field(self, opensearch_db):
        """All three ways of expressing one exact-match filter must query the same field."""
        scalar = opensearch_db._build_filter_conditions({"cuisine": "Thai Food"})
        as_list = opensearch_db._build_filter_conditions({"cuisine": ["Thai Food"]})
        as_in = opensearch_db._build_filter_conditions({"cuisine": {"$in": ["Thai Food"]}})

        assert scalar[0] == {"term": {"meta_data.cuisine.keyword": "Thai Food"}}
        assert as_list[0] == {"terms": {"meta_data.cuisine.keyword": ["Thai Food"]}}
        assert as_in[0] == {"terms": {"meta_data.cuisine.keyword": ["Thai Food"]}}


class TestOpenSearchUtilityOperations:
    """Test utility operations."""

    def test_get_document_by_id_found(self, opensearch_db, mock_opensearch_client):
        """Test getting document by ID when found."""
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.get.return_value = {
            "found": True,
            "_source": {
                "content": "test content",
                "meta_data": {"category": "test"},
                "embedding": [0.1] * TEST_DIMENSION,
            },
        }
        opensearch_db._client = mock_opensearch_client

        doc = opensearch_db.get_document_by_id("test_id")

        assert doc is not None
        assert doc.content == "test content"
        assert doc.meta_data["search_score"] == 1.0

    def test_get_document_by_id_not_found(self, opensearch_db, mock_opensearch_client):
        """Test getting document by ID when not found."""
        mock_opensearch_client.indices.exists.return_value = True
        opensearch_db._client = mock_opensearch_client

        # Test with NotFoundError
        from opensearchpy import exceptions as opensearch_exceptions

        mock_opensearch_client.get.side_effect = opensearch_exceptions.NotFoundError("Not found", {}, {})

        doc = opensearch_db.get_document_by_id("test_id")

        assert doc is None

    def test_get_document_by_id_index_not_exists(self, opensearch_db, mock_opensearch_client):
        """Test getting document by ID when index doesn't exist."""
        mock_opensearch_client.indices.exists.return_value = False
        opensearch_db._client = mock_opensearch_client

        doc = opensearch_db.get_document_by_id("test_id")

        assert doc is None

    def test_count_documents(self, opensearch_db, mock_opensearch_client):
        """Test counting documents."""
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.count.return_value = {"count": 5}
        opensearch_db._client = mock_opensearch_client

        count = opensearch_db.count()

        assert count == 5
        mock_opensearch_client.count.assert_called_once_with(index=TEST_INDEX_NAME)

    def test_count_documents_index_not_exists(self, opensearch_db, mock_opensearch_client):
        """Test counting documents when index doesn't exist."""
        mock_opensearch_client.indices.exists.return_value = False
        opensearch_db._client = mock_opensearch_client

        count = opensearch_db.count()

        assert count == 0

    def test_count_documents_exception(self, opensearch_db, mock_opensearch_client):
        """Test counting documents handles exceptions."""
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.count.side_effect = Exception("Count failed")
        opensearch_db._client = mock_opensearch_client

        count = opensearch_db.count()

        assert count == 0

    def test_delete_documents_success(self, opensearch_db, mock_opensearch_client):
        """Test deleting documents by IDs."""
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.bulk.return_value = {"errors": False, "items": []}
        opensearch_db._client = mock_opensearch_client

        opensearch_db.delete_documents(["doc1", "doc2"])

        mock_opensearch_client.bulk.assert_called_once()
        call_args = mock_opensearch_client.bulk.call_args
        bulk_data = call_args[1]["body"]

        # Check that it uses delete operations
        assert any("delete" in item for item in bulk_data if isinstance(item, dict))

    def test_delete_documents_empty_list(self, opensearch_db, mock_opensearch_client):
        """Test deleting documents with empty ID list."""
        mock_opensearch_client.indices.exists.return_value = True
        opensearch_db._client = mock_opensearch_client

        opensearch_db.delete_documents([])

        mock_opensearch_client.bulk.assert_not_called()

    def test_delete_documents_index_not_exists(self, opensearch_db, mock_opensearch_client):
        """Test deleting documents when index doesn't exist."""
        mock_opensearch_client.indices.exists.return_value = False
        opensearch_db._client = mock_opensearch_client

        opensearch_db.delete_documents(["doc1"])

        mock_opensearch_client.bulk.assert_not_called()

    def test_delete_all_documents(self, opensearch_db, mock_opensearch_client):
        """Test deleting all documents."""
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.delete_by_query.return_value = {"deleted": 5}
        opensearch_db._client = mock_opensearch_client

        result = opensearch_db.delete()

        assert result is True
        mock_opensearch_client.delete_by_query.assert_called_once()

    def test_delete_all_documents_index_not_exists(self, opensearch_db, mock_opensearch_client):
        """Test deleting all documents when index doesn't exist."""
        mock_opensearch_client.indices.exists.return_value = False
        opensearch_db._client = mock_opensearch_client

        result = opensearch_db.delete()

        assert result is False

    def test_optimize_index(self, opensearch_db, mock_opensearch_client):
        """Test optimizing index."""
        mock_opensearch_client.indices.exists.return_value = True
        opensearch_db._client = mock_opensearch_client

        opensearch_db.optimize()

        mock_opensearch_client.indices.forcemerge.assert_called_once_with(index=TEST_INDEX_NAME, max_num_segments=1)

    def test_optimize_index_not_exists(self, opensearch_db, mock_opensearch_client):
        """Test optimizing index when it doesn't exist."""
        mock_opensearch_client.indices.exists.return_value = False
        opensearch_db._client = mock_opensearch_client

        opensearch_db.optimize()

        mock_opensearch_client.indices.forcemerge.assert_not_called()


class TestOpenSearchBulkSelectionOperations:
    """Deletes and metadata updates must cover every match, not just the first page.

    These previously collected hits from a search with a hardcoded size of 1000 and acted
    on those ids, so content chunked into more than 1000 documents was only partially
    deleted or updated while still reporting success.
    """

    @pytest.fixture(autouse=True)
    def _existing_index(self, opensearch_db, mock_opensearch_client):
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.delete_by_query.return_value = {"deleted": 1005, "failures": []}
        mock_opensearch_client.update_by_query.return_value = {"updated": 1005, "failures": []}
        opensearch_db._client = mock_opensearch_client

    def test_delete_by_name_uses_delete_by_query(self, opensearch_db, mock_opensearch_client):
        assert opensearch_db.delete_by_name("big") is True

        body = mock_opensearch_client.delete_by_query.call_args[1]["body"]
        assert body["query"] == {"term": {"name.keyword": "big"}}
        assert "size" not in body
        mock_opensearch_client.search.assert_not_called()

    def test_delete_by_content_id_uses_delete_by_query(self, opensearch_db, mock_opensearch_client):
        assert opensearch_db.delete_by_content_id("cid-1") is True

        body = mock_opensearch_client.delete_by_query.call_args[1]["body"]
        assert body["query"] == {"term": {"content_id.keyword": "cid-1"}}
        mock_opensearch_client.search.assert_not_called()

    def test_delete_by_metadata_uses_delete_by_query(self, opensearch_db, mock_opensearch_client):
        assert opensearch_db.delete_by_metadata({"tenant": "acme"}) is True

        body = mock_opensearch_client.delete_by_query.call_args[1]["body"]
        assert body["query"] == {"bool": {"filter": [{"term": {"meta_data.tenant.keyword": "acme"}}]}}
        mock_opensearch_client.search.assert_not_called()

    def test_delete_reports_failure_when_shards_fail(self, opensearch_db, mock_opensearch_client):
        """A partial delete must not be reported as success."""
        mock_opensearch_client.delete_by_query.return_value = {
            "deleted": 3,
            "failures": [{"cause": "boom"}],
        }

        assert opensearch_db.delete_by_name("big") is False

    def test_update_metadata_uses_update_by_query(self, opensearch_db, mock_opensearch_client):
        opensearch_db.update_metadata("cid-1", {"reviewed": "yes"})

        body = mock_opensearch_client.update_by_query.call_args[1]["body"]
        assert body["query"] == {"term": {"content_id.keyword": "cid-1"}}
        assert body["script"]["params"] == {"metadata": {"reviewed": "yes"}}
        assert "size" not in body
        mock_opensearch_client.search.assert_not_called()

    def test_update_metadata_raises_when_shards_fail(self, opensearch_db, mock_opensearch_client):
        """A partial update must surface as an error, not pass silently."""
        mock_opensearch_client.update_by_query.return_value = {
            "updated": 2,
            "failures": [{"cause": "boom"}],
        }

        with pytest.raises(Exception, match="failure"):
            opensearch_db.update_metadata("cid-1", {"reviewed": "yes"})


class TestOpenSearchDocumentFromHit:
    """Test document creation from search hits."""

    def test_create_document_from_hit_complete(self, opensearch_db):
        """Test creating document from complete hit."""
        hit = {
            "_id": "test_id",
            "_score": 0.95,
            "_source": {
                "content": "test content",
                "name": "test_name",
                "meta_data": {"category": "test"},
                "embedding": [0.1] * TEST_DIMENSION,
                "usage": {"tokens": 10},
                "reranking_score": 0.8,
            },
        }

        doc = opensearch_db._create_document_from_hit(hit)

        assert doc.id == "test_id"
        assert doc.content == "test content"
        assert doc.name == "test_name"
        assert doc.meta_data["category"] == "test"
        assert doc.meta_data["search_score"] == 0.95
        assert doc.embedding == [0.1] * TEST_DIMENSION
        assert doc.usage == {"tokens": 10}
        assert doc.reranking_score == 0.8

    def test_create_document_from_hit_minimal(self, opensearch_db):
        """Test creating document from minimal hit."""
        hit = {"_id": "test_id", "_score": 0.95, "_source": {"content": "test content"}}

        doc = opensearch_db._create_document_from_hit(hit)

        assert doc.id == "test_id"
        assert doc.content == "test content"
        assert doc.name is None
        assert doc.meta_data["search_score"] == 0.95
        assert doc.embedding is None
        assert doc.usage is None
        assert doc.reranking_score is None


class TestOpenSearchEdgeCases:
    """Test edge cases and error conditions."""

    def test_large_document_handling(self, opensearch_db, mock_opensearch_client, mock_embedder):
        """Test handling of large documents."""
        large_content = "x" * 10000  # Large content
        doc = Document(id="large_doc", content=large_content, embedding=[0.1] * TEST_DIMENSION)

        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.bulk.return_value = {"errors": False, "items": []}
        opensearch_db._client = mock_opensearch_client

        opensearch_db.insert("test_hash", [doc])

        mock_opensearch_client.bulk.assert_called_once()

    def test_unicode_content_handling(self, opensearch_db, mock_opensearch_client):
        """Test handling of unicode content."""
        unicode_content = "Test content with unicode: 你好世界 🌍"
        doc = Document(id="unicode_doc", content=unicode_content, embedding=[0.1] * TEST_DIMENSION)

        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.bulk.return_value = {"errors": False, "items": []}
        opensearch_db._client = mock_opensearch_client

        opensearch_db.insert("test_hash", [doc])

        mock_opensearch_client.bulk.assert_called_once()

    def test_empty_query_search(self, opensearch_db, mock_opensearch_client, mock_embedder):
        """Test search with empty query."""
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.search.return_value = {"hits": {"hits": []}}
        opensearch_db._client = mock_opensearch_client

        results = opensearch_db.search("", limit=5)

        assert results == []
        mock_embedder.get_embedding_and_usage.assert_called_once_with("")

    def test_very_large_limit(self, opensearch_db, mock_opensearch_client, mock_embedder):
        """Test search with very large limit."""
        mock_opensearch_client.indices.exists.return_value = True
        mock_opensearch_client.search.return_value = {"hits": {"hits": []}}
        opensearch_db._client = mock_opensearch_client

        results = opensearch_db.search("test", limit=10000)

        assert results == []
        call_args = mock_opensearch_client.search.call_args
        assert call_args[1]["body"]["size"] == 10000


class TestOpenSearchBatchEmbedding:
    """Test batch embedding functionality."""

    @pytest.mark.asyncio
    async def test_async_embed_documents_with_batch_embedder(self):
        """Test batch embedding when embedder supports it."""
        # Create a mock embedder with batch support
        mock_embedder = Mock(spec=Embedder)
        mock_embedder.enable_batch = True
        mock_embedder.async_get_embeddings_batch_and_usage = AsyncMock(
            return_value=([[0.1] * TEST_DIMENSION, [0.2] * TEST_DIMENSION], [{"tokens": 10}, {"tokens": 12}])
        )

        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
        ):
            db = OpenSearch(index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, embedder=mock_embedder)

            # Create documents without embeddings
            docs = [
                Document(id="doc1", content="content 1"),
                Document(id="doc2", content="content 2"),
            ]

            # Call batch embedding
            await db._async_embed_documents(docs)

            # Verify batch embedding was called
            mock_embedder.async_get_embeddings_batch_and_usage.assert_called_once_with(["content 1", "content 2"])

            # Verify embeddings were assigned
            assert docs[0].embedding == [0.1] * TEST_DIMENSION
            assert docs[0].usage == {"tokens": 10}
            assert docs[1].embedding == [0.2] * TEST_DIMENSION
            assert docs[1].usage == {"tokens": 12}

    @pytest.mark.asyncio
    async def test_async_embed_documents_without_batch_embedder(self):
        """Test individual embedding when batch is not supported."""
        # Create a mock embedder without batch support
        mock_embedder = Mock(spec=Embedder)
        mock_embedder.enable_batch = False

        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
        ):
            db = OpenSearch(index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, embedder=mock_embedder)

            # Create mock documents with async_embed method
            doc1 = Mock(spec=Document)
            doc1.embedding = None
            doc1.async_embed = AsyncMock()

            doc2 = Mock(spec=Document)
            doc2.embedding = None
            doc2.async_embed = AsyncMock()

            docs = [doc1, doc2]

            # Call batch embedding
            await db._async_embed_documents(docs)

            # Verify individual embedding was called for each doc
            doc1.async_embed.assert_called_once_with(embedder=mock_embedder)
            doc2.async_embed.assert_called_once_with(embedder=mock_embedder)

    @pytest.mark.asyncio
    async def test_async_embed_documents_skip_already_embedded(self):
        """Test that documents with embeddings are skipped."""
        # Create a mock embedder with batch support
        mock_embedder = Mock(spec=Embedder)
        mock_embedder.enable_batch = True
        mock_embedder.async_get_embeddings_batch_and_usage = AsyncMock(
            return_value=([[0.2] * TEST_DIMENSION], [{"tokens": 12}])
        )

        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
        ):
            db = OpenSearch(index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, embedder=mock_embedder)

            # Create documents - one with embedding, one without
            docs = [
                Document(id="doc1", content="content 1", embedding=[0.1] * TEST_DIMENSION),
                Document(id="doc2", content="content 2"),
            ]

            # Call batch embedding
            await db._async_embed_documents(docs)

            # Verify batch embedding was called only for doc without embedding
            mock_embedder.async_get_embeddings_batch_and_usage.assert_called_once_with(["content 2"])

            # Verify embeddings
            assert docs[0].embedding == [0.1] * TEST_DIMENSION  # Original embedding preserved
            assert docs[1].embedding == [0.2] * TEST_DIMENSION  # New embedding assigned

    @pytest.mark.asyncio
    async def test_async_embed_documents_rate_limit_error(self):
        """Test that rate limit errors are raised and not caught."""
        # Create a mock embedder with batch support
        mock_embedder = Mock(spec=Embedder)
        mock_embedder.enable_batch = True
        mock_embedder.async_get_embeddings_batch_and_usage = AsyncMock(
            side_effect=Exception("Rate limit exceeded: 429 Too Many Requests")
        )

        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
        ):
            db = OpenSearch(index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, embedder=mock_embedder)

            docs = [Document(id="doc1", content="content 1")]

            # Verify that rate limit error is raised
            with pytest.raises(Exception, match="Rate limit"):
                await db._async_embed_documents(docs)

    @pytest.mark.asyncio
    async def test_async_embed_documents_fallback_on_error(self):
        """Test fallback to individual embedding on non-rate-limit errors."""
        # Create a mock embedder with batch support that fails
        mock_embedder = Mock(spec=Embedder)
        mock_embedder.enable_batch = True
        mock_embedder.async_get_embeddings_batch_and_usage = AsyncMock(side_effect=Exception("Some other error"))

        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch("agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient"),
        ):
            db = OpenSearch(index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, embedder=mock_embedder)

            # Create mock documents with async_embed method
            doc1 = Mock(spec=Document)
            doc1.embedding = None
            doc1.async_embed = AsyncMock()

            docs = [doc1]

            # Call batch embedding
            await db._async_embed_documents(docs)

            # Verify fallback to individual embedding
            doc1.async_embed.assert_called_once_with(embedder=mock_embedder)

    @pytest.mark.asyncio
    async def test_async_insert_uses_batch_embedding(self, mock_async_opensearch_client):
        """Test that async_insert uses batch embedding."""
        # Create a mock embedder with batch support
        mock_embedder = Mock(spec=Embedder)
        mock_embedder.enable_batch = True
        mock_embedder.async_get_embeddings_batch_and_usage = AsyncMock(
            return_value=([[0.1] * TEST_DIMENSION], [{"tokens": 10}])
        )

        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch(
                "agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient", return_value=mock_async_opensearch_client
            ),
        ):
            db = OpenSearch(index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, embedder=mock_embedder)
            db._async_client = mock_async_opensearch_client

            docs = [Document(id="doc1", content="content 1")]

            # Call async insert
            await db.async_insert("test_hash", docs)

            # Verify batch embedding was called
            mock_embedder.async_get_embeddings_batch_and_usage.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_upsert_uses_batch_embedding(self, mock_async_opensearch_client):
        """Test that async_upsert uses batch embedding."""
        # Create a mock embedder with batch support
        mock_embedder = Mock(spec=Embedder)
        mock_embedder.enable_batch = True
        mock_embedder.async_get_embeddings_batch_and_usage = AsyncMock(
            return_value=([[0.1] * TEST_DIMENSION], [{"tokens": 10}])
        )

        with (
            patch("agno.vectordb.opensearch.opensearch.OpenSearchClient"),
            patch(
                "agno.vectordb.opensearch.opensearch.AsyncOpenSearchClient", return_value=mock_async_opensearch_client
            ),
        ):
            db = OpenSearch(index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, embedder=mock_embedder)
            db._async_client = mock_async_opensearch_client

            docs = [Document(id="doc1", content="content 1")]

            # Call async upsert
            await db.async_upsert("test_hash", docs)

            # Verify batch embedding was called
            mock_embedder.async_get_embeddings_batch_and_usage.assert_called_once()
