from unittest.mock import AsyncMock, Mock, patch

import pytest
from couchbase.auth import PasswordAuthenticator
from couchbase.bucket import Bucket
from couchbase.cluster import Cluster
from couchbase.collection import Collection
from couchbase.exceptions import BucketDoesNotExistException
from couchbase.options import ClusterOptions

from agno.knowledge.document import Document
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.vectordb.couchbase.couchbase import (
    CouchbaseQuery,
    QueryVectorSearchSimilarity,
    QueryVectorSearchType,
)


# -------------------------------------------------
# Fixtures (duplicated for isolation)
# -------------------------------------------------


@pytest.fixture
def mock_async_cluster():
    with patch("agno.vectordb.couchbase.couchbase.AsyncCluster") as MockAsyncClusterClass:
        from acouchbase.cluster import AsyncCluster

        mock_cluster_instance = AsyncMock(spec=AsyncCluster)
        MockAsyncClusterClass.connect = AsyncMock(return_value=mock_cluster_instance)
        mock_cluster_instance.wait_until_ready = Mock()
        yield MockAsyncClusterClass


@pytest.fixture
def mock_cluster():
    with patch("agno.vectordb.couchbase.couchbase.Cluster") as mock_cluster:
        cluster = Mock(spec=Cluster)
        cluster.wait_until_ready.return_value = None
        mock_cluster.return_value = cluster
        yield cluster


@pytest.fixture
def mock_bucket(mock_cluster):
    bucket = Mock(spec=Bucket)
    mock_cluster.bucket.return_value = bucket
    collections_manager = Mock()
    bucket.collections.return_value = collections_manager
    mock_scope = Mock()
    mock_scope.name = "test_scope"
    mock_collection = Mock()
    mock_collection.name = "test_collection"
    mock_scope.collections = [mock_collection]
    collections_manager.get_all_scopes.return_value = [mock_scope]
    return bucket


@pytest.fixture
def mock_collection(mock_bucket):
    collection = Mock(spec=Collection)
    return collection


@pytest.fixture
def mock_embedder():
    with patch("agno.knowledge.embedder.openai.OpenAIEmbedder") as mock_embedder:
        openai_embedder = Mock(spec=OpenAIEmbedder)
        openai_embedder.get_embedding_and_usage.return_value = ([0.1, 0.2, 0.3, 0.4, 0.5], None)
        openai_embedder.get_embedding.return_value = [0.1, 0.2, 0.3, 0.4, 0.5]
        mock_embedder.return_value = openai_embedder
        return mock_embedder.return_value


@pytest.fixture
def couchbase_query_ann(mock_collection, mock_embedder):
    return CouchbaseQuery(
        bucket_name="test_bucket",
        scope_name="test_scope",
        collection_name="test_collection",
        couchbase_connection_string="couchbase://localhost",
        search_type=QueryVectorSearchType.ANN,
        similarity=QueryVectorSearchSimilarity.COSINE,
        n_probes=10,
        cluster_options=ClusterOptions(authenticator=PasswordAuthenticator("username", "password")),
        embedder=mock_embedder,
        embedding_key="embedding",
    )


@pytest.fixture
def couchbase_query_knn(mock_collection, mock_embedder):
    return CouchbaseQuery(
        bucket_name="test_bucket",
        scope_name="test_scope",
        collection_name="test_collection",
        couchbase_connection_string="couchbase://localhost",
        search_type="KNN",  # string form
        similarity="DOT",  # string form
        n_probes=None,
        cluster_options=ClusterOptions(authenticator=PasswordAuthenticator("username", "password")),
        embedder=mock_embedder,
    )


# -------------------------------------------------
# CouchbaseQuery Tests
# -------------------------------------------------


def test_couchbase_query_init_with_enums(couchbase_query_ann):
    assert couchbase_query_ann.bucket_name == "test_bucket"
    assert couchbase_query_ann.scope_name == "test_scope"
    assert couchbase_query_ann.collection_name == "test_collection"
    assert couchbase_query_ann._search_type == QueryVectorSearchType.ANN
    assert couchbase_query_ann._similarity == "COSINE"
    assert couchbase_query_ann._nprobes == 10
    assert couchbase_query_ann.embedding_key == "embedding"


def test_couchbase_query_init_with_strings(couchbase_query_knn):
    assert couchbase_query_knn._search_type == QueryVectorSearchType.KNN
    assert couchbase_query_knn._similarity == "DOT"
    assert couchbase_query_knn._nprobes is None
    assert couchbase_query_knn.embedding_key == "embedding"


def test_couchbase_query_create(couchbase_query_ann, mock_bucket):
    collections_manager = Mock()
    mock_bucket.collections.return_value = collections_manager
    couchbase_query_ann.create()
    collections_manager.create_scope.assert_called_once_with(scope_name="test_scope")


