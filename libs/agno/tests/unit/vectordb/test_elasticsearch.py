from typing import List
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agno.knowledge.document import Document
from agno.knowledge.embedder.base import Embedder
from agno.knowledge.reranker.base import Reranker
from agno.vectordb.distance import Distance
from agno.vectordb.elasticsearch import Elasticsearch, HybridStrategy, Similarity
from agno.vectordb.search import SearchType

# Test constants
TEST_INDEX_NAME = "test_index"
TEST_DIMENSION = 768

CLIENT_PATH = "agno.vectordb.elasticsearch.elasticsearch.ElasticsearchClient"
ASYNC_CLIENT_PATH = "agno.vectordb.elasticsearch.elasticsearch.AsyncElasticsearchClient"


@pytest.fixture
def mock_embedder():
    """Mock embedder fixture."""
    embedder = Mock(spec=Embedder)
    embedder.dimensions = TEST_DIMENSION
    embedder.enable_batch = False
    embedder.get_embedding_and_usage.return_value = ([0.1] * TEST_DIMENSION, {"tokens": 10})

    # The async read path awaits this, so a plain Mock attribute would not be awaitable.
    async def _async_get_embedding_and_usage(text: str):
        return [0.1] * TEST_DIMENSION, {"tokens": 10}

    embedder.async_get_embedding_and_usage = _async_get_embedding_and_usage
    return embedder


@pytest.fixture
def mock_reranker():
    """Mock reranker fixture."""
    reranker = Mock(spec=Reranker)
    reranker.rerank.return_value = []
    return reranker


@pytest.fixture
def mock_es_client():
    """Mock Elasticsearch client."""
    client = Mock()
    client.ping.return_value = True
    client.indices.exists.return_value = False
    client.indices.create.return_value = {"acknowledged": True}
    client.indices.delete.return_value = {"acknowledged": True}
    client.indices.get_mapping.return_value = {TEST_INDEX_NAME: {"mappings": {"properties": {}}}}
    client.indices.put_mapping.return_value = {"acknowledged": True}
    client.exists.return_value = False
    client.search.return_value = {"hits": {"hits": [], "total": {"value": 0}}}
    client.bulk.return_value = {"errors": False, "items": []}
    client.get.return_value = {"found": False}
    client.count.return_value = {"count": 0}
    client.delete_by_query.return_value = {"deleted": 0}
    client.update_by_query.return_value = {"updated": 0}
    client.indices.forcemerge.return_value = {"acknowledged": True}
    return client


@pytest.fixture
def mock_async_es_client():
    """Mock async Elasticsearch client."""
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
def es_db(mock_embedder):
    """Elasticsearch instance with mock embedder."""
    with patch(CLIENT_PATH), patch(ASYNC_CLIENT_PATH):
        return Elasticsearch(index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, embedder=mock_embedder)


@pytest.fixture
def es_db_with_reranker(mock_embedder, mock_reranker):
    """Elasticsearch instance with mock embedder and reranker."""
    with patch(CLIENT_PATH), patch(ASYNC_CLIENT_PATH):
        return Elasticsearch(
            index_name=TEST_INDEX_NAME,
            dimension=TEST_DIMENSION,
            embedder=mock_embedder,
            reranker=mock_reranker,
        )


@pytest.fixture
def create_test_documents():
    """Create test documents."""

    def _create_documents(count: int = 3) -> List[Document]:
        documents = []
        for i in range(count):
            documents.append(
                Document(
                    id=f"doc_{i}",
                    content=f"Test content {i}",
                    name=f"test_doc_{i}",
                    meta_data={"category": f"category_{i}", "index": i},
                    embedding=[0.1 + i * 0.1] * TEST_DIMENSION,
                )
            )
        return documents

    return _create_documents