def test_couchbase_query_search_ann(couchbase_query_ann, mock_cluster, mock_embedder):
    mock_embedder.get_embedding.return_value = [0.1, 0.2, 0.3, 0.4, 0.5]
    mock_result = Mock()
    mock_row = Mock()
    mock_row.get.side_effect = lambda key, default=None: {
        "id": "test_id_1",
        "name": "test doc 1",
        "content": "test content 1",
        "meta_data": {"category": "test"},
        "embedding": [0.1, 0.2, 0.3, 0.4, 0.5],
        "content_id": "content_123",
    }.get(key, default)
    mock_result.rows.return_value = [mock_row]
    mock_cluster.query.return_value = mock_result
    results = couchbase_query_ann.search("test query", limit=5)
    mock_embedder.get_embedding.assert_called_once_with("test query")
    sql = mock_cluster.query.call_args[0][0]
    assert "APPROX_VECTOR_DISTANCE" in sql and "COSINE" in sql and ", 10" in sql and "LIMIT 5" in sql
    assert len(results) == 1 and results[0].id == "test_id_1"


def test_couchbase_query_search_knn(couchbase_query_knn, mock_cluster, mock_embedder):
    mock_embedder.get_embedding.return_value = [0.1, 0.2, 0.3, 0.4, 0.5]
    mock_result = Mock()
    mock_row = Mock()
    mock_row.get.side_effect = lambda key, default=None: {
        "id": "test_id_2",
        "name": "test doc 2",
        "content": "test content 2",
        "meta_data": {"priority": "high"},
        "embedding": [0.2, 0.3, 0.4, 0.5, 0.6],
        "content_id": "content_456",
    }.get(key, default)
    mock_result.rows.return_value = [mock_row]
    mock_cluster.query.return_value = mock_result
    results = couchbase_query_knn.search("test query", limit=3)
    sql = mock_cluster.query.call_args[0][0]
    assert "VECTOR_DISTANCE" in sql and "DOT" in sql and ", 10" not in sql and "LIMIT 3" in sql
    assert len(results) == 1 and results[0].id == "test_id_2"


def test_couchbase_query_search_no_embedding(couchbase_query_ann, mock_embedder):
    mock_embedder.get_embedding.return_value = None
    assert couchbase_query_ann.search("test query", limit=5) == []


def test_couchbase_query_search_exception(couchbase_query_ann, mock_cluster, mock_embedder):
    mock_embedder.get_embedding.return_value = [0.1, 0.2, 0.3, 0.4, 0.5]
    mock_cluster.query.side_effect = Exception("Query execution failed")
    with pytest.raises(Exception, match="Query execution failed"):
        couchbase_query_ann.search("test query", limit=5)


def test_couchbase_query_search_row_processing_error(couchbase_query_ann, mock_cluster, mock_embedder):
    mock_embedder.get_embedding.return_value = [0.1, 0.2, 0.3, 0.4, 0.5]
    mock_result = Mock()
    mock_good_row = Mock()
    mock_good_row.get.side_effect = lambda key, default=None: {
        "id": "test_id_good",
        "name": "good doc",
        "content": "good content",
        "meta_data": {},
        "embedding": [0.1, 0.2, 0.3],
        "content_id": None,
    }.get(key, default)
    mock_result.rows.return_value = [mock_good_row]
    mock_cluster.query.return_value = mock_result
    results = couchbase_query_ann.search("test query", limit=5)
    assert len(results) == 1 and results[0].id == "test_id_good"


@pytest.mark.asyncio
async def test_couchbase_query_async_search_ann(couchbase_query_ann, mock_embedder):
    mock_embedder.get_embedding.return_value = [0.1, 0.2, 0.3, 0.4, 0.5]
    mock_async_cluster = AsyncMock()
    mock_result = Mock()

    async def mock_rows():
        mock_row = Mock()
        mock_row.get.side_effect = lambda key, default=None: {
            "id": "async_test_id",
            "name": "async test doc",
            "content": "async test content",
            "meta_data": {"type": "async"},
            "embedding": [0.1, 0.2, 0.3, 0.4, 0.5],
            "content_id": "async_content_123",
        }.get(key, default)
        yield mock_row

    mock_result.rows = mock_rows
    mock_async_cluster.query.return_value = mock_result
    with patch.object(couchbase_query_ann, "get_async_cluster", return_value=mock_async_cluster):
        results = await couchbase_query_ann.async_search("async test query", limit=5)
    assert len(results) == 1 and results[0].id == "async_test_id"