class TestElasticsearchInitialization:
    """Test Elasticsearch initialization."""

    def test_init_with_default_embedder(self):
        """Test initialization with default embedder."""
        with (
            patch(CLIENT_PATH),
            patch(ASYNC_CLIENT_PATH),
            patch("agno.knowledge.embedder.openai.OpenAIEmbedder") as mock_openai,
        ):
            db = Elasticsearch(index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION)

            assert db.index_name == TEST_INDEX_NAME
            assert db.dimension == TEST_DIMENSION
            assert db.similarity == Similarity.cosine
            mock_openai.assert_called_once()

    def test_index_name_is_the_only_required_argument(self, mock_embedder):
        """The common case must need nothing but an index name."""
        with patch(CLIENT_PATH), patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(index_name=TEST_INDEX_NAME, embedder=mock_embedder)

            assert db.hosts == ["http://localhost:9200"]
            assert db.dimension == TEST_DIMENSION
            assert db.mappings["properties"]["embedding"]["dims"] == TEST_DIMENSION

    def test_url_accepts_a_list_for_multi_node_clusters(self, mock_embedder):
        """A list of urls must be passed through to the client as multiple hosts."""
        urls = ["https://n1.example.com:9243", "https://n2.example.com:9243"]
        with patch(CLIENT_PATH) as mock_client, patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(index_name=TEST_INDEX_NAME, url=urls, embedder=mock_embedder)
            _ = db.client

            assert db.hosts == urls
            assert mock_client.call_args[1]["hosts"] == urls

    def test_explicit_dimension_overrides_the_embedder(self, mock_embedder):
        """An explicit dimension must win over the embedder's dimensions."""
        with patch(CLIENT_PATH), patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(index_name=TEST_INDEX_NAME, dimension=32, embedder=mock_embedder)

            assert db.dimension == 32
            assert db.mappings["properties"]["embedding"]["dims"] == 32

    def test_undeterminable_dimension_raises(self):
        """A dimensionless embedder with no explicit dimension must fail loudly."""
        embedder = Mock(spec=Embedder)
        embedder.dimensions = None

        with (
            patch(CLIENT_PATH),
            patch(ASYNC_CLIENT_PATH),
            pytest.raises(ValueError, match="dimension"),
        ):
            Elasticsearch(index_name=TEST_INDEX_NAME, embedder=embedder)

    def test_empty_url_list_raises(self, mock_embedder):
        """An empty url list is a configuration error, not a silent default."""
        with pytest.raises(ValueError, match="url"):
            Elasticsearch(index_name=TEST_INDEX_NAME, url=[], embedder=mock_embedder)

    def test_empty_url_list_is_allowed_with_a_cloud_id(self, mock_embedder):
        """cloud_id is an alternative to a url, not a companion to one."""
        with patch(CLIENT_PATH) as mock_client, patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(index_name=TEST_INDEX_NAME, url=[], cloud_id="deploy:abc123", embedder=mock_embedder)
            _ = db.client

            kwargs = mock_client.call_args[1]
            assert kwargs["cloud_id"] == "deploy:abc123"
            # hosts and cloud_id are mutually exclusive in the client
            assert "hosts" not in kwargs

    def test_extra_kwargs_are_forwarded_to_the_client(self, mock_embedder):
        """Unrecognised kwargs must reach the underlying elasticsearch clients."""
        with patch(CLIENT_PATH) as mock_client, patch(ASYNC_CLIENT_PATH) as mock_async_client:
            db = Elasticsearch(index_name=TEST_INDEX_NAME, embedder=mock_embedder, http_compress=True)
            _ = db.client
            _ = db.async_client

            assert mock_client.call_args[1]["http_compress"] is True
            assert mock_async_client.call_args[1]["http_compress"] is True

    def test_optional_auth_is_omitted_rather_than_passed_as_none(self, mock_embedder):
        """The client rejects api_key=None, so absent auth must not be forwarded at all."""
        with patch(CLIENT_PATH) as mock_client, patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(index_name=TEST_INDEX_NAME, embedder=mock_embedder)
            _ = db.client

            kwargs = mock_client.call_args[1]
            assert "api_key" not in kwargs
            assert "basic_auth" not in kwargs
            assert "ca_certs" not in kwargs

    def test_auth_arguments_are_forwarded_when_given(self, mock_embedder):
        """Supplied credentials must reach the client."""
        with patch(CLIENT_PATH) as mock_client, patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(
                index_name=TEST_INDEX_NAME,
                embedder=mock_embedder,
                api_key="secret-key",
                basic_auth=("user", "pass"),
                ca_certs="/tmp/ca.crt",
            )
            _ = db.client

            kwargs = mock_client.call_args[1]
            assert kwargs["api_key"] == "secret-key"
            assert kwargs["basic_auth"] == ("user", "pass")
            assert kwargs["ca_certs"] == "/tmp/ca.crt"

    @pytest.mark.parametrize(
        "distance,expected",
        [
            (Distance.cosine, Similarity.cosine),
            (Distance.l2, Similarity.l2_norm),
            (Distance.max_inner_product, Similarity.max_inner_product),
        ],
    )
    def test_distance_maps_to_similarity(self, mock_embedder, distance, expected):
        """Each Distance must select the matching Elasticsearch similarity."""
        with patch(CLIENT_PATH), patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(index_name=TEST_INDEX_NAME, embedder=mock_embedder, distance=distance)

            assert db.similarity == expected
            assert db.mappings["properties"]["embedding"]["similarity"] == expected

    def test_explicit_similarity_overrides_distance(self, mock_embedder):
        """similarity is the more specific knob and must win over distance."""
        with patch(CLIENT_PATH), patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(
                index_name=TEST_INDEX_NAME,
                embedder=mock_embedder,
                distance=Distance.cosine,
                similarity=Similarity.dot_product,
            )

            assert db.similarity == Similarity.dot_product

    def test_base_class_attributes_are_initialized(self, mock_embedder):
        """VectorDb base attributes must be set so the db can be registered and named."""
        with patch(CLIENT_PATH), patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, embedder=mock_embedder)

            assert db.id is not None
            assert db.name == "Elasticsearch"
            assert db.description is None

    def test_explicit_id_and_name_are_preserved(self, mock_embedder):
        """Explicitly supplied id/name must override the generated defaults."""
        with patch(CLIENT_PATH), patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(
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

    def test_get_supported_search_types(self, es_db):
        """All three search types must be reported as supported."""
        assert es_db.get_supported_search_types() == [
            SearchType.vector,
            SearchType.keyword,
            SearchType.hybrid,
        ]

    def test_create_mappings(self, es_db):
        """The dense_vector field must be indexed for kNN with the right dims."""
        mappings = es_db._create_mappings()
        embedding = mappings["properties"]["embedding"]

        assert embedding["type"] == "dense_vector"
        assert embedding["dims"] == TEST_DIMENSION
        assert embedding["index"] is True
        assert embedding["similarity"] == Similarity.cosine
        # The owner must be exact-match, never analyzed
        assert mappings["properties"]["user_id"]["type"] == "keyword"
        assert mappings["properties"]["content_hash"]["type"] == "keyword"


class TestElasticsearchClient:
    """Test client creation and management."""

    def test_client_property(self, es_db, mock_es_client):
        """Client must be created once and cached."""
        with patch(CLIENT_PATH, return_value=mock_es_client):
            client1 = es_db.client
            assert client1 == mock_es_client
            mock_es_client.ping.assert_called_once()

            client2 = es_db.client
            assert client1 is client2

    def test_client_creation_failure(self, es_db):
        """A connection failure must propagate rather than yield a broken client."""
        with patch(CLIENT_PATH) as mock_class:
            mock_class.side_effect = Exception("Connection failed")

            with pytest.raises(Exception, match="Connection failed"):
                _ = es_db.client

    def test_async_client_property(self, es_db, mock_async_es_client):
        """Async client must be created once and cached."""
        with patch(ASYNC_CLIENT_PATH, return_value=mock_async_es_client):
            client1 = es_db.async_client
            assert client1 == mock_async_es_client

            client2 = es_db.async_client
            assert client1 is client2

    def test_async_client_forwards_connection_settings(self, es_db, mock_async_es_client):
        """Async client must honour the configured timeout and retry settings."""
        with patch(ASYNC_CLIENT_PATH, return_value=mock_async_es_client) as mock_class:
            _ = es_db.async_client

            kwargs = mock_class.call_args[1]
            assert kwargs["request_timeout"] == es_db.timeout
            assert kwargs["max_retries"] == es_db.max_retries
            assert kwargs["retry_on_timeout"] == es_db.retry_on_timeout

    def test_close_releases_sync_client(self, es_db, mock_es_client):
        """close() must close and clear the cached sync client."""
        es_db._client = mock_es_client

        es_db.close()

        mock_es_client.close.assert_called_once()
        assert es_db._client is None

    @pytest.mark.asyncio
    async def test_async_close_releases_async_client(self, es_db, mock_async_es_client):
        """async_close() must close the aiohttp-backed client so it is not leaked."""
        es_db._async_client = mock_async_es_client

        await es_db.async_close()

        mock_async_es_client.close.assert_awaited_once()
        assert es_db._async_client is None

    @pytest.mark.asyncio
    async def test_async_close_is_safe_without_client(self, es_db):
        """async_close() must be a no-op when no client was ever created."""
        es_db._async_client = None

        await es_db.async_close()

        assert es_db._async_client is None

    @pytest.mark.asyncio
    async def test_async_close_also_closes_the_sync_client(self, es_db, mock_es_client, mock_async_es_client):
        """An async-only caller still builds a sync client, so async_close must release both.

        The owner gate inspects the live mapping synchronously and async_search runs the
        sync client on a worker thread, so the documented await vector_db.async_close()
        would otherwise leave that transport open.
        """
        es_db._client = mock_es_client
        es_db._async_client = mock_async_es_client

        await es_db.async_close()

        mock_async_es_client.close.assert_awaited_once()
        mock_es_client.close.assert_called_once()
        assert es_db._client is None
        assert es_db._async_client is None

    @pytest.mark.asyncio
    async def test_async_close_does_not_block_the_event_loop(self, es_db, mock_es_client, mock_async_es_client):
        """Closing the sync transport is a blocking teardown and belongs on a worker thread."""
        import threading

        seen = {}
        mock_es_client.close.side_effect = lambda: seen.setdefault("thread", threading.get_ident())
        es_db._client = mock_es_client
        es_db._async_client = mock_async_es_client

        await es_db.async_close()

        assert seen["thread"] != threading.get_ident()

    @pytest.mark.asyncio
    async def test_async_close_releases_the_sync_client_even_with_no_async_client(self, es_db, mock_es_client):
        """A caller who only ever triggered the sync half still gets it closed."""
        es_db._client = mock_es_client
        es_db._async_client = None

        await es_db.async_close()

        mock_es_client.close.assert_called_once()
        assert es_db._client is None

    @pytest.mark.asyncio
    async def test_async_close_is_idempotent(self, es_db, mock_es_client, mock_async_es_client):
        """Calling it twice must not raise or double-close."""
        es_db._client = mock_es_client
        es_db._async_client = mock_async_es_client

        await es_db.async_close()
        await es_db.async_close()

        mock_es_client.close.assert_called_once()
        mock_async_es_client.close.assert_awaited_once()

    def test_async_client_creation_failure(self, es_db):
        """An async client failure must propagate."""
        with patch(ASYNC_CLIENT_PATH) as mock_class:
            mock_class.side_effect = Exception("Connection failed")

            with pytest.raises(Exception, match="Connection failed"):
                _ = es_db.async_client


class TestElasticsearchIndexOperations:
    """Test index lifecycle operations."""

    def test_exists_true(self, es_db, mock_es_client):
        """exists() must report a live index."""
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client

        assert es_db.exists() is True
        mock_es_client.indices.exists.assert_called_once_with(index=TEST_INDEX_NAME)

    def test_exists_false(self, es_db, mock_es_client):
        """exists() must report a missing index."""
        mock_es_client.indices.exists.return_value = False
        es_db._client = mock_es_client

        assert es_db.exists() is False

    def test_exists_swallows_errors(self, es_db, mock_es_client):
        """A transport failure must read as 'not there', never raise out of exists()."""
        mock_es_client.indices.exists.side_effect = Exception("boom")
        es_db._client = mock_es_client

        assert es_db.exists() is False

    def test_create_index_when_missing(self, es_db, mock_es_client):
        """create() must build the index with the configured mappings and settings."""
        mock_es_client.indices.exists.return_value = False
        es_db._client = mock_es_client

        es_db.create()

        mock_es_client.indices.create.assert_called_once_with(
            index=TEST_INDEX_NAME, mappings=es_db.mappings, settings=es_db.settings
        )

    def test_create_is_a_noop_when_index_exists(self, es_db, mock_es_client):
        """create() must not recreate an existing index."""
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client

        es_db.create()

        mock_es_client.indices.create.assert_not_called()

    def test_drop_deletes_existing_index(self, es_db, mock_es_client):
        """drop() must delete the index when it exists."""
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client

        es_db.drop()

        mock_es_client.indices.delete.assert_called_once_with(index=TEST_INDEX_NAME)

    def test_drop_is_a_noop_when_index_missing(self, es_db, mock_es_client):
        """drop() must not call delete for an index that isn't there."""
        mock_es_client.indices.exists.return_value = False
        es_db._client = mock_es_client

        es_db.drop()

        mock_es_client.indices.delete.assert_not_called()

    def test_drop_reresolves_the_owner_mapping(self, es_db, mock_es_client):
        """A recreated index gets a fresh mapping, so the cached answer must be dropped."""
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        es_db.drop()

        assert es_db._owner_field_exact is None

    @pytest.mark.asyncio
    async def test_async_create_and_drop(self, es_db, mock_async_es_client):
        """The async lifecycle must mirror the sync one."""
        es_db._async_client = mock_async_es_client

        mock_async_es_client.indices.exists.return_value = False
        await es_db.async_create()
        mock_async_es_client.indices.create.assert_awaited_once()

        mock_async_es_client.indices.exists.return_value = True
        await es_db.async_drop()
        mock_async_es_client.indices.delete.assert_awaited_once_with(index=TEST_INDEX_NAME)

    def test_optimize_forcemerges(self, es_db, mock_es_client):
        """optimize() must force-merge down to a single segment."""
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client

        es_db.optimize()

        mock_es_client.indices.forcemerge.assert_called_once_with(index=TEST_INDEX_NAME, max_num_segments=1)

    def test_count_returns_zero_for_missing_index(self, es_db, mock_es_client):
        """count() must not fail on a missing index."""
        mock_es_client.indices.exists.return_value = False
        es_db._client = mock_es_client

        assert es_db.count() == 0

    def test_count_returns_document_total(self, es_db, mock_es_client):
        """count() must report the index document total."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.count.return_value = {"count": 42}
        es_db._client = mock_es_client

        assert es_db.count() == 42


class TestElasticsearchDocumentPreparation:
    """Test document preparation and id derivation."""

    def test_build_index_document_promotes_content_hash(self, es_db, create_test_documents):
        """content_hash must be lifted to a top-level keyword so it can be matched exactly."""
        doc = create_test_documents(1)[0]
        doc.meta_data["content_hash"] = "abc123"

        index_doc = es_db._build_index_document(doc)

        assert index_doc["content_hash"] == "abc123"
        assert index_doc["content"] == doc.content
        assert index_doc["embedding"] == doc.embedding

    def test_build_index_document_omits_owner_for_shared(self, es_db, create_test_documents):
        """The shared bucket is the absence of the field, not an empty value."""
        doc = create_test_documents(1)[0]

        index_doc = es_db._build_index_document(doc, user_id=None)

        assert "user_id" not in index_doc

    def test_build_index_document_stamps_the_owner(self, es_db, create_test_documents):
        """A scoped write must carry its owner."""
        doc = create_test_documents(1)[0]

        index_doc = es_db._build_index_document(doc, user_id="alice")

        assert index_doc["user_id"] == "alice"

    def test_doc_id_is_stable_for_the_same_document(self, es_db, create_test_documents):
        """Re-indexing the same document must land on the same _id, so it upserts in place."""
        doc = create_test_documents(1)[0]
        doc.meta_data["content_hash"] = "hash-1"

        assert es_db._build_doc_id(doc) == es_db._build_doc_id(doc)

    def test_doc_id_differs_per_owner(self, es_db, create_test_documents):
        """Two users ingesting the same bytes must not overwrite each other."""
        doc = create_test_documents(1)[0]
        doc.meta_data["content_hash"] = "hash-1"

        alice = es_db._build_doc_id(doc, user_id="alice")
        bob = es_db._build_doc_id(doc, user_id="bob")
        shared = es_db._build_doc_id(doc, user_id=None)

        assert len({alice, bob, shared}) == 3

    def test_validate_embedding_dimensions_rejects_mismatch(self, es_db, create_test_documents):
        """A wrong-width vector must fail before it reaches the cluster."""
        doc = create_test_documents(1)[0]
        doc.embedding = [0.1] * (TEST_DIMENSION + 1)

        with pytest.raises(ValueError, match="dimension mismatch"):
            es_db._validate_embedding_dimensions(doc)

    def test_apply_content_hash_and_filters(self, es_db, create_test_documents):
        """Filters must be merged into metadata so filtered search can match them."""
        docs = create_test_documents(2)

        es_db._apply_content_hash_and_filters(docs, "hash-9", {"team": "eng"})

        for doc in docs:
            assert doc.meta_data["content_hash"] == "hash-9"
            assert doc.meta_data["team"] == "eng"

    def test_create_document_from_hit_records_the_score(self, es_db):
        """The search score must be preserved on the returned document."""
        hit = {
            "_id": "abc",
            "_score": 0.75,
            "_source": {"content": "hello", "name": "n", "meta_data": {"team": "eng"}},
        }

        doc = es_db._create_document_from_hit(hit)

        assert doc.id == "abc"
        assert doc.content == "hello"
        assert doc.meta_data["search_score"] == 0.75
        assert doc.meta_data["team"] == "eng"

    def test_create_document_from_hit_tolerates_a_null_score(self, es_db):
        """An rrf hit carries no _score, which must not blow up document construction."""
        hit = {"_id": "abc", "_score": None, "_source": {"content": "hello"}}

        doc = es_db._create_document_from_hit(hit)

        assert doc.meta_data["search_score"] is None


class TestElasticsearchSearch:
    """Test the three search paths and how they build their queries."""

    def test_vector_query_uses_a_knn_clause(self, es_db):
        """A vector search must go through the native knn clause."""
        body = es_db._build_vector_query("q", 5, None, None)

        assert body["size"] == 5
        assert body["knn"]["field"] == "embedding"
        assert body["knn"]["k"] == 5
        assert "filter" not in body["knn"]

    def test_num_candidates_defaults_above_the_limit(self, es_db):
        """num_candidates must never fall below k, which the cluster rejects."""
        body = es_db._build_vector_query("q", 5, None, None)

        assert body["knn"]["num_candidates"] >= 5
        assert body["knn"]["num_candidates"] == 50

    def test_num_candidates_scales_with_a_large_limit(self, es_db):
        """A big limit must widen the candidate pool rather than stay at the floor."""
        body = es_db._build_vector_query("q", 100, None, None)

        assert body["knn"]["num_candidates"] == 1000

    def test_explicit_num_candidates_is_honoured(self, mock_embedder):
        """An explicit num_candidates must be used, but never below k."""
        with patch(CLIENT_PATH), patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(
                index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, embedder=mock_embedder, num_candidates=7
            )

        assert db._build_vector_query("q", 3, None, None)["knn"]["num_candidates"] == 7
        # Below k is invalid, so the limit wins
        assert db._build_vector_query("q", 20, None, None)["knn"]["num_candidates"] == 20

    def test_vector_query_prefilters_inside_the_knn_clause(self, es_db):
        """Post-filtering would drop every hit when the neighbours belong to another owner."""
        body = es_db._build_vector_query("q", 5, None, "alice")

        assert "filter" in body["knn"]
        assert body["knn"]["filter"] == [es_db._user_scope_filter("alice")]

    def test_vector_query_combines_filters_and_scope(self, es_db):
        """Metadata filters and the owner scope must both be applied."""
        body = es_db._build_vector_query("q", 5, {"team": "eng"}, "alice")

        conditions = body["knn"]["filter"]
        assert {"term": {"meta_data.team.keyword": "eng"}} in conditions
        assert es_db._user_scope_filter("alice") in conditions

    def test_keyword_query_matches_content_and_name(self, es_db):
        """A keyword search must span both text fields."""
        body = es_db._build_keyword_query("q", 5, None, None)

        assert body["query"]["multi_match"]["fields"] == ["content", "name"]
        assert body["size"] == 5

    def test_keyword_query_applies_the_scope_as_a_filter(self, es_db):
        """A scoped keyword search must AND the owner scope in."""
        body = es_db._build_keyword_query("q", 5, None, "alice")

        assert es_db._user_scope_filter("alice") in body["query"]["bool"]["filter"]

    def test_hybrid_boost_weights_both_halves(self, es_db):
        """The default hybrid strategy must sum a boosted knn and multi_match."""
        body = es_db._build_hybrid_query("q", 5, None, None)

        assert body["knn"]["boost"] == 0.7
        assert body["query"]["multi_match"]["boost"] == 0.3

    def test_hybrid_boost_scopes_both_halves(self, es_db):
        """A scoped hybrid search must filter the vector and the keyword half alike."""
        body = es_db._build_hybrid_query("q", 5, None, "alice")
        scope = es_db._user_scope_filter("alice")

        assert scope in body["knn"]["filter"]
        assert scope in body["query"]["bool"]["filter"]

    def test_hybrid_rrf_builds_a_retriever(self, mock_embedder):
        """The rrf strategy must fuse the two rankings instead of summing scores."""
        with patch(CLIENT_PATH), patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(
                index_name=TEST_INDEX_NAME,
                dimension=TEST_DIMENSION,
                embedder=mock_embedder,
                hybrid_strategy=HybridStrategy.rrf,
            )

        body = db._build_hybrid_query("q", 5, None, None)

        retrievers = body["retriever"]["rrf"]["retrievers"]
        assert any("knn" in r for r in retrievers)
        assert any("standard" in r for r in retrievers)
        # rrf fuses ranks, so the boosts must not be applied
        assert "boost" not in body["knn"] if "knn" in body else True

    def test_search_dispatches_on_search_type(self, mock_embedder):
        """The configured search type must select the matching search method."""
        with patch(CLIENT_PATH), patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(
                index_name=TEST_INDEX_NAME,
                dimension=TEST_DIMENSION,
                embedder=mock_embedder,
                search_type=SearchType.keyword,
            )
        db._owner_field_exact = True

        with patch.object(db, "keyword_search", return_value=[]) as mock_keyword:
            db.search("q", limit=3)

        mock_keyword.assert_called_once_with("q", 3, None, None)

    def test_search_returns_documents_from_hits(self, es_db, mock_es_client):
        """A search must map hits onto Documents."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.search.return_value = {
            "hits": {
                "hits": [
                    {"_id": "1", "_score": 0.9, "_source": {"content": "a", "meta_data": {}}},
                    {"_id": "2", "_score": 0.8, "_source": {"content": "b", "meta_data": {}}},
                ]
            }
        }
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        results = es_db.search("q", limit=2)

        assert [d.content for d in results] == ["a", "b"]

    def test_search_returns_empty_for_missing_index(self, es_db, mock_es_client):
        """Searching a missing index must return nothing rather than raise."""
        mock_es_client.indices.exists.return_value = False
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        assert es_db.search("q") == []

    def test_search_swallows_transport_errors(self, es_db, mock_es_client):
        """A failing search must degrade to no results, matching the other backends."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.search.side_effect = Exception("boom")
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        assert es_db.search("q") == []

    def test_reranker_is_applied_to_results(self, es_db_with_reranker, mock_es_client, mock_reranker):
        """A configured reranker must get the chance to reorder the hits."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.search.return_value = {
            "hits": {"hits": [{"_id": "1", "_score": 0.5, "_source": {"content": "a", "meta_data": {}}}]}
        }
        es_db_with_reranker._client = mock_es_client
        es_db_with_reranker._owner_field_exact = True
        mock_reranker.rerank.return_value = []

        es_db_with_reranker.search("q")

        mock_reranker.rerank.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_search_uses_the_async_client(self, es_db, mock_es_client, mock_async_es_client):
        """The round trip is awaited natively rather than run on a worker thread."""
        mock_async_es_client.indices.exists.return_value = True
        mock_async_es_client.search.return_value = {
            "hits": {"hits": [{"_id": "1", "_score": 0.9, "_source": {"content": "a", "meta_data": {}}}]}
        }
        es_db._client = mock_es_client
        es_db._async_client = mock_async_es_client
        es_db._owner_field_exact = True

        results = await es_db.async_search("q", limit=4, user_id="alice")

        assert [d.content for d in results] == ["a"]
        mock_async_es_client.search.assert_awaited_once()
        mock_es_client.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_search_awaits_the_embedder(self, es_db, mock_es_client, mock_async_es_client):
        """async_get_embedding_and_usage exists on the base Embedder, so it must be awaited."""
        mock_async_es_client.indices.exists.return_value = True
        mock_async_es_client.search.return_value = {"hits": {"hits": []}}
        es_db._client = mock_es_client
        es_db._async_client = mock_async_es_client
        es_db._owner_field_exact = True

        awaited = {}

        async def record(text):
            awaited["text"] = text
            return [0.1] * TEST_DIMENSION, {}

        es_db.embedder.async_get_embedding_and_usage = record

        await es_db.async_search("find me", limit=4)

        assert awaited["text"] == "find me"
        es_db.embedder.get_embedding_and_usage.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_keyword_search_embeds_nothing(self, mock_embedder, mock_es_client, mock_async_es_client):
        """A keyword search has no vector half, so it must not pay for an embedding."""
        with patch(CLIENT_PATH), patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(
                index_name=TEST_INDEX_NAME,
                dimension=TEST_DIMENSION,
                embedder=mock_embedder,
                search_type=SearchType.keyword,
            )
        mock_async_es_client.indices.exists.return_value = True
        mock_async_es_client.search.return_value = {"hits": {"hits": []}}
        db._client = mock_es_client
        db._async_client = mock_async_es_client
        db._owner_field_exact = True

        called = {"n": 0}

        async def record(text):
            called["n"] += 1
            return [0.1] * TEST_DIMENSION, {}

        db.embedder.async_get_embedding_and_usage = record

        await db.async_search("q", limit=4)

        assert called["n"] == 0

    @pytest.mark.asyncio
    async def test_async_search_offloads_the_reranker(
        self, es_db_with_reranker, mock_es_client, mock_async_es_client, mock_reranker
    ):
        """rerank() is sync-only, so it belongs on a worker thread rather than the loop."""
        import threading

        mock_async_es_client.indices.exists.return_value = True
        mock_async_es_client.search.return_value = {
            "hits": {"hits": [{"_id": "1", "_score": 0.9, "_source": {"content": "a", "meta_data": {}}}]}
        }
        es_db_with_reranker._client = mock_es_client
        es_db_with_reranker._async_client = mock_async_es_client
        es_db_with_reranker._owner_field_exact = True

        seen = {}
        mock_reranker.rerank.side_effect = (
            lambda query, documents: seen.setdefault("thread", threading.get_ident()) and documents or documents
        )

        await es_db_with_reranker.async_search("q", limit=4)

        assert seen["thread"] != threading.get_ident(), "the reranker blocked the event loop"

    @pytest.mark.asyncio
    async def test_async_search_still_validates_the_owner(self, es_db):
        """The guard has to survive the rewrite: an empty user_id is not the shared bucket."""
        with pytest.raises(ValueError, match="user_id must not be empty"):
            await es_db.async_search("q", limit=4, user_id="")


class TestElasticsearchFilterEdgeCases:
    """Filter forms that used to select nothing, or nothing at all, without saying so."""

    def test_date_detection_is_off(self, es_db):
        """A date-shaped string must stay text, or its .keyword subfield never exists."""
        assert es_db.mappings["date_detection"] is False

    def test_equality_on_a_date_string_targets_the_keyword_subfield(self, es_db):
        """With date detection off the field is text+keyword, so equality can match it."""
        condition = es_db._build_single_filter_condition("published_on", "2024-01-15")

        assert condition == {"term": {"meta_data.published_on.keyword": "2024-01-15"}}

    def test_a_string_range_targets_the_keyword_subfield(self, es_db):
        """An ISO date range compares text tokens on the analyzed parent; keyword is exact."""
        condition = es_db._build_single_filter_condition("published_on", {"gte": "2024-01-01"})

        assert condition == {"range": {"meta_data.published_on.keyword": {"gte": "2024-01-01"}}}

    def test_a_numeric_range_stays_on_the_bare_field(self, es_db):
        """Numbers are mapped on the parent and have no keyword subfield."""
        condition = es_db._build_single_filter_condition("views", {"gte": 100, "lt": 500})

        assert condition == {"range": {"meta_data.views": {"gte": 100, "lt": 500}}}

    def test_a_dict_filter_still_works(self, es_db):
        """The dict path is unchanged by the DSL translation."""
        assert es_db._scoped_filter_conditions({"team": "eng"}, None) == [{"term": {"meta_data.team.keyword": "eng"}}]