@pytest.mark.asyncio
async def test_couchbase_query_async_search_with_async_embedding(couchbase_query_ann, mock_embedder):
    mock_embedder.async_get_embedding = AsyncMock(return_value=[0.1, 0.2, 0.3, 0.4, 0.5])
    mock_async_cluster = AsyncMock()
    mock_result = Mock()

    async def mock_rows():
        mock_row = Mock()
        mock_row.get.side_effect = lambda key, default=None: {
            "id": "async_embed_test_id",
            "name": "async embed test doc",
            "content": "async embed test content",
            "meta_data": {},
            "embedding": [0.1, 0.2, 0.3, 0.4, 0.5],
            "content_id": "async_embed_content_123",
        }.get(key, default)
        yield mock_row

    mock_result.rows = mock_rows
    mock_async_cluster.query.return_value = mock_result
    with patch.object(couchbase_query_ann, "get_async_cluster", return_value=mock_async_cluster):
        results = await couchbase_query_ann.async_search("async embed test query", limit=3)
    mock_embedder.async_get_embedding.assert_called_once_with("async embed test query")
    assert len(results) == 1 and results[0].id == "async_embed_test_id"


@pytest.mark.asyncio
async def test_couchbase_query_async_search_knn(couchbase_query_knn, mock_embedder):
    mock_embedder.get_embedding.return_value = [0.5, 0.4, 0.3, 0.2, 0.1]
    mock_async_cluster = AsyncMock()
    mock_result = Mock()

    async def mock_rows():
        mock_row = Mock()
        mock_row.get.side_effect = lambda key, default=None: {
            "id": "knn_async_test_id",
            "name": "knn async test doc",
            "content": "knn async test content",
            "meta_data": {"search_type": "knn"},
            "embedding": [0.5, 0.4, 0.3, 0.2, 0.1],
            "content_id": "knn_async_content_123",
        }.get(key, default)
        yield mock_row

    mock_result.rows = mock_rows
    mock_async_cluster.query.return_value = mock_result
    with patch.object(couchbase_query_knn, "get_async_cluster", return_value=mock_async_cluster):
        results = await couchbase_query_knn.async_search("knn async test query", limit=2)
    assert len(results) == 1 and results[0].id == "knn_async_test_id"


@pytest.mark.asyncio
async def test_couchbase_query_async_search_no_embedding(couchbase_query_ann, mock_embedder):
    mock_embedder.get_embedding.return_value = None
    if hasattr(mock_embedder, "async_get_embedding"):
        mock_embedder.async_get_embedding = AsyncMock(return_value=None)
    results = await couchbase_query_ann.async_search("test query", limit=5)
    assert results == []


@pytest.mark.asyncio
async def test_couchbase_query_async_search_exception(couchbase_query_ann, mock_embedder):
    mock_embedder.get_embedding.return_value = [0.1, 0.2, 0.3, 0.4, 0.5]
    mock_async_cluster = AsyncMock()
    mock_async_cluster.query.side_effect = Exception("Async query execution failed")
    with patch.object(couchbase_query_ann, "get_async_cluster", return_value=mock_async_cluster):
        with pytest.raises(Exception, match="Async query execution failed"):
            await couchbase_query_ann.async_search("test query", limit=5)


@pytest.mark.asyncio
async def test_couchbase_query_async_search_row_processing_error(couchbase_query_ann, mock_embedder):
    mock_embedder.get_embedding.return_value = [0.1, 0.2, 0.3, 0.4, 0.5]
    mock_async_cluster = AsyncMock()
    mock_result = Mock()

    async def mock_rows_with_error():
        bad_row = Mock()
        bad_row.get.side_effect = lambda key, default=None: (_ for _ in ()).throw(KeyError("Missing async field"))
        yield bad_row
        good_row = Mock()
        good_row.get.side_effect = lambda key, default=None: {
            "id": "async_good_id",
            "name": "async good doc",
            "content": "async good content",
            "meta_data": {},
            "embedding": [0.1, 0.2, 0.3],
            "content_id": None,
        }.get(key, default)
        yield good_row

    mock_result.rows = mock_rows_with_error
    mock_async_cluster.query.return_value = mock_result
    with patch.object(couchbase_query_ann, "get_async_cluster", return_value=mock_async_cluster):
        results = await couchbase_query_ann.async_search("test query", limit=5)
    assert len(results) == 1 and results[0].id == "async_good_id"


@pytest.mark.asyncio
async def test_couchbase_query_async_create(couchbase_query_ann, mock_bucket):
    collections_manager = Mock()
    mock_bucket.collections.return_value = collections_manager
    with patch.object(
        couchbase_query_ann, "_async_create_collection_and_scope", new_callable=AsyncMock
    ) as mock_async_create:
        await couchbase_query_ann.async_create()
        mock_async_create.assert_called_once()


def test_couchbase_query_enum_values():
    assert QueryVectorSearchType.ANN == "ANN"
    assert QueryVectorSearchType.KNN == "KNN"
    assert QueryVectorSearchSimilarity.COSINE == "COSINE"
    assert QueryVectorSearchSimilarity.DOT == "DOT"
    assert QueryVectorSearchSimilarity.L2 == "L2"
    assert QueryVectorSearchSimilarity.EUCLIDEAN == "EUCLIDEAN"
    assert QueryVectorSearchSimilarity.L2_SQUARED == "L2_SQUARED"
    assert QueryVectorSearchSimilarity.EUCLIDEAN_SQUARED == "EUCLIDEAN_SQUARED"


def test_couchbase_query_similarity_string_conversion(mock_collection, mock_embedder):
    query_db = CouchbaseQuery(
        bucket_name="test_bucket",
        scope_name="test_scope",
        collection_name="test_collection",
        couchbase_connection_string="couchbase://localhost",
        search_type=QueryVectorSearchType.ANN,
        similarity="cosine",
        n_probes=5,
        cluster_options=ClusterOptions(authenticator=PasswordAuthenticator("username", "password")),
        embedder=mock_embedder,
    )
    assert query_db._similarity == "COSINE"


def test_couchbase_query_custom_embedding_key(mock_collection, mock_embedder):
    query_db = CouchbaseQuery(
        bucket_name="test_bucket",
        scope_name="test_scope",
        collection_name="test_collection",
        couchbase_connection_string="couchbase://localhost",
        search_type=QueryVectorSearchType.KNN,
        similarity=QueryVectorSearchSimilarity.L2,
        n_probes=None,
        cluster_options=ClusterOptions(authenticator=PasswordAuthenticator("username", "password")),
        embedder=mock_embedder,
        embedding_key="custom_embedding_field",
    )
    assert query_db.embedding_key == "custom_embedding_field"


def test_couchbase_query_insert(couchbase_query_ann, mock_collection):
    """Test insert method."""
    from agno.knowledge.document import Document

    documents = [Document(content="test content 1"), Document(content="test content 2")]
    from couchbase.result import MultiMutationResult

    mock_result = Mock(spec=MultiMutationResult)
    mock_result.all_ok = True
    mock_collection.insert_multi.return_value = mock_result

    # Properly connect the mock_collection to the instance
    couchbase_query_ann._collection = mock_collection

    couchbase_query_ann.insert(documents=documents, content_hash="test_hash")
    assert mock_collection.insert_multi.called


def test_couchbase_query_upsert(couchbase_query_ann, mock_collection):
    """Test upsert method."""
    from agno.knowledge.document import Document

    documents = [Document(content="test content 1"), Document(content="test content 2")]
    from couchbase.result import MultiMutationResult

    mock_result = Mock(spec=MultiMutationResult)
    mock_result.all_ok = True
    mock_collection.upsert_multi.return_value = mock_result

    # Properly connect the mock_collection to the instance
    couchbase_query_ann._collection = mock_collection

    couchbase_query_ann.upsert(documents=documents, content_hash="test_hash")
    assert mock_collection.upsert_multi.called


def test_couchbase_query_drop(couchbase_query_ann, mock_bucket):
    """Test drop method."""
    mock_collections_mgr = Mock()
    mock_bucket.collections.return_value = mock_collections_mgr

    with patch.object(couchbase_query_ann, "exists", return_value=True):
        couchbase_query_ann.drop()
        mock_collections_mgr.drop_collection.assert_called_once()


def test_couchbase_query_exists(couchbase_query_ann, mock_bucket):
    """Test exists method."""
    assert couchbase_query_ann.exists() is True


def test_couchbase_query_name_exists(couchbase_query_ann, mock_bucket):
    """Test name_exists method."""
    mock_scope = Mock()
    couchbase_query_ann._scope = mock_scope
    mock_result = Mock()
    mock_result.rows.return_value = [{"name": "test_doc"}]
    mock_scope.query.return_value = mock_result

    assert couchbase_query_ann.name_exists("test_doc") is True

    mock_result.rows.return_value = []
    assert couchbase_query_ann.name_exists("nonexistent_doc") is False


def test_couchbase_query_id_exists(couchbase_query_ann, mock_collection):
    """Test id_exists method."""
    # Properly connect the mock_collection to the instance
    couchbase_query_ann._collection = mock_collection

    mock_exists_result = Mock()
    mock_exists_result.exists = True
    mock_collection.exists.return_value = mock_exists_result

    assert couchbase_query_ann.id_exists("test_id") is True

    mock_exists_result.exists = False
    assert couchbase_query_ann.id_exists("test_id") is False


def test_couchbase_query_delete_by_id(couchbase_query_ann, mock_collection):
    """Test delete_by_id method."""
    # Properly connect the mock_collection to the instance
    couchbase_query_ann._collection = mock_collection

    with patch.object(couchbase_query_ann, "id_exists") as mock_id_exists:
        mock_id_exists.return_value = True
        result = couchbase_query_ann.delete_by_id("doc_1")
        assert result is True
        mock_collection.remove.assert_called_with("doc_1")

        mock_id_exists.return_value = False
        result = couchbase_query_ann.delete_by_id("nonexistent_id")
        assert result is False