class TestElasticsearchFilterExpressions:
    """The FilterExpr DSL must be translated, never dropped.

    Knowledge injects its ``linked_to`` instance scope into this same list when
    isolate_vector_search is on, so dropping the list drops that scope - and a filter
    meant to narrow the search widens it across knowledge bases instead.
    """

    def test_eq(self, es_db):
        from agno.filters import EQ

        assert es_db._translate_filter_expressions([EQ("team", "eng")]) == [{"term": {"meta_data.team.keyword": "eng"}}]

    def test_eq_on_a_number_skips_the_keyword_subfield(self, es_db):
        from agno.filters import EQ

        assert es_db._translate_filter_expressions([EQ("year", 2025)]) == [{"term": {"meta_data.year": 2025}}]

    def test_neq_becomes_must_not(self, es_db):
        from agno.filters import NEQ

        assert es_db._translate_filter_expressions([NEQ("team", "eng")]) == [
            {"bool": {"must_not": [{"term": {"meta_data.team.keyword": "eng"}}]}}
        ]

    @pytest.mark.parametrize("op_name,key", [("GT", "gt"), ("GTE", "gte"), ("LT", "lt"), ("LTE", "lte")])
    def test_range_operators(self, es_db, op_name, key):
        import agno.filters as filters

        expr = getattr(filters, op_name)("year", 2024)

        assert es_db._translate_filter_expressions([expr]) == [{"range": {"meta_data.year": {key: 2024}}}]

    def test_in_becomes_terms(self, es_db):
        from agno.filters import IN

        assert es_db._translate_filter_expressions([IN("team", ["eng", "ops"])]) == [
            {"terms": {"meta_data.team.keyword": ["eng", "ops"]}}
        ]

    def test_contains_and_startswith_use_the_unanalyzed_value(self, es_db):
        from agno.filters import CONTAINS, STARTSWITH

        assert es_db._translate_filter_expressions([CONTAINS("project", "beta")]) == [
            {"wildcard": {"meta_data.project.keyword": "*beta*"}}
        ]
        assert es_db._translate_filter_expressions([STARTSWITH("project", "beta")]) == [
            {"prefix": {"meta_data.project.keyword": "beta"}}
        ]

    def test_and_becomes_a_bool_filter(self, es_db):
        from agno.filters import AND, EQ

        (clause,) = es_db._translate_filter_expressions([AND(EQ("team", "eng"), EQ("year", 2025))])

        assert clause["bool"]["filter"] == [
            {"term": {"meta_data.team.keyword": "eng"}},
            {"term": {"meta_data.year": 2025}},
        ]

    def test_or_requires_one_match(self, es_db):
        from agno.filters import EQ, OR

        (clause,) = es_db._translate_filter_expressions([OR(EQ("team", "eng"), EQ("team", "ops"))])

        assert clause["bool"]["minimum_should_match"] == 1
        assert len(clause["bool"]["should"]) == 2

    def test_not_negates(self, es_db):
        from agno.filters import EQ, NOT

        assert es_db._translate_filter_expressions([NOT(EQ("team", "eng"))]) == [
            {"bool": {"must_not": [{"term": {"meta_data.team.keyword": "eng"}}]}}
        ]

    def test_nesting_is_translated_recursively(self, es_db):
        from agno.filters import AND, EQ, NOT

        (clause,) = es_db._translate_filter_expressions([AND(EQ("team", "eng"), NOT(EQ("year", 2023)))])

        assert clause["bool"]["filter"][1] == {"bool": {"must_not": [{"term": {"meta_data.year": 2023}}]}}

    def test_several_expressions_are_anded(self, es_db):
        """Knowledge prepends its linked_to scope to the caller's list, so both must apply."""
        from agno.filters import EQ

        conditions = es_db._translate_filter_expressions([EQ("linked_to", "eng_kb"), EQ("team", "eng")])

        assert conditions == [
            {"term": {"meta_data.linked_to.keyword": "eng_kb"}},
            {"term": {"meta_data.team.keyword": "eng"}},
        ]

    def test_the_instance_scope_survives_a_dsl_filter(self, es_db):
        """The isolation leak: dropping the list dropped linked_to and crossed knowledge bases."""
        from agno.filters import EQ

        conditions = es_db._scoped_filter_conditions([EQ("linked_to", "eng_kb"), EQ("team", "eng")], None)

        assert {"term": {"meta_data.linked_to.keyword": "eng_kb"}} in conditions

    def test_an_unknown_operator_raises_rather_than_widening(self, es_db):
        """A filter that cannot be applied must never turn into no filter at all."""
        with pytest.raises(ValueError, match="Unsupported filter operator"):
            es_db._translate_filter_expressions([{"op": "BOGUS", "key": "x", "value": 1}])

    def test_a_node_without_an_operator_raises(self, es_db):
        with pytest.raises(ValueError, match="no operator"):
            es_db._translate_filter_expressions([{"key": "x", "value": 1}])

    def test_excessive_nesting_raises(self, es_db):
        """Bounded recursion, matching the DSL's own depth limit."""
        node = {"op": "EQ", "key": "k", "value": 1}
        for _ in range(15):
            node = {"op": "NOT", "condition": node}

        with pytest.raises(ValueError, match="nests deeper"):
            es_db._translate_filter_expressions([node])