def test_couchbase_query_delete_by_name(couchbase_query_ann, mock_bucket, mock_collection):
    """Test delete_by_name method."""
    # Properly connect the mock_collection to the instance
    couchbase_query_ann._collection = mock_collection

    mock_scope = Mock()
    couchbase_query_ann._scope = mock_scope
    mock_result = Mock()
    mock_row1 = Mock()
    mock_row1.get.return_value = "doc_1"
    mock_row2 = Mock()
    mock_row2.get.return_value = "doc_2"
    mock_result.rows.return_value = [mock_row1, mock_row2]
    mock_scope.query.return_value = mock_result

    # Configure batch removal mock
    mock_multi_remove_result = Mock()
    mock_multi_remove_result.all_ok = True
    mock_multi_remove_result.exceptions = {}
    mock_collection.remove_multi = Mock(return_value=mock_multi_remove_result)

    result = couchbase_query_ann.delete_by_name("test_document")
    assert result is True
    mock_collection.remove_multi.assert_called_once()


def test_couchbase_query_delete_by_metadata(couchbase_query_ann, mock_bucket, mock_collection):
    """Test delete_by_metadata method."""
    # Properly connect the mock_collection to the instance
    couchbase_query_ann._collection = mock_collection

    mock_scope = Mock()
    couchbase_query_ann._scope = mock_scope
    mock_result = Mock()
    mock_row1 = Mock()
    mock_row1.get.return_value = "doc_1"
    mock_row2 = Mock()
    mock_row2.get.return_value = "doc_2"
    mock_result.rows.return_value = [mock_row1, mock_row2]
    mock_scope.query.return_value = mock_result

    metadata = {"category": "test", "priority": "high"}
    mock_multi_remove_result = Mock()
    mock_multi_remove_result.all_ok = True
    mock_multi_remove_result.exceptions = {}
    mock_collection.remove_multi = Mock(return_value=mock_multi_remove_result)

    result = couchbase_query_ann.delete_by_metadata(metadata)
    assert result is True
    mock_collection.remove_multi.assert_called_once()


def test_couchbase_query_delete_by_content_id(couchbase_query_ann, mock_bucket, mock_collection):
    """Test delete_by_content_id method."""
    # Properly connect the mock_collection to the instance
    couchbase_query_ann._collection = mock_collection

    mock_scope = Mock()
    couchbase_query_ann._scope = mock_scope
    mock_result = Mock()
    mock_row1 = Mock()
    mock_row1.get.return_value = "doc_1"
    mock_row2 = Mock()
    mock_row2.get.return_value = "doc_2"
    mock_result.rows.return_value = [mock_row1, mock_row2]
    mock_scope.query.return_value = mock_result

    mock_multi_remove_result = Mock()
    mock_multi_remove_result.all_ok = True
    mock_multi_remove_result.exceptions = {}
    mock_collection.remove_multi = Mock(return_value=mock_multi_remove_result)

    result = couchbase_query_ann.delete_by_content_id("content_123")
    assert result is True
    mock_collection.remove_multi.assert_called_once()


@pytest.mark.asyncio
async def test_couchbase_query_async_id_exists(couchbase_query_ann):
    """Test async_id_exists method."""
    from acouchbase.collection import AsyncCollection

    mock_collection_inst = AsyncMock(spec=AsyncCollection)
    mock_get_result = Mock()
    mock_collection_inst.exists = AsyncMock(return_value=mock_get_result)

    from agno.vectordb.couchbase.couchbase import CouchbaseQuery

    with patch.object(CouchbaseQuery, "get_async_collection", new_callable=AsyncMock) as mock_get_async_collection:
        mock_get_async_collection.return_value = mock_collection_inst

        mock_get_result.exists = True
        assert await couchbase_query_ann.async_id_exists("test_id") is True
        mock_collection_inst.exists.assert_called_once_with("test_id")

        mock_get_result.exists = False
        mock_collection_inst.exists.reset_mock()
        assert await couchbase_query_ann.async_id_exists("test_id") is False
        mock_collection_inst.exists.assert_called_once_with("test_id")


@pytest.mark.asyncio
async def test_couchbase_query_async_name_exists(couchbase_query_ann):
    """Test async_name_exists method."""
    from acouchbase.scope import AsyncScope

    mock_scope_inst = AsyncMock(spec=AsyncScope)
    mock_query_result = Mock()
    mock_scope_inst.query = Mock(return_value=mock_query_result)

    from agno.vectordb.couchbase.couchbase import CouchbaseQuery

    with patch.object(CouchbaseQuery, "get_async_scope", new_callable=AsyncMock) as mock_get_async_scope:
        mock_get_async_scope.return_value = mock_scope_inst

        async def mock_rows_found():
            yield {"name": "test_doc"}

        mock_query_result.rows = mock_rows_found
        assert await couchbase_query_ann.async_name_exists("test_doc") is True
        mock_scope_inst.query.assert_called_once()

        async def mock_rows_not_found():
            if False:
                yield

        mock_query_result.rows = mock_rows_not_found
        mock_scope_inst.query.reset_mock()
        assert await couchbase_query_ann.async_name_exists("nonexistent_doc") is False
        mock_scope_inst.query.assert_called_once()


@pytest.mark.asyncio
async def test_couchbase_query_async_drop(couchbase_query_ann):
    """Test async_drop method."""
    from acouchbase.bucket import AsyncBucket

    mock_bucket_inst = AsyncMock(spec=AsyncBucket)
    mock_collections_mgr = AsyncMock()
    mock_bucket_inst.collections = Mock(return_value=mock_collections_mgr)
    mock_collections_mgr.drop_collection = AsyncMock()

    from agno.vectordb.couchbase.couchbase import CouchbaseQuery

    with patch.object(CouchbaseQuery, "get_async_bucket", new_callable=AsyncMock) as mock_get_async_bucket:
        mock_get_async_bucket.return_value = mock_bucket_inst

        with patch.object(couchbase_query_ann, "async_exists", AsyncMock(return_value=True)) as mock_async_exists:
            await couchbase_query_ann.async_drop()
            mock_async_exists.assert_called_once()
            mock_get_async_bucket.assert_called_once()
            mock_collections_mgr.drop_collection.assert_called_once()


@pytest.mark.asyncio
async def test_couchbase_query_async_exists(couchbase_query_ann):
    """Test async_exists method."""
    from acouchbase.bucket import AsyncBucket

    mock_bucket_inst = AsyncMock(spec=AsyncBucket)
    mock_collections_mgr = AsyncMock()
    mock_bucket_inst.collections = Mock(return_value=mock_collections_mgr)

    mock_scope_obj = Mock()
    mock_scope_obj.name = couchbase_query_ann.scope_name
    mock_collection_obj = Mock()
    mock_collection_obj.name = couchbase_query_ann.collection_name
    mock_scope_obj.collections = [mock_collection_obj]

    from agno.vectordb.couchbase.couchbase import CouchbaseQuery

    with patch.object(CouchbaseQuery, "get_async_bucket", new_callable=AsyncMock) as mock_get_async_bucket:
        mock_get_async_bucket.return_value = mock_bucket_inst
        mock_collections_mgr.get_all_scopes = AsyncMock(return_value=[mock_scope_obj])

        assert await couchbase_query_ann.async_exists() is True
        mock_get_async_bucket.assert_called_once()
        mock_collections_mgr.get_all_scopes.assert_called_once()


@pytest.mark.asyncio
async def test_couchbase_query_async_insert(couchbase_query_ann, mock_embedder):
    """Test async_insert method."""
    import copy

    from acouchbase.collection import AsyncCollection
    from agno.knowledge.document import Document

    documents = [Document(name="doc1", content="content1"), Document(name="doc2", content="content2")]

    mock_async_collection_instance = AsyncMock(spec=AsyncCollection)
    mock_async_collection_instance.insert = AsyncMock(return_value=None)

    with patch.object(
        couchbase_query_ann, "get_async_collection", AsyncMock(return_value=mock_async_collection_instance)
    ) as mock_get_async_collection:
        await couchbase_query_ann.async_insert(documents=copy.deepcopy(documents), content_hash="test_hash")
        mock_get_async_collection.assert_called_once()

        first_call_args = mock_async_collection_instance.insert.call_args_list[0].args
        assert isinstance(first_call_args[0], str)
        assert first_call_args[1]["name"] == documents[0].name
        assert "filters" not in first_call_args[1]


@pytest.mark.asyncio
async def test_couchbase_query_async_upsert(couchbase_query_ann, mock_embedder):
    """Test async_upsert method."""
    import copy

    from acouchbase.collection import AsyncCollection
    from agno.knowledge.document import Document

    documents = [Document(name="doc1", content="content1"), Document(name="doc2", content="content2")]

    mock_async_collection_instance = AsyncMock(spec=AsyncCollection)
    mock_async_collection_instance.upsert = AsyncMock(return_value=None)

    with patch.object(
        couchbase_query_ann, "get_async_collection", AsyncMock(return_value=mock_async_collection_instance)
    ) as mock_get_async_collection:
        await couchbase_query_ann.async_upsert(documents=copy.deepcopy(documents), content_hash="test_hash")
        mock_get_async_collection.assert_called_once()

        first_call_args = mock_async_collection_instance.upsert.call_args_list[0].args
        assert isinstance(first_call_args[0], str)
        assert first_call_args[1]["name"] == documents[0].name
        assert "filters" not in first_call_args[1]