class TestElasticsearchRrfLicence:
    """rrf needs a platinum licence; a basic cluster answers 403 and the search returns []."""

    @staticmethod
    def _licence_error():
        return Exception(
            "AuthorizationException(403, 'security_exception', "
            "'current license is non-compliant for [Reciprocal Rank Fusion (RRF)]')"
        )

    def _rrf_db(self, mock_embedder):
        with patch(CLIENT_PATH), patch(ASYNC_CLIENT_PATH):
            return Elasticsearch(
                index_name=TEST_INDEX_NAME,
                dimension=TEST_DIMENSION,
                embedder=mock_embedder,
                search_type=SearchType.hybrid,
                hybrid_strategy=HybridStrategy.rrf,
            )

    def test_the_licence_refusal_is_recognised(self, mock_embedder):
        db = self._rrf_db(mock_embedder)

        assert db._is_unlicensed_rrf_error(self._licence_error()) is True

    def test_other_errors_are_not_mistaken_for_it(self, mock_embedder):
        db = self._rrf_db(mock_embedder)

        assert db._is_unlicensed_rrf_error(Exception("connection refused")) is False

    def test_a_boost_search_never_matches(self, es_db):
        """Only an rrf search can be refused for want of an rrf licence."""
        assert es_db.hybrid_strategy == HybridStrategy.boost
        assert es_db._is_unlicensed_rrf_error(self._licence_error()) is False

    def test_search_falls_back_to_boost_instead_of_returning_nothing(self, mock_embedder, mock_es_client):
        """Ingestion succeeds either way, so an empty result reads as an empty knowledge base."""
        db = self._rrf_db(mock_embedder)
        mock_es_client.indices.exists.return_value = True
        mock_es_client.search.side_effect = [
            self._licence_error(),
            {"hits": {"hits": [{"_id": "1", "_score": 1.0, "_source": {"content": "a", "meta_data": {}}}]}},
        ]
        db._client = mock_es_client
        db._owner_field_exact = True

        results = db.search("q", limit=5)

        assert [d.content for d in results] == ["a"]
        assert db.hybrid_strategy == HybridStrategy.boost, "the downgrade must stick"

    def test_the_downgrade_is_not_retried_on_the_next_search(self, mock_embedder, mock_es_client):
        """Once downgraded, a later search must not spend a round trip re-learning the refusal."""
        db = self._rrf_db(mock_embedder)
        mock_es_client.indices.exists.return_value = True
        mock_es_client.search.side_effect = [
            self._licence_error(),
            {"hits": {"hits": []}},
            {"hits": {"hits": []}},
        ]
        db._client = mock_es_client
        db._owner_field_exact = True

        db.search("q", limit=5)
        call_count_after_first = mock_es_client.search.call_count
        db.search("q", limit=5)

        assert mock_es_client.search.call_count == call_count_after_first + 1


class TestElasticsearchClusterLimits:
    """Values the cluster refuses outright, which the search path would turn into empty results."""

    @pytest.mark.parametrize("limit,expected", [(5, 50), (100, 1000), (1000, 10000), (1001, 10000), (9000, 10000)])
    def test_num_candidates_is_capped_at_the_cluster_ceiling(self, es_db, limit, expected):
        """Above 10000 the cluster answers "[num_candidates] cannot exceed [10000]"."""
        assert es_db._resolve_num_candidates(limit) == expected

    def test_an_explicit_num_candidates_is_capped_too(self, mock_embedder):
        """A constructor argument reaches the same ceiling as a derived value."""
        with patch(CLIENT_PATH), patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(
                index_name=TEST_INDEX_NAME, dimension=TEST_DIMENSION, embedder=mock_embedder, num_candidates=20000
            )

        assert db._resolve_num_candidates(5) == 10000

    def test_the_cap_never_pulls_num_candidates_below_k(self, es_db):
        """num_candidates < k is rejected, so the ceiling must not create that case."""
        for limit in (1, 50, 1000, 10000):
            assert es_db._resolve_num_candidates(limit) >= limit

    def test_a_capped_vector_query_is_still_well_formed(self, es_db):
        """The knn clause the cap produces has to satisfy k <= num_candidates <= 10000."""
        body = es_db._build_vector_query("q", 1000, None, None)

        knn = body["knn"]
        assert knn["k"] <= knn["num_candidates"] <= 10000

    def test_rrf_sets_a_rank_window_large_enough_for_the_page(self, mock_embedder):
        """rank_window_size defaults to 10; a larger size is rejected and swallowed into []."""
        with patch(CLIENT_PATH), patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(
                index_name=TEST_INDEX_NAME,
                dimension=TEST_DIMENSION,
                embedder=mock_embedder,
                hybrid_strategy=HybridStrategy.rrf,
            )

        for limit in (5, 10, 20, 100):
            window = db._build_hybrid_query("q", limit, None, None)["retriever"]["rrf"]["rank_window_size"]
            assert window >= limit, "a page larger than the rank window comes back empty"
            assert window >= 10, "the cluster floor for rank_window_size"