@pytest.mark.asyncio
async def test_couchbase_query_async_cluster_property_caching(couchbase_query_ann, mock_async_cluster):
    """Test the async_cluster property caching mechanism."""
    cluster_instance_1 = await couchbase_query_ann.get_async_cluster()

    mock_async_cluster.connect.assert_called_once_with(
        couchbase_query_ann.connection_string, couchbase_query_ann.cluster_options
    )

    mock_returned_cluster_instance = mock_async_cluster.connect.return_value
    assert couchbase_query_ann._async_cluster is cluster_instance_1
    assert cluster_instance_1 is mock_returned_cluster_instance

    cluster_instance_2 = await couchbase_query_ann.get_async_cluster()
    mock_async_cluster.connect.assert_called_once()
    assert cluster_instance_2 is cluster_instance_1


@pytest.mark.asyncio
async def test_couchbase_query_async_bucket_property_caching(couchbase_query_ann):
    """Test the async_bucket property caching mechanism."""
    from acouchbase.cluster import AsyncCluster

    mock_cluster_inst = AsyncMock(spec=AsyncCluster)
    mock_bucket_inst = AsyncMock()
    mock_cluster_inst.bucket = Mock(return_value=mock_bucket_inst)

    from agno.vectordb.couchbase.couchbase import CouchbaseQuery

    with patch.object(CouchbaseQuery, "get_async_cluster", new_callable=AsyncMock) as mock_get_async_cluster:
        mock_get_async_cluster.return_value = mock_cluster_inst

        bucket1 = await couchbase_query_ann.get_async_bucket()
        mock_get_async_cluster.assert_called_once()
        mock_cluster_inst.bucket.assert_called_once_with(couchbase_query_ann.bucket_name)
        assert bucket1 is mock_bucket_inst
        assert couchbase_query_ann._async_bucket is bucket1

        mock_get_async_cluster.reset_mock()
        mock_cluster_inst.bucket.reset_mock()

        bucket2 = await couchbase_query_ann.get_async_bucket()
        mock_get_async_cluster.assert_not_called()
        mock_cluster_inst.bucket.assert_not_called()
        assert bucket2 is bucket1


@pytest.mark.asyncio
async def test_couchbase_query_async_scope_property_caching(couchbase_query_ann):
    """Test the async_scope property caching mechanism."""
    from acouchbase.bucket import AsyncBucket
    from acouchbase.scope import AsyncScope

    mock_bucket_inst = AsyncMock(spec=AsyncBucket)
    mock_scope_inst = AsyncMock(spec=AsyncScope)
    mock_bucket_inst.scope = Mock(return_value=mock_scope_inst)

    from agno.vectordb.couchbase.couchbase import CouchbaseQuery

    with patch.object(CouchbaseQuery, "get_async_bucket", new_callable=AsyncMock) as mock_get_async_bucket:
        mock_get_async_bucket.return_value = mock_bucket_inst

        scope1 = await couchbase_query_ann.get_async_scope()
        mock_get_async_bucket.assert_called_once()
        mock_bucket_inst.scope.assert_called_once_with(couchbase_query_ann.scope_name)
        assert scope1 is mock_scope_inst
        assert couchbase_query_ann._async_scope is scope1

        mock_get_async_bucket.reset_mock()
        mock_bucket_inst.scope.reset_mock()

        scope2 = await couchbase_query_ann.get_async_scope()
        mock_get_async_bucket.assert_not_called()
        mock_bucket_inst.scope.assert_not_called()
        assert scope2 is scope1


@pytest.mark.asyncio
async def test_couchbase_query_async_collection_property_caching(couchbase_query_ann):
    """Test the async_collection property caching mechanism."""
    from acouchbase.collection import AsyncCollection
    from acouchbase.scope import AsyncScope

    mock_scope_inst = AsyncMock(spec=AsyncScope)
    mock_collection_inst = AsyncMock(spec=AsyncCollection)
    mock_scope_inst.collection = Mock(return_value=mock_collection_inst)

    from agno.vectordb.couchbase.couchbase import CouchbaseQuery

    with patch.object(CouchbaseQuery, "get_async_scope", new_callable=AsyncMock) as mock_get_async_scope:
        mock_get_async_scope.return_value = mock_scope_inst

        collection1 = await couchbase_query_ann.get_async_collection()
        mock_get_async_scope.assert_called_once()
        mock_scope_inst.collection.assert_called_once_with(couchbase_query_ann.collection_name)
        assert collection1 is mock_collection_inst
        assert couchbase_query_ann._async_collection is collection1

        mock_get_async_scope.reset_mock()
        mock_scope_inst.collection.reset_mock()

        collection2 = await couchbase_query_ann.get_async_collection()
        mock_get_async_scope.assert_not_called()
        mock_scope_inst.collection.assert_not_called()
        assert collection2 is collection1