class TestElasticsearchServerless:
    """A serverless project manages its own shards and segments and refuses to be told otherwise."""

    def test_the_default_settings_keep_a_single_node_cluster_green(self, es_db):
        """The cluster default of one replica cannot be assigned on one node, leaving it yellow."""
        assert es_db.settings == {"index": {"number_of_replicas": 0}}

    def test_shard_count_is_left_to_the_cluster(self, es_db):
        """number_of_shards has no single-node problem and serverless refuses it."""
        assert "number_of_shards" not in es_db.settings["index"]

    def test_create_retries_without_settings_when_the_cluster_refuses_them(self, es_db, mock_es_client):
        """A serverless project rejects the replica setting; the index is still creatable without it."""
        mock_es_client.indices.exists.return_value = False
        mock_es_client.indices.create.side_effect = [
            Exception("Settings [index.number_of_replicas] are not available when running in serverless mode"),
            {"acknowledged": True},
        ]
        es_db._client = mock_es_client

        es_db.create()

        assert mock_es_client.indices.create.call_count == 2
        assert "settings" not in mock_es_client.indices.create.call_args_list[1][1]

    @pytest.mark.asyncio
    async def test_async_create_retries_without_settings_too(self, es_db, mock_async_es_client):
        """The async path must degrade the same way."""
        mock_async_es_client.indices.exists.return_value = False
        mock_async_es_client.indices.create.side_effect = [
            Exception("Settings [index.number_of_replicas] are not available when running in serverless mode"),
            {"acknowledged": True},
        ]
        es_db._async_client = mock_async_es_client

        await es_db.async_create()

        assert mock_async_es_client.indices.create.await_count == 2

    def test_create_does_not_retry_a_real_failure(self, es_db, mock_es_client):
        """Only a refusal of the settings is retried; anything else propagates."""
        mock_es_client.indices.exists.return_value = False
        mock_es_client.indices.create.side_effect = RuntimeError("cluster unreachable")
        es_db._client = mock_es_client

        with pytest.raises(RuntimeError, match="cluster unreachable"):
            es_db.create()

        assert mock_es_client.indices.create.call_count == 1

    def test_index_settings_are_sent_when_asked_for(self, mock_embedder, mock_es_client):
        """A self-managed cluster can still be told how to shard."""
        with patch(CLIENT_PATH), patch(ASYNC_CLIENT_PATH):
            db = Elasticsearch(
                index_name=TEST_INDEX_NAME,
                dimension=TEST_DIMENSION,
                embedder=mock_embedder,
                index_settings={"index": {"number_of_shards": 3}},
            )
        mock_es_client.indices.exists.return_value = False
        db._client = mock_es_client

        db.create()

        assert mock_es_client.indices.create.call_args[1]["settings"] == {"index": {"number_of_shards": 3}}

    def test_optimize_is_skipped_when_the_cluster_manages_its_own_segments(self, es_db, mock_es_client):
        """_forcemerge answers api_not_available_exception; optimize is a hint, not correctness."""
        from elastic_transport import ApiResponseMeta
        from elasticsearch import ApiError

        mock_es_client.indices.exists.return_value = True
        mock_es_client.indices.forcemerge.side_effect = ApiError(
            "api_not_available_exception: not available when running in serverless mode",
            meta=ApiResponseMeta(status=410, http_version="1.1", headers={}, duration=0.0, node=None),
            body=None,
        )
        es_db._client = mock_es_client

        # Must not raise: optimising is a performance hint, not a correctness step.
        es_db.optimize()

    def test_optimize_still_raises_a_real_failure(self, es_db, mock_es_client):
        """Swallowing the serverless answer must not swallow everything else."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.indices.forcemerge.side_effect = RuntimeError("disk full")

        es_db._client = mock_es_client

        with pytest.raises(RuntimeError, match="disk full"):
            es_db.optimize()


class TestElasticsearchFilters:
    """Test filter translation."""

    def test_scalar_becomes_a_term_filter(self, es_db):
        assert es_db._build_single_filter_condition("team", "eng") == {"term": {"meta_data.team.keyword": "eng"}}

    def test_list_becomes_a_terms_filter(self, es_db):
        assert es_db._build_single_filter_condition("team", ["a", "b"]) == {
            "terms": {"meta_data.team.keyword": ["a", "b"]}
        }

    @pytest.mark.parametrize("operator", ["$in", "in"])
    def test_in_operator_becomes_a_terms_filter(self, es_db, operator):
        assert es_db._build_single_filter_condition("team", {operator: ["a", "b"]}) == {
            "terms": {"meta_data.team.keyword": ["a", "b"]}
        }

    def test_range_operators_become_a_range_filter(self, es_db):
        assert es_db._build_single_filter_condition("year", {"gte": 2020, "lt": 2024}) == {
            "range": {"meta_data.year": {"gte": 2020, "lt": 2024}}
        }

    @pytest.mark.parametrize(
        "value,expected_field",
        [
            ("eng", "meta_data.team.keyword"),
            (1, "meta_data.team"),
            (True, "meta_data.team"),
            (4.5, "meta_data.team"),
        ],
        ids=["str", "int", "bool", "float"],
    )
    def test_term_filter_targets_the_field_the_value_type_is_mapped_to(self, es_db, value, expected_field):
        """Only a string gets a .keyword subfield; asking for one on a number matches nothing."""
        assert es_db._build_single_filter_condition("team", value) == {"term": {expected_field: value}}

    @pytest.mark.parametrize(
        "values,expected_field",
        [
            (["eng", "ops"], "meta_data.team.keyword"),
            ([1, 2], "meta_data.team"),
            ([True], "meta_data.team"),
        ],
        ids=["str", "int", "bool"],
    )
    def test_terms_filter_targets_the_field_the_value_type_is_mapped_to(self, es_db, values, expected_field):
        """A list of numbers must not be matched against a .keyword subfield that does not exist."""
        assert es_db._build_single_filter_condition("team", values) == {"terms": {expected_field: values}}

    @pytest.mark.parametrize(
        "values,expected_field",
        [(["eng"], "meta_data.team.keyword"), ([1], "meta_data.team")],
        ids=["str", "int"],
    )
    def test_in_operator_targets_the_field_the_value_type_is_mapped_to(self, es_db, values, expected_field):
        """The $in path builds the same terms filter and must pick the field the same way."""
        assert es_db._build_single_filter_condition("team", {"$in": values}) == {"terms": {expected_field: values}}

    def test_empty_list_filter_does_not_raise(self, es_db):
        """An empty list has no first element to type-check, which must not blow up."""
        assert es_db._build_single_filter_condition("team", []) == {"terms": {"meta_data.team": []}}

    @pytest.mark.parametrize("spelling", ["$in", "in"])
    def test_an_empty_in_list_still_builds_a_filter(self, es_db, spelling):
        """An empty selection must select nothing, not silently drop the filter.

        Reading the operator by truthiness sent an empty $in list on to the absent "in"
        key, dropped the condition, and ran the search unfiltered - so a filter matching
        nothing returned every document.
        """
        condition = es_db._build_single_filter_condition("team", {spelling: []})

        assert condition == {"terms": {"meta_data.team": []}}

    def test_both_spellings_of_in_agree(self, es_db):
        """$in and in are the same operator and must never disagree."""
        for values in ([], ["eng"], [1, 2]):
            assert es_db._build_single_filter_condition("team", {"$in": values}) == (
                es_db._build_single_filter_condition("team", {"in": values})
            )

    def test_an_empty_in_list_reaches_the_query_as_a_filter(self, es_db):
        """The dropped-condition bug was only visible once the filter reached the query."""
        body = es_db._build_keyword_query("q", 5, {"team": {"$in": []}}, None)

        assert {"terms": {"meta_data.team": []}} in body["query"]["bool"]["filter"]

    def test_unsupported_operator_is_dropped(self, es_db):
        """An unknown operator must be skipped rather than emit a broken clause."""
        assert es_db._build_single_filter_condition("team", {"$regex": "x"}) is None

    def test_build_filter_conditions_skips_invalid_entries(self, es_db):
        """One bad filter must not discard the good ones."""
        conditions = es_db._build_filter_conditions({"team": "eng", "bad": {"$regex": "x"}})

        assert conditions == [{"term": {"meta_data.team.keyword": "eng"}}]


class TestElasticsearchWrites:
    """Test insert and upsert."""

    def test_insert_sends_index_operations(self, es_db, mock_es_client, create_test_documents):
        """An insert must emit an index action per document."""
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client
        es_db._owner_field_exact = True
        docs = create_test_documents(2)

        es_db.insert("hash-1", docs)

        operations = mock_es_client.bulk.call_args[1]["operations"]
        assert len(operations) == 4
        assert all("index" in op for op in operations[::2])

    def test_upsert_sends_update_operations(self, es_db, mock_es_client, create_test_documents):
        """An upsert must use update with doc_as_upsert so it lands in place."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.search.return_value = {"hits": {"hits": [], "total": {"value": 0}}}
        es_db._client = mock_es_client
        es_db._owner_field_exact = True
        docs = create_test_documents(1)

        es_db.upsert("hash-1", docs)

        operations = mock_es_client.bulk.call_args[1]["operations"]
        assert "update" in operations[0]
        assert operations[1]["doc_as_upsert"] is True

    def test_upsert_clears_the_previous_chunks_first(self, es_db, mock_es_client, create_test_documents):
        """A re-upsert into fewer chunks must not leave the surplus behind."""
        mock_es_client.indices.exists.return_value = True
        # content_hash_exists finds the previous generation
        mock_es_client.search.return_value = {"hits": {"hits": [], "total": {"value": 1}}}
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        es_db.upsert("hash-1", create_test_documents(1))

        mock_es_client.delete_by_query.assert_called_once()

    def test_insert_creates_the_index_when_missing(self, es_db, mock_es_client, create_test_documents):
        """Writing to an absent index must create it rather than fail."""
        mock_es_client.indices.exists.return_value = False
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        es_db.insert("hash-1", create_test_documents(1))

        mock_es_client.indices.create.assert_called_once()

    def test_insert_of_nothing_is_a_noop(self, es_db, mock_es_client):
        """An empty batch must not reach the cluster."""
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        es_db.insert("hash-1", [])

        mock_es_client.bulk.assert_not_called()

    def test_a_bad_document_does_not_sink_the_batch(self, es_db, mock_es_client, create_test_documents):
        """One unusable document must be skipped so the rest still land."""
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client
        es_db._owner_field_exact = True
        docs = create_test_documents(2)
        docs[0].embedding = [0.1] * (TEST_DIMENSION + 1)

        es_db.insert("hash-1", docs)

        operations = mock_es_client.bulk.call_args[1]["operations"]
        assert len(operations) == 2

    def test_upsert_available(self, es_db):
        assert es_db.upsert_available() is True

    @pytest.mark.asyncio
    async def test_async_insert_sends_index_operations(
        self, es_db, mock_es_client, mock_async_es_client, create_test_documents
    ):
        """The async write path must mirror the sync one."""
        mock_async_es_client.indices.exists.return_value = True
        es_db._async_client = mock_async_es_client
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        await es_db.async_insert("hash-1", create_test_documents(2))

        operations = mock_async_es_client.bulk.call_args[1]["operations"]
        assert len(operations) == 4


class TestElasticsearchBulkFailuresSurface:
    """A rejected chunk must reach the caller: ingestion decides COMPLETED on whether insert raises."""

    @staticmethod
    def _rejected(action="index"):
        return {
            "errors": True,
            "items": [
                {action: {"_id": "1"}},
                {action: {"_id": "2", "error": {"type": "document_parsing_exception", "reason": "bad field"}}},
            ],
        }

    def test_insert_raises_when_a_document_is_rejected(self, es_db, mock_es_client, create_test_documents):
        """Logging alone would commit the rest of the batch and report success."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.bulk.return_value = self._rejected("index")
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        with pytest.raises(RuntimeError, match="rejected 1 of 2"):
            es_db.insert("hash-1", create_test_documents(2))

    def test_the_error_names_the_cause(self, es_db, mock_es_client, create_test_documents):
        """A bare count is not actionable, so the cluster's own reason is carried out."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.bulk.return_value = self._rejected("index")
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        with pytest.raises(RuntimeError, match="bad field"):
            es_db.insert("hash-1", create_test_documents(2))

    def test_upsert_raises_on_its_own_action_key(self, es_db, mock_es_client, create_test_documents):
        """An upsert batch answers with 'update' items, which must be read as errors too."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.search.return_value = {"hits": {"hits": [], "total": {"value": 0}}}
        mock_es_client.bulk.return_value = self._rejected("update")
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        with pytest.raises(RuntimeError, match="rejected"):
            es_db.upsert("hash-1", create_test_documents(2))

    @pytest.mark.asyncio
    async def test_async_insert_raises_too(self, es_db, mock_es_client, mock_async_es_client, create_test_documents):
        """The async path must not be the quiet one."""
        mock_async_es_client.indices.exists.return_value = True
        mock_async_es_client.bulk.return_value = self._rejected("index")
        es_db._client = mock_es_client
        es_db._async_client = mock_async_es_client
        es_db._owner_field_exact = True

        with pytest.raises(RuntimeError, match="rejected"):
            await es_db.async_insert("hash-1", create_test_documents(2))

    def test_a_clean_batch_still_does_not_raise(self, es_db, mock_es_client, create_test_documents):
        """The happy path must stay silent, or every ingest would fail."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.bulk.return_value = {"errors": False, "items": []}
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        es_db.insert("hash-1", create_test_documents(2))

    def test_many_errors_are_summarised_not_dumped(self, es_db, mock_es_client, create_test_documents):
        """One bad mapping must not produce a megabyte-long exception message."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.bulk.return_value = {
            "errors": True,
            "items": [{"index": {"_id": str(i), "error": {"reason": f"r{i}"}}} for i in range(50)],
        }
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        with pytest.raises(RuntimeError, match="and 47 more"):
            es_db.insert("hash-1", create_test_documents(2))

    def test_delete_by_id_reports_failure_instead_of_claiming_success(self, es_db, mock_es_client):
        """A caller reading the bool must not be told a surviving document was removed."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.bulk.return_value = self._rejected("delete")
        es_db._client = mock_es_client

        assert es_db.delete_by_id("abc") is False


class TestElasticsearchPreparationFailuresSurface:
    """A batch that loses every document before the write must not read as success."""

    @staticmethod
    def _undersized(count, dimension=TEST_DIMENSION + 1):
        return [Document(id=f"d{i}", name=f"d{i}", content=f"c{i}", embedding=[0.1] * dimension) for i in range(count)]

    def test_insert_raises_when_no_document_can_be_prepared(self, es_db, mock_es_client):
        """Nothing was written, so a quiet return would have ingestion mark it indexed."""
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        with pytest.raises(RuntimeError, match="prepared none of 3"):
            es_db.insert("hash-1", self._undersized(3))

        mock_es_client.bulk.assert_not_called()

    def test_upsert_raises_when_no_document_can_be_prepared(self, es_db, mock_es_client):
        """The upsert path prepares its own operations and needs the same guard."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.search.return_value = {"hits": {"hits": [], "total": {"value": 0}}}
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        with pytest.raises(RuntimeError, match="prepared none of 2"):
            es_db.upsert("hash-1", self._undersized(2))

    @pytest.mark.asyncio
    async def test_async_insert_raises_when_no_document_can_be_prepared(
        self, es_db, mock_es_client, mock_async_es_client
    ):
        """The async path must not be the quiet one."""
        mock_async_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client
        es_db._async_client = mock_async_es_client
        es_db._owner_field_exact = True

        with pytest.raises(RuntimeError, match="prepared none of 2"):
            await es_db.async_insert("hash-1", self._undersized(2))

    def test_a_total_loss_of_wrong_width_vectors_raises(self, es_db, mock_es_client):
        """A wrong-width vector is present but unusable, so nothing is written and the batch must raise."""
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client
        es_db._owner_field_exact = True
        docs = self._undersized(2)

        with pytest.raises(RuntimeError):
            es_db.insert("hash-1", docs)

        mock_es_client.bulk.assert_not_called()
        # The drops are also cleared, so a caller inspecting the batch sees nothing retrievable.
        assert not any(d.embedding for d in docs)

    def test_a_partial_shortfall_still_writes_the_good_chunks(self, es_db, mock_es_client, create_test_documents):
        """Partial loss stays a warning: the surviving chunks are retrievable and ingestion reports PARTIAL."""
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client
        es_db._owner_field_exact = True
        docs = create_test_documents(2)
        docs[0].embedding = [0.1] * (TEST_DIMENSION + 1)

        es_db.insert("hash-1", docs)

        operations = mock_es_client.bulk.call_args[1]["operations"]
        assert len(operations) == 2, "the one good document must still be written"

    def test_a_dropped_chunk_stops_counting_as_embedded(self, es_db, mock_es_client, create_test_documents):
        """Ingestion classifies PARTIAL by counting embeddings, so a dropped chunk must not still carry one.

        A wrong-width vector is present but unusable: left in place it counts as embedded
        and the content is reported COMPLETED despite never being written.
        """
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client
        es_db._owner_field_exact = True
        docs = create_test_documents(3)
        docs[0].embedding = [0.1] * (TEST_DIMENSION + 1)

        es_db.insert("hash-1", docs)

        assert docs[0].embedding is None, "the dropped chunk must not look retrievable"
        assert all(d.embedding for d in docs[1:]), "the chunks that landed must keep their embeddings"
        assert sum(1 for d in docs if d.embedding) == 2, "the shortfall has to be visible as 2 of 3"

    def test_a_dropped_chunk_stops_counting_as_embedded_on_upsert(self, es_db, mock_es_client, create_test_documents):
        """The upsert path prepares its own operations and must mark drops the same way."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.search.return_value = {"hits": {"hits": [], "total": {"value": 0}}}
        es_db._client = mock_es_client
        es_db._owner_field_exact = True
        docs = create_test_documents(2)
        docs[0].embedding = [0.1] * (TEST_DIMENSION + 1)

        es_db.upsert("hash-1", docs)

        assert docs[0].embedding is None

    def test_an_empty_batch_is_not_an_error(self, es_db, mock_es_client):
        """Nothing in, nothing expected out - that is a no-op, not a failure."""
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        es_db.insert("hash-1", [])