def test_couchbase_query_delete_by_id_exception_handling(couchbase_query_ann, mock_collection):
    """Test delete_by_id method exception handling."""
    # Properly connect the mock_collection to the instance
    couchbase_query_ann._collection = mock_collection

    with patch.object(couchbase_query_ann, "id_exists") as mock_id_exists:
        mock_id_exists.return_value = True

        mock_collection.remove.side_effect = Exception("Remove error")
        result = couchbase_query_ann.delete_by_id("doc_1")
        assert result is False

        mock_id_exists.side_effect = Exception("Exists check error")
        result = couchbase_query_ann.delete_by_id("doc_1")
        assert result is False


def test_couchbase_query_delete_by_name_exception_handling(couchbase_query_ann):
    """Test delete_by_name method exception handling."""
    mock_scope = Mock()
    couchbase_query_ann._scope = mock_scope
    mock_scope.query.side_effect = Exception("Query error")
    result = couchbase_query_ann.delete_by_name("test_document")
    assert result is False


def test_couchbase_query_delete_by_metadata_exception_handling(couchbase_query_ann):
    """Test delete_by_metadata method exception handling."""
    mock_scope = Mock()
    couchbase_query_ann._scope = mock_scope
    mock_scope.query.side_effect = Exception("Query error")
    result = couchbase_query_ann.delete_by_metadata({"category": "test"})
    assert result is False


def test_couchbase_query_delete_by_content_id_exception_handling(couchbase_query_ann):
    """Test delete_by_content_id method exception handling."""
    mock_scope = Mock()
    couchbase_query_ann._scope = mock_scope
    mock_scope.query.side_effect = Exception("Query error")
    result = couchbase_query_ann.delete_by_content_id("content_123")
    assert result is False


# -------------------------------------------------
# Additional base tests from CouchbaseBase
# -------------------------------------------------


def test_couchbase_query_init_basic(couchbase_query_ann):
    """Test CouchbaseQuery initialization."""
    assert couchbase_query_ann.bucket_name == "test_bucket"
    assert couchbase_query_ann.scope_name == "test_scope"
    assert couchbase_query_ann.collection_name == "test_collection"


def test_couchbase_query_prepare_doc(couchbase_query_ann, mock_embedder):
    """Test document preparation."""
    document = Document(name="test doc", content="test content", meta_data={"key": "value"})
    prepared_doc = couchbase_query_ann.prepare_doc(document=document, content_hash="test_hash")
    assert prepared_doc["name"] == "test doc"
    assert prepared_doc["content"] == "test content"
    assert prepared_doc["meta_data"] == {"key": "value"}


def test_couchbase_query_init_empty_bucket_name():
    """Test initialization with empty bucket name."""
    with pytest.raises(ValueError, match="Bucket name must not be empty."):
        CouchbaseQuery(
            bucket_name="",
            scope_name="test_scope",
            collection_name="test_collection",
            couchbase_connection_string="couchbase://localhost",
            cluster_options=ClusterOptions(authenticator=PasswordAuthenticator("username", "password")),
            search_type="ANN",
            similarity="DOT_PRODUCT",
            n_probes=10,
        )


def test_couchbase_query_get_cluster_connection_error():
    """Test cluster connection error handling."""
    with patch("agno.vectordb.couchbase.couchbase.Cluster") as mock_cluster:
        mock_cluster.side_effect = Exception("Connection failed")
        with pytest.raises(ConnectionError, match="Failed to connect to Couchbase"):
            couchbase_query = CouchbaseQuery(
                bucket_name="test_bucket",
                scope_name="test_scope",
                collection_name="test_collection",
                couchbase_connection_string="couchbase://localhost",
                cluster_options=ClusterOptions(authenticator=PasswordAuthenticator("username", "password")),
                search_type="ANN",
                similarity="DOT_PRODUCT",
                n_probes=10,
            )
            couchbase_query.create()


def test_couchbase_query_get_bucket_not_exists(mock_cluster):
    """Test bucket not exists error handling."""
    mock_cluster.bucket.side_effect = BucketDoesNotExistException("Bucket does not exist")
    with pytest.raises(BucketDoesNotExistException):
        couchbase_query = CouchbaseQuery(
            bucket_name="nonexistent_bucket",
            scope_name="test_scope",
            collection_name="test_collection",
            couchbase_connection_string="couchbase://localhost",
            cluster_options=ClusterOptions(authenticator=PasswordAuthenticator("username", "password")),
            search_type="ANN",
            similarity="DOT_PRODUCT",
            n_probes=10,
        )
        couchbase_query.create()