class TestElasticsearchAsyncDoesNotBlock:
    """The blocking prelude of an async write must not run on the event-loop thread."""

    @pytest.mark.asyncio
    async def test_async_upsert_offloads_the_replacement_prelude(
        self, es_db, mock_es_client, mock_async_es_client, create_test_documents
    ):
        """The gate, the existence check and the delete are sync round trips: they belong on a worker thread."""
        import threading

        mock_es_client.indices.exists.return_value = True
        mock_async_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client
        es_db._async_client = mock_async_es_client
        es_db._owner_field_exact = True

        loop_thread = threading.get_ident()
        seen = {}

        original = es_db._replace_prelude

        def record(content_hash, user_id):
            seen["thread"] = threading.get_ident()
            return original(content_hash, user_id)

        with patch.object(es_db, "_replace_prelude", side_effect=record):
            await es_db.async_upsert("hash-1", create_test_documents(1), user_id="alice")

        assert seen["thread"] != loop_thread, "the prelude blocked the event loop"

    @pytest.mark.asyncio
    async def test_async_insert_offloads_the_owner_gate(
        self, es_db, mock_es_client, mock_async_es_client, create_test_documents
    ):
        """The gate inspects the live mapping over the network, so it must not block the loop either."""
        import threading

        mock_es_client.indices.exists.return_value = True
        mock_async_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client
        es_db._async_client = mock_async_es_client
        es_db._owner_field_exact = True

        loop_thread = threading.get_ident()
        seen = {}

        def record(user_id):
            seen["thread"] = threading.get_ident()
            return True

        with patch.object(es_db, "_require_owner_field", side_effect=record):
            await es_db.async_insert("hash-1", create_test_documents(1), user_id="alice")

        assert seen["thread"] != loop_thread, "the owner gate blocked the event loop"

    @pytest.mark.asyncio
    async def test_async_upsert_still_gates_a_bad_mapping(self, es_db, mock_es_client, mock_async_es_client):
        """Offloading must not swallow the refusal: the ValueError has to survive the thread hop."""
        mock_es_client.indices.get_mapping.return_value = {
            TEST_INDEX_NAME: {"mappings": {"properties": {"user_id": {"type": "text"}}}}
        }
        es_db._client = mock_es_client
        es_db._async_client = mock_async_es_client
        es_db._owner_field_exact = None

        with pytest.raises(ValueError, match="recreate the index"):
            await es_db.async_upsert("hash-1", [], user_id="alice")


class TestElasticsearchDeletes:
    """Test the delete paths."""

    def test_delete_all_uses_match_all(self, es_db, mock_es_client):
        """delete() must clear the documents but keep the index."""
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client

        assert es_db.delete() is True
        assert mock_es_client.delete_by_query.call_args[1]["query"] == {"match_all": {}}
        mock_es_client.indices.delete.assert_not_called()

    def test_delete_by_name(self, es_db, mock_es_client):
        """delete_by_name must match the exact keyword, not analyzed tokens."""
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client

        assert es_db.delete_by_name("doc") is True
        assert mock_es_client.delete_by_query.call_args[1]["query"] == {"term": {"name.keyword": "doc"}}

    def test_delete_by_metadata(self, es_db, mock_es_client):
        """delete_by_metadata must translate the metadata into filter clauses."""
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client

        assert es_db.delete_by_metadata({"team": "eng"}) is True
        query = mock_es_client.delete_by_query.call_args[1]["query"]
        assert query["bool"]["filter"] == [{"term": {"meta_data.team.keyword": "eng"}}]

    def test_delete_by_content_id_unscoped(self, es_db, mock_es_client):
        """An unscoped delete must clear the content for every owner."""
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        assert es_db.delete_by_content_id("c1") is True
        assert mock_es_client.delete_by_query.call_args[1]["query"] == {"term": {"content_id.keyword": "c1"}}

    def test_delete_by_content_id_scoped_to_one_owner(self, es_db, mock_es_client):
        """A scoped delete must not reach another owner's or the shared chunks."""
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        assert es_db.delete_by_content_id("c1", user_id="alice") is True
        query = mock_es_client.delete_by_query.call_args[1]["query"]
        assert {"term": {"user_id": "alice"}} in query["bool"]["filter"]

    def test_delete_reports_failures(self, es_db, mock_es_client):
        """Partial failures must be reported rather than read as success."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.delete_by_query.return_value = {"deleted": 0, "failures": [{"cause": "x"}]}
        es_db._client = mock_es_client

        assert es_db.delete_by_name("doc") is False

    def test_delete_on_missing_index_is_false(self, es_db, mock_es_client):
        """There is nothing to delete in an index that does not exist."""
        mock_es_client.indices.exists.return_value = False
        es_db._client = mock_es_client

        assert es_db.delete_by_name("doc") is False

    def test_delete_by_id_uses_a_bulk_delete(self, es_db, mock_es_client):
        """delete_by_id must go through the bulk delete path."""
        mock_es_client.indices.exists.return_value = True
        es_db._client = mock_es_client

        assert es_db.delete_by_id("abc") is True
        operations = mock_es_client.bulk.call_args[1]["operations"]
        assert operations == [{"delete": {"_index": TEST_INDEX_NAME, "_id": "abc"}}]


class TestElasticsearchMetadata:
    """Test metadata updates and existence checks."""

    def test_update_metadata_merges_server_side(self, es_db, mock_es_client):
        """Every chunk of the content must be updated, however many there are."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.update_by_query.return_value = {"updated": 3}
        es_db._client = mock_es_client

        es_db.update_metadata("c1", {"team": "eng"})

        kwargs = mock_es_client.update_by_query.call_args[1]
        assert kwargs["query"] == {"term": {"content_id.keyword": "c1"}}
        assert kwargs["script"]["params"]["metadata"] == {"team": "eng"}

    def test_update_metadata_raises_on_missing_index(self, es_db, mock_es_client):
        """Updating a missing index must fail loudly."""
        mock_es_client.indices.exists.return_value = False
        es_db._client = mock_es_client

        with pytest.raises(ValueError, match="does not exist"):
            es_db.update_metadata("c1", {"team": "eng"})

    def test_update_metadata_raises_on_failures(self, es_db, mock_es_client):
        """Partial failures must not be swallowed."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.update_by_query.return_value = {"updated": 1, "failures": [{"cause": "x"}]}
        es_db._client = mock_es_client

        with pytest.raises(RuntimeError, match="failure"):
            es_db.update_metadata("c1", {"team": "eng"})

    def test_name_exists_matches_the_keyword_field(self, es_db, mock_es_client):
        """name_exists must match the exact name, not its analyzed tokens."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.search.return_value = {"hits": {"hits": [], "total": {"value": 1}}}
        es_db._client = mock_es_client

        assert es_db.name_exists("doc") is True
        assert mock_es_client.search.call_args[1]["query"] == {"term": {"name.keyword": "doc"}}

    def test_content_hash_exists_is_scoped_to_one_bucket(self, es_db, mock_es_client):
        """The dedup check must match exactly what the matching delete would clear."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.search.return_value = {"hits": {"hits": [], "total": {"value": 1}}}
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        assert es_db.content_hash_exists("h1", user_id="alice") is True
        query = mock_es_client.search.call_args[1]["query"]
        assert {"term": {"user_id": "alice"}} in query["bool"]["filter"]

    def test_content_hash_exists_for_shared_uses_field_absence(self, es_db, mock_es_client):
        """The shared bucket is the absence of the owner field."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.search.return_value = {"hits": {"hits": [], "total": {"value": 0}}}
        es_db._client = mock_es_client
        es_db._owner_field_exact = True

        es_db.content_hash_exists("h1", user_id=None)

        query = mock_es_client.search.call_args[1]["query"]
        assert es_db._shared_bucket_filter() in query["bool"]["filter"]

    def test_get_document_by_id_returns_none_when_absent(self, es_db, mock_es_client):
        """A missing document must read as None, not raise."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.get.return_value = {"found": False}
        es_db._client = mock_es_client

        assert es_db.get_document_by_id("abc") is None

    def test_get_document_by_id_returns_the_document(self, es_db, mock_es_client):
        """A found document must be reconstructed."""
        mock_es_client.indices.exists.return_value = True
        mock_es_client.get.return_value = {"found": True, "_source": {"content": "hello", "meta_data": {}}}
        es_db._client = mock_es_client

        doc = es_db.get_document_by_id("abc")

        assert doc is not None
        assert doc.content == "hello"
