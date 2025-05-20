import copy
from unittest.mock import AsyncMock, Mock, patch

import pytest
from acouchbase.bucket import AsyncBucket
from acouchbase.cluster import AsyncCluster
from acouchbase.collection import AsyncCollection
from acouchbase.scope import AsyncScope
from couchbase.auth import PasswordAuthenticator
from couchbase.bucket import Bucket
from couchbase.cluster import Cluster
from couchbase.collection import Collection
from couchbase.exceptions import (
    BucketDoesNotExistException,
    CollectionAlreadyExistsException,
    ScopeAlreadyExistsException,
)
from couchbase.management.search import SearchIndex
from couchbase.options import ClusterOptions
from couchbase.result import GetResult, MultiMutationResult
from couchbase.scope import Scope

from agno.document import Document
from agno.vectordb.couchbase.couchbase import CouchbaseSearch, OpenAIEmbedder


@pytest.fixture
def mock_async_cluster():
    with patch("agno.vectordb.couchbase.couchbase.AsyncCluster") as MockAsyncClusterClass:
        mock_cluster_instance = AsyncMock(spec=AsyncCluster)
        MockAsyncClusterClass.connect = AsyncMock(return_value=mock_cluster_instance)
        # wait_until_ready is called by _get_async_cluster, ensure it's a mock
        # It's called on the instance, not awaited itself, so Mock() is fine.
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

    # Mock collections manager
    collections_manager = Mock()
    bucket.collections.return_value = collections_manager

    # Mock scope
    mock_scope = Mock()
    mock_scope.name = "test_scope"

    # Mock collection
    mock_collection = Mock()
    mock_collection.name = "test_collection"

    # Set up the scope to have the collection
    mock_scope.collections = [mock_collection]

    # Set up the collections manager to return scopes
    collections_manager.get_all_scopes.return_value = [mock_scope]

    return bucket


@pytest.fixture
def mock_scope(mock_bucket):
    scope = Mock(spec=Scope)
    mock_bucket.scope.return_value = scope
    return scope


@pytest.fixture
def mock_collection(mock_scope):
    collection = Mock(spec=Collection)
    mock_scope.collection.return_value = collection
    return collection


@pytest.fixture
def mock_embedder():
    with patch("agno.vectordb.couchbase.couchbase.OpenAIEmbedder") as mock_embedder:
        openai_embedder = Mock(spec=OpenAIEmbedder)
        openai_embedder.get_embedding_and_usage.return_value = ([0.1, 0.2, 0.3], None)
        openai_embedder.get_embedding.return_value = [0.1, 0.2, 0.3]
        mock_embedder.return_value = openai_embedder
        return mock_embedder.return_value


@pytest.fixture
def couchbase_fts(mock_collection, mock_embedder):
    fts = CouchbaseSearch(
        bucket_name="test_bucket",
        scope_name="test_scope",
        collection_name="test_collection",
        couchbase_connection_string="couchbase://localhost",
        cluster_options=ClusterOptions(
            authenticator=PasswordAuthenticator("username", "password"),
        ),
        search_index="test_index",
        embedder=mock_embedder,
    )
    return fts


@pytest.fixture
def couchbase_fts_overwrite(mock_collection, mock_embedder):
    fts = CouchbaseSearch(
        bucket_name="test_bucket",
        scope_name="test_scope",
        collection_name="test_collection",
        couchbase_connection_string="couchbase://localhost",
        cluster_options=ClusterOptions(
            authenticator=PasswordAuthenticator("username", "password"),
        ),
        overwrite=True,
        search_index=SearchIndex(
            name="test_index",
            source_type="couchbase",
            idx_type="fulltext-index",
            source_name="test_collection",
            uuid="test_uuid",
            params={},
            source_uuid="test_uuid",
            source_params={},
            plan_params={},
        ),
        embedder=mock_embedder,
    )
    return fts


def test_init(couchbase_fts):
    assert couchbase_fts.bucket_name == "test_bucket"
    assert couchbase_fts.scope_name == "test_scope"
    assert couchbase_fts.collection_name == "test_collection"
    assert couchbase_fts.search_index_name == "test_index"


def test_doc_exists(couchbase_fts, mock_collection):
    # Setup
    document = Document(content="test content")

    # Mock the exists method
    mock_exists_result = Mock()
    mock_exists_result.exists = True
    mock_collection.exists.return_value = mock_exists_result

    # Test document exists
    assert couchbase_fts.doc_exists(document) is True

    # Test document doesn't exist
    mock_exists_result.exists = False
    assert couchbase_fts.doc_exists(document) is False


def test_insert(couchbase_fts, mock_collection):
    # Setup
    documents = [Document(content="test content 1"), Document(content="test content 2")]
    mock_result = Mock(spec=MultiMutationResult)
    mock_result.all_ok = True
    mock_collection.insert_multi.return_value = mock_result

    # Test successful insert
    couchbase_fts.insert(documents)
    assert mock_collection.insert_multi.called

    # Reset mock to check insert with filters
    mock_collection.insert_multi.reset_mock()

    # Test insert with filters
    filters = {"category": "test", "priority": "high"}
    couchbase_fts.insert(documents, filters=filters)

    # Verify filters were included in the documents
    call_args = mock_collection.insert_multi.call_args[0][0]
    for doc_id in call_args:
        assert "filters" in call_args[doc_id]
        assert call_args[doc_id]["filters"] == filters

    # Test failed insert
    mock_result.all_ok = False
    mock_result.exceptions = {"error": "test error"}
    mock_collection.insert_multi.return_value = mock_result
    couchbase_fts.insert(documents)  # Should log warning but not raise exception


def test_upsert(couchbase_fts, mock_collection):
    # Setup
    documents = [Document(content="test content 1"), Document(content="test content 2")]
    mock_result = Mock(spec=MultiMutationResult)
    mock_result.all_ok = True
    mock_collection.upsert_multi.return_value = mock_result

    # Test successful upsert without filters
    couchbase_fts.upsert(documents)
    assert mock_collection.upsert_multi.called

    # Reset mock to check upsert with filters
    mock_collection.upsert_multi.reset_mock()

    # Test upsert with filters
    filters = {"category": "test", "priority": "high"}
    couchbase_fts.upsert(documents, filters=filters)

    # Verify filters were included in the documents
    call_args = mock_collection.upsert_multi.call_args[0][0]
    for doc_id in call_args:
        assert "filters" in call_args[doc_id]
        assert call_args[doc_id]["filters"] == filters

    # Test failed upsert
    mock_result.all_ok = False
    mock_result.exceptions = {"error": "test error"}
    mock_collection.upsert_multi.return_value = mock_result
    couchbase_fts.upsert(documents)  # Should log warning but not raise exception


def test_search(couchbase_fts, mock_scope, mock_collection):
    # Setup
    mock_search_result = Mock()
    mock_row = Mock()
    mock_row.id = "test_id"
    mock_row.score = 0.95
    mock_search_result.rows.return_value = [mock_row]
    mock_scope.search.return_value = mock_search_result

    # Setup KV get_multi response
    mock_get_result = Mock(spec=GetResult)
    mock_get_result.value = {
        "name": "test doc",
        "content": "test content",
        "meta_data": {},
        "embedding": [0.1, 0.2, 0.3],
    }
    mock_get_result.success = True
    mock_kv_response = Mock()
    mock_kv_response.all_ok = True
    mock_kv_response.results = {"test_id": mock_get_result}
    mock_collection.get_multi.return_value = mock_kv_response

    # Test
    results = couchbase_fts.search("test query", limit=5)
    assert len(results) == 1
    assert isinstance(results[0], Document)
    assert results[0].id == "test_id"
    assert results[0].name == "test doc"
    assert results[0].content == "test content"

    # Test with filters
    filters = {"category": "test"}
    couchbase_fts.search("test query", limit=5, filters=filters)
    # Verify that search was called with the correct arguments
    assert mock_scope.search.call_count == 2


def test_drop(mock_bucket, couchbase_fts):
    # Setup
    mock_collections_mgr = Mock()
    mock_bucket.collections.return_value = mock_collections_mgr

    # Mock the exists method to return True
    with patch.object(couchbase_fts, "exists", return_value=True):
        # Test successful drop
        couchbase_fts.drop()
        mock_collections_mgr.drop_collection.assert_called_once_with(
            collection_name=couchbase_fts.collection_name, scope_name=couchbase_fts.scope_name
        )

    # Test when collection doesn't exist
    mock_collections_mgr.drop_collection.reset_mock()
    with patch.object(couchbase_fts, "exists", return_value=False):
        couchbase_fts.drop()
        mock_collections_mgr.drop_collection.assert_not_called()


def test_exists(couchbase_fts, mock_scope):
    # Test collection exists
    assert couchbase_fts.exists() is True

    # Test collection doesn't exist
    mock_scope_without_collection = Mock()
    mock_scope_without_collection.name = "test_scope"
    mock_scope_without_collection.collections = []

    couchbase_fts._bucket.collections().get_all_scopes.return_value = [mock_scope_without_collection]
    assert couchbase_fts.exists() is False

    # Test exception handling
    couchbase_fts._bucket.collections().get_all_scopes.side_effect = Exception("Test error")
    assert couchbase_fts.exists() is False


def test_prepare_doc(couchbase_fts, mock_embedder):
    # Setup
    document = Document(name="test doc", content="test content", meta_data={"key": "value"})

    # Test
    prepared_doc = couchbase_fts.prepare_doc(document)
    assert "_id" in prepared_doc
    assert prepared_doc["name"] == "test doc"
    assert prepared_doc["content"] == "test content"
    assert prepared_doc["meta_data"] == {"key": "value"}
    assert prepared_doc["embedding"] == [0.1, 0.2, 0.3]


def test_get_count(mock_scope, couchbase_fts):
    # Setup
    mock_search_indexes = Mock()
    mock_search_indexes.get_indexed_documents_count.return_value = 42
    mock_scope.search_indexes.return_value = mock_search_indexes

    # Test
    count = couchbase_fts.get_count()
    assert count == 42

    # Test error case
    mock_search_indexes.get_indexed_documents_count.side_effect = Exception()
    count = couchbase_fts.get_count()
    assert count == 0


def test_init_empty_bucket_name():
    with pytest.raises(ValueError, match="Bucket name must not be empty."):
        CouchbaseSearch(
            bucket_name="",
            scope_name="test_scope",
            collection_name="test_collection",
            couchbase_connection_string="couchbase://localhost",
            cluster_options=ClusterOptions(authenticator=PasswordAuthenticator("username", "password")),
            search_index="test_index",
        )


def test_get_cluster_connection_error():
    with patch("agno.vectordb.couchbase.couchbase.Cluster") as mock_cluster:
        mock_cluster.side_effect = Exception("Connection failed")

        with pytest.raises(ConnectionError, match="Failed to connect to Couchbase"):
            couchbase_fts = CouchbaseSearch(
                bucket_name="test_bucket",
                scope_name="test_scope",
                collection_name="test_collection",
                couchbase_connection_string="couchbase://localhost",
                cluster_options=ClusterOptions(authenticator=PasswordAuthenticator("username", "password")),
                search_index="test_index",
            )
            couchbase_fts.create()


def test_get_bucket_not_exists(mock_cluster):
    mock_cluster.bucket.side_effect = BucketDoesNotExistException("Bucket does not exist")

    with pytest.raises(BucketDoesNotExistException):
        couchbase_fts = CouchbaseSearch(
            bucket_name="nonexistent_bucket",
            scope_name="test_scope",
            collection_name="test_collection",
            couchbase_connection_string="couchbase://localhost",
            cluster_options=ClusterOptions(authenticator=PasswordAuthenticator("username", "password")),
            search_index="test_index",
        )
        couchbase_fts.create()


def test_create_scope_collection_exists(couchbase_fts, mock_bucket):
    # Mock the collections().get_all_scopes() to return a scope with the _default name
    mock_bucket.collections().create_scope.side_effect = ScopeAlreadyExistsException("Scope already exists")
    mock_bucket.collections().create_collection.side_effect = CollectionAlreadyExistsException(
        "Collection already exists"
    )
    # Call the method
    couchbase_fts._create_collection_and_scope()

    mock_bucket.collections().create_scope.assert_called_once_with(scope_name=couchbase_fts.scope_name)
    mock_bucket.collections().create_collection.assert_called_once_with(
        collection_name=couchbase_fts.collection_name, scope_name=couchbase_fts.scope_name
    )


def test_create_scope_error(couchbase_fts, mock_bucket):
    # Then make the create_scope method raise an exception
    mock_bucket.collections().create_scope.side_effect = Exception("Creation error")

    # Test that the exception is propagated
    with pytest.raises(Exception, match="Creation error"):
        couchbase_fts._create_collection_and_scope()


def test_create_collection_with_overwrite(couchbase_fts_overwrite, mock_bucket, mock_scope):
    # Test collection creation with overwrite=True
    couchbase_fts_overwrite._create_collection_and_scope()
    collections_mgr = mock_bucket.collections.return_value

    collections_mgr.create_scope.assert_called_once_with(scope_name=couchbase_fts_overwrite.scope_name)
    # Assert that the collection was dropped and created
    collections_mgr.drop_collection.assert_called_once_with(
        collection_name=couchbase_fts_overwrite.collection_name, scope_name=couchbase_fts_overwrite.scope_name
    )
    collections_mgr.create_collection.assert_called_once_with(
        collection_name=couchbase_fts_overwrite.collection_name, scope_name=couchbase_fts_overwrite.scope_name
    )


def test_create_fts_index_with_overwrite(couchbase_fts_overwrite, mock_scope):
    # Setup mock before calling create()
    mock_search_indexes = Mock()
    mock_scope.search_indexes.return_value = mock_search_indexes

    # Now call create()
    couchbase_fts_overwrite.create()

    # Assert
    mock_search_indexes.drop_index.assert_called_once_with(couchbase_fts_overwrite.search_index_name)
    mock_search_indexes.upsert_index.assert_called_once_with(couchbase_fts_overwrite.search_index_definition)


def test_wait_for_index_ready_timeout(couchbase_fts, mock_cluster):
    # Test timeout while waiting for index
    couchbase_fts.wait_until_index_ready = 0.1  # Short timeout for test
    mock_search_indexes = Mock()
    mock_index = Mock()
    mock_index.plan_params.num_replicas = 2
    mock_index.plan_params.num_replicas_actual = 1  # Not ready
    mock_search_indexes.get_index.return_value = mock_index
    mock_cluster.search_indexes.return_value = mock_search_indexes

    with pytest.raises(TimeoutError, match="Timeout waiting for FTS index to become ready"):
        couchbase_fts._wait_for_index_ready()


def test_name_exists(couchbase_fts, mock_scope):
    # Test document exists by name
    mock_rows = [{"name": "test_doc"}]
    mock_result = Mock()
    mock_result.rows.return_value = mock_rows
    mock_scope.query.return_value = mock_result

    assert couchbase_fts.name_exists("test_doc") is True

    # Test document doesn't exist
    mock_result.rows.return_value = []
    assert couchbase_fts.name_exists("nonexistent_doc") is False

    # Test query error
    mock_scope.query.side_effect = Exception("Query error")
    assert couchbase_fts.name_exists("test_doc") is False


def test_id_exists(couchbase_fts, mock_collection):
    # Test document exists by ID
    mock_exists_result = Mock()
    mock_exists_result.exists = True
    mock_collection.exists.return_value = mock_exists_result

    assert couchbase_fts.id_exists("test_id") is True

    # Test document doesn't exist
    mock_exists_result.exists = False
    assert couchbase_fts.id_exists("test_id") is False

    # Test exception handling
    mock_collection.exists.side_effect = Exception("Test error")
    assert couchbase_fts.id_exists("test_id") is False


def test_create_fts_index_cluster_level(mock_cluster, mock_embedder):
    """Test creating FTS index at cluster level with overwrite."""
    # Setup mock search indexes manager
    mock_search_indexes = Mock()
    mock_cluster.search_indexes.return_value = mock_search_indexes

    # Mock bucket and collections
    mock_bucket = Mock(spec=Bucket)
    mock_cluster.bucket.return_value = mock_bucket

    # Mock collections manager
    collections_manager = Mock()
    mock_bucket.collections.return_value = collections_manager

    # Mock scope
    mock_scope = Mock(spec=Scope)
    mock_scope.name = "test_scope"
    mock_bucket.scope.return_value = mock_scope

    # Mock collection
    mock_collection = Mock(spec=Collection)
    mock_collection.name = "test_collection"
    mock_scope.collection.return_value = mock_collection

    # Set up the scope to have the collection
    mock_scope.collections = [mock_collection]

    # Set up the collections manager to return scopes
    collections_manager.get_all_scopes.return_value = [mock_scope]

    # Create CouchbaseSearch instance with cluster-level index
    fts = CouchbaseSearch(
        bucket_name="test_bucket",
        scope_name="test_scope",
        collection_name="test_collection",
        couchbase_connection_string="couchbase://localhost",
        cluster_options=ClusterOptions(
            authenticator=PasswordAuthenticator("username", "password"),
        ),
        overwrite=True,
        is_global_level_index=True,  # Enable cluster-level index
        search_index=SearchIndex(
            name="test_index",
            source_type="couchbase",
            idx_type="fulltext-index",
            source_name="test_collection",
            uuid="test_uuid",
            params={},
            source_uuid="test_uuid",
            source_params={},
            plan_params={},
        ),
        embedder=mock_embedder,
    )

    # Call create to trigger index creation
    fts.create()

    # Verify cluster-level search indexes were used
    assert mock_cluster.search_indexes.call_count >= 1

    # Verify index was dropped and recreated
    mock_search_indexes.drop_index.assert_called_once_with("test_index")
    mock_search_indexes.upsert_index.assert_called_once()

    # Verify the index definition was passed to upsert
    upsert_call = mock_search_indexes.upsert_index.call_args[0][0]
    assert isinstance(upsert_call, SearchIndex)
    assert upsert_call.name == "test_index"


def test_get_count_cluster_level(mock_cluster, mock_embedder):
    """Test getting document count from cluster-level index."""
    # Setup mock search indexes manager
    mock_search_indexes = Mock()
    mock_search_indexes.get_indexed_documents_count.return_value = 42
    mock_cluster.search_indexes.return_value = mock_search_indexes

    # Create CouchbaseSearch instance with cluster-level index
    fts = CouchbaseSearch(
        bucket_name="test_bucket",
        scope_name="test_scope",
        collection_name="test_collection",
        couchbase_connection_string="couchbase://localhost",
        cluster_options=ClusterOptions(
            authenticator=PasswordAuthenticator("username", "password"),
        ),
        is_global_level_index=True,  # Enable cluster-level index
        search_index="test_index",
        embedder=mock_embedder,
    )

    # Get count
    count = fts.get_count()

    # Verify cluster-level search indexes were used
    mock_cluster.search_indexes.assert_called_once()

    # Verify count was retrieved from cluster-level index
    mock_search_indexes.get_indexed_documents_count.assert_called_once_with("test_index")
    assert count == 42


def test_search_cluster_level(mock_cluster, mock_embedder):
    """Test searching with cluster-level index."""
    # Setup mock search result
    mock_search_result = Mock()
    mock_row = Mock()
    mock_row.id = "test_id"
    mock_row.score = 0.95
    mock_search_result.rows.return_value = [mock_row]
    mock_cluster.search.return_value = mock_search_result

    # Setup mock KV response
    mock_collection = Mock(spec=Collection)
    mock_get_result = Mock(spec=GetResult)
    mock_get_result.value = {
        "name": "test doc",
        "content": "test content",
        "meta_data": {},
        "embedding": [0.1, 0.2, 0.3],
    }
    mock_get_result.success = True
    mock_kv_response = Mock()
    mock_kv_response.all_ok = True
    mock_kv_response.results = {"test_id": mock_get_result}
    mock_collection.get_multi.return_value = mock_kv_response

    # Create CouchbaseSearch instance with cluster-level index
    fts = CouchbaseSearch(
        bucket_name="test_bucket",
        scope_name="test_scope",
        collection_name="test_collection",
        couchbase_connection_string="couchbase://localhost",
        cluster_options=ClusterOptions(
            authenticator=PasswordAuthenticator("username", "password"),
        ),
        is_global_level_index=True,  # Enable cluster-level index
        search_index="test_index",
        embedder=mock_embedder,
    )
    fts._collection = mock_collection
    fts._cluster = mock_cluster

    # Perform search
    results = fts.search("test query", limit=5)

    # Verify cluster-level search was used
    mock_cluster.search.assert_called_once()

    # Verify results
    assert len(results) == 1
    assert isinstance(results[0], Document)
    assert results[0].id == "test_id"
    assert results[0].name == "test doc"


@pytest.mark.asyncio
async def test_async_create(couchbase_fts):
    """Test the async_create method."""
    with patch.object(
        couchbase_fts, "_async_create_collection_and_scope", new_callable=AsyncMock
    ) as mock_create_coll_scope, patch.object(
        couchbase_fts, "_async_create_fts_index", new_callable=AsyncMock
    ) as mock_create_fts:
        await couchbase_fts.async_create()
        mock_create_coll_scope.assert_called_once()
        mock_create_fts.assert_called_once()


@pytest.mark.asyncio
async def test_async_doc_exists(couchbase_fts):
    """Test the async_doc_exists method."""
    document = Document(content="test content")

    # Mock async_id_exists method
    with patch.object(couchbase_fts, "async_id_exists", new_callable=AsyncMock) as mock_async_id_exists:
        # Test document exists
        mock_async_id_exists.return_value = True
        assert await couchbase_fts.async_doc_exists(document) is True
        mock_async_id_exists.assert_called_once()

        # Test document doesn't exist
        mock_async_id_exists.return_value = False
        # Reset call count for the next assertion
        mock_async_id_exists.reset_mock()
        assert await couchbase_fts.async_doc_exists(document) is False
        mock_async_id_exists.assert_called_once()


@pytest.mark.asyncio
async def test_async_id_exists(couchbase_fts):
    """Test the async_id_exists method."""
    mock_collection_inst = AsyncMock(spec=AsyncCollection)
    mock_get_result = Mock()
    mock_collection_inst.exists = AsyncMock(return_value=mock_get_result)

    with patch.object(CouchbaseSearch, "get_async_collection", new_callable=AsyncMock) as mock_get_async_collection:
        mock_get_async_collection.return_value = mock_collection_inst

        mock_get_result.exists = True
        assert await couchbase_fts.async_id_exists("test_id") is True
        mock_collection_inst.exists.assert_called_once_with("test_id")

        mock_get_result.exists = False
        mock_collection_inst.exists.reset_mock()
        assert await couchbase_fts.async_id_exists("test_id") is False
        mock_collection_inst.exists.assert_called_once_with("test_id")

        mock_collection_inst.exists.reset_mock()
        mock_collection_inst.exists.side_effect = Exception("Test error")
        assert await couchbase_fts.async_id_exists("test_id") is False
        mock_collection_inst.exists.assert_called_once_with("test_id")


@pytest.mark.asyncio
async def test_async_name_exists(couchbase_fts):
    """Test the async_name_exists method."""
    mock_scope_inst = AsyncMock(spec=AsyncScope)
    mock_query_result = Mock()
    # query method on AsyncScope is synchronous and returns an object with an async rows() iterator
    mock_scope_inst.query = Mock(return_value=mock_query_result)

    with patch.object(CouchbaseSearch, "get_async_scope", new_callable=AsyncMock) as mock_get_async_scope:
        mock_get_async_scope.return_value = mock_scope_inst

        async def mock_rows_found():
            yield {"name": "test_doc"}

        mock_query_result.rows = mock_rows_found

        assert await couchbase_fts.async_name_exists("test_doc") is True
        mock_scope_inst.query.assert_called_once()

        async def mock_rows_not_found():
            if False:  # pragma: no cover
                yield

        mock_query_result.rows = mock_rows_not_found
        mock_scope_inst.query.reset_mock()
        assert await couchbase_fts.async_name_exists("nonexistent_doc") is False
        mock_scope_inst.query.assert_called_once()

        mock_scope_inst.query.reset_mock()
        mock_scope_inst.query.side_effect = Exception("Query error")
        assert await couchbase_fts.async_name_exists("test_doc") is False
        mock_scope_inst.query.assert_called_once()


@pytest.mark.asyncio
async def test_async_insert(couchbase_fts, mock_embedder):
    """Test the async_insert method with batched concurrent inserts."""
    documents = [Document(name="doc1", content="content1"), Document(name="doc2", content="content2")]
    filters = {"category": "test", "priority": "high"}

    mock_async_collection_instance = AsyncMock(spec=AsyncCollection)
    mock_async_collection_instance.insert = AsyncMock(return_value=None)

    with patch.object(
        couchbase_fts, "get_async_collection", AsyncMock(return_value=mock_async_collection_instance)
    ) as mock_get_async_collection:
        # Test case 1: without filters - documents should be embedded
        await couchbase_fts.async_insert(copy.deepcopy(documents))

        mock_get_async_collection.assert_called_once()
        assert mock_embedder.get_embedding_and_usage.call_count == len(documents)
        assert mock_async_collection_instance.insert.call_count == len(documents)

        first_call_args = mock_async_collection_instance.insert.call_args_list[0].args
        assert isinstance(first_call_args[0], str)
        assert first_call_args[1]["name"] == documents[0].name
        assert "filters" not in first_call_args[1]

        # Reset mocks for the next call
        mock_get_async_collection.reset_mock()
        mock_async_collection_instance.insert.reset_mock()
        mock_embedder.get_embedding_and_usage.reset_mock()

        # Test case 2: with filters - documents already have embeddings, so embedder should not be called again
        await couchbase_fts.async_insert(copy.deepcopy(documents), filters=filters)
        mock_get_async_collection.assert_called_once()
        assert mock_embedder.get_embedding_and_usage.call_count == len(documents)
        assert mock_async_collection_instance.insert.call_count == len(documents)

        first_call_args_filtered = mock_async_collection_instance.insert.call_args_list[0].args
        assert isinstance(first_call_args_filtered[0], str)
        assert first_call_args_filtered[1]["name"] == documents[0].name
        assert first_call_args_filtered[1]["filters"] == filters


@pytest.mark.asyncio
async def test_async_upsert(couchbase_fts, mock_embedder):
    """Test the async_upsert method with batched concurrent upserts."""
    documents = [Document(name="doc1", content="content1"), Document(name="doc2", content="content2")]
    filters = {"category": "test", "priority": "high"}

    mock_async_collection_instance = AsyncMock(spec=AsyncCollection)
    mock_async_collection_instance.upsert = AsyncMock(return_value=None)

    with patch.object(
        couchbase_fts, "get_async_collection", AsyncMock(return_value=mock_async_collection_instance)
    ) as mock_get_async_collection:
        # Test case 1: without filters - documents should be embedded
        await couchbase_fts.async_upsert(copy.deepcopy(documents))

        mock_get_async_collection.assert_called_once()
        assert mock_embedder.get_embedding_and_usage.call_count == len(documents)
        assert mock_async_collection_instance.upsert.call_count == len(documents)

        first_call_args = mock_async_collection_instance.upsert.call_args_list[0].args
        assert isinstance(first_call_args[0], str)
        assert first_call_args[1]["name"] == documents[0].name
        assert "filters" not in first_call_args[1]

        # Reset mocks for the next call
        mock_get_async_collection.reset_mock()
        mock_async_collection_instance.upsert.reset_mock()
        mock_embedder.get_embedding_and_usage.reset_mock()

        # Test case 2: with filters - documents already have embeddings, so embedder should not be called again
        await couchbase_fts.async_upsert(copy.deepcopy(documents), filters=filters)
        mock_get_async_collection.assert_called_once()
        assert mock_embedder.get_embedding_and_usage.call_count == len(documents)  # Embedder not called again
        assert mock_async_collection_instance.upsert.call_count == len(documents)

        first_call_args_filtered = mock_async_collection_instance.upsert.call_args_list[0].args
        assert isinstance(first_call_args_filtered[0], str)
        assert first_call_args_filtered[1]["name"] == documents[0].name
        assert first_call_args_filtered[1]["filters"] == filters


@pytest.mark.asyncio
async def test_async_search_scope_level(couchbase_fts, mock_embedder):
    """Test async_search with scope-level index and new __async_get_doc_from_kv logic."""
    mock_scope_inst = AsyncMock(spec=AsyncScope)
    mock_search_result_obj = Mock()  # Represents the synchronous SearchResult object
    mock_search_row = Mock()
    mock_search_row.id = "test_id_scope_search"
    mock_search_row.score = 0.95

    # Patch rows to return an async iterator
    async def async_rows():
        yield mock_search_row

    mock_search_result_obj.rows = async_rows  # <-- Fix: assign the async generator function directly
    mock_scope_inst.search = Mock(return_value=mock_search_result_obj)

    # Mocking for __async_get_doc_from_kv internal calls
    mock_async_collection_instance = AsyncMock(spec=AsyncCollection)
    mock_get_result_kv = AsyncMock(spec=GetResult)  # Use AsyncMock if GetResult itself is async, else Mock
    # Simulate structure returned by acouchbase .get().content_as[dict]
    mock_get_result_kv.content_as = {
        dict: {
            "name": "test doc from kv",
            "content": "test content from kv",
            "meta_data": {"source": "kv_scope"},
            "embedding": [0.1, 0.2, 0.3],
        }
    }
    # mock_get_result_kv.success = True # Not directly used by new logic, absence of exception is success
    mock_async_collection_instance.get = AsyncMock(return_value=mock_get_result_kv)

    with patch.object(
        couchbase_fts, "get_async_scope", AsyncMock(return_value=mock_scope_inst)
    ) as mock_get_async_scope, patch.object(
        couchbase_fts, "get_async_collection", AsyncMock(return_value=mock_async_collection_instance)
    ) as mock_get_async_collection_for_kv:
        couchbase_fts.is_global_level_index = False  # Ensure scope level search

        results = await couchbase_fts.async_search("test query scope kv", limit=5)

        mock_embedder.get_embedding.assert_called_once_with("test query scope kv")
        mock_get_async_scope.assert_called_once()  # For the search part
        mock_scope_inst.search.assert_called_once()
        search_args, search_kwargs = mock_scope_inst.search.call_args
        assert search_kwargs["options"]["limit"] == 5

        # __async_get_doc_from_kv will call get_async_collection then .get for each doc
        mock_get_async_collection_for_kv.assert_called_once()
        mock_async_collection_instance.get.assert_called_once_with(mock_search_row.id)

        assert len(results) == 1
        assert results[0].id == mock_search_row.id
        assert results[0].name == "test doc from kv"
        assert results[0].meta_data == {"source": "kv_scope"}

        # Reset mocks for filter test
        mock_embedder.get_embedding.reset_mock()
        mock_get_async_scope.reset_mock()
        mock_scope_inst.search.reset_mock()
        mock_get_async_collection_for_kv.reset_mock()
        mock_async_collection_instance.get.reset_mock()

        filters = {"category": "test_scope_kv"}
        results_with_filters = await couchbase_fts.async_search("test query filter scope kv", limit=5, filters=filters)

        mock_embedder.get_embedding.assert_called_once_with("test query filter scope kv")
        mock_get_async_scope.assert_called_once()
        mock_scope_inst.search.assert_called_once()
        search_args_f, search_kwargs_f = mock_scope_inst.search.call_args
        assert search_kwargs_f["options"]["limit"] == 5
        assert search_kwargs_f["options"]["raw"] == filters

        mock_get_async_collection_for_kv.assert_called_once()
        mock_async_collection_instance.get.assert_called_once_with(mock_search_row.id)
        assert len(results_with_filters) == 1


@pytest.mark.asyncio
async def test_async_search_cluster_level(couchbase_fts, mock_embedder):
    """Test async_search with cluster-level index and new __async_get_doc_from_kv logic."""
    mock_cluster_inst = AsyncMock(spec=AsyncCluster)
    mock_search_result_obj = Mock()
    mock_search_row = Mock()
    mock_search_row.id = "test_id_cluster_search"
    mock_search_row.score = 0.90

    # Patch rows to return an async iterator
    async def async_rows():
        yield mock_search_row

    mock_search_result_obj.rows = async_rows  # <-- Fix: assign the async generator function directly
    mock_cluster_inst.search = Mock(return_value=mock_search_result_obj)

    # Mocking for __async_get_doc_from_kv internal calls
    mock_async_collection_instance = AsyncMock(spec=AsyncCollection)
    mock_get_result_kv = AsyncMock(spec=GetResult)
    mock_get_result_kv.content_as = {
        dict: {
            "name": "cluster test doc from kv",
            "content": "cluster test content from kv",
            "meta_data": {"source": "kv_cluster"},
            "embedding": [0.4, 0.5, 0.6],
        }
    }
    mock_async_collection_instance.get = AsyncMock(return_value=mock_get_result_kv)

    # Instead of mocking mock_async_cluster fixture, we patch get_async_cluster on the instance
    with patch.object(
        couchbase_fts, "get_async_cluster", AsyncMock(return_value=mock_cluster_inst)
    ) as mock_get_async_cluster_for_search, patch.object(
        couchbase_fts, "get_async_collection", AsyncMock(return_value=mock_async_collection_instance)
    ) as mock_get_async_collection_for_kv:
        couchbase_fts.is_global_level_index = True  # Ensure cluster level search

        results = await couchbase_fts.async_search("cluster query kv", limit=3)

        mock_embedder.get_embedding.assert_called_once_with("cluster query kv")
        mock_get_async_cluster_for_search.assert_called_once()  # For the search part
        mock_cluster_inst.search.assert_called_once()
        search_args, search_kwargs = mock_cluster_inst.search.call_args
        assert search_kwargs["options"]["limit"] == 3

        mock_get_async_collection_for_kv.assert_called_once()
        mock_async_collection_instance.get.assert_called_once_with(mock_search_row.id)

        assert len(results) == 1
        assert results[0].id == mock_search_row.id
        assert results[0].name == "cluster test doc from kv"

        # Reset mocks for filter test (optional, as new instances are created or mocks are fresh per test)
        mock_embedder.get_embedding.reset_mock()
        mock_get_async_cluster_for_search.reset_mock()
        mock_cluster_inst.search.reset_mock()
        mock_get_async_collection_for_kv.reset_mock()
        mock_async_collection_instance.get.reset_mock()

        filters = {"type": "cluster_kv"}
        results_with_filters = await couchbase_fts.async_search("cluster query filter kv", limit=3, filters=filters)

        mock_embedder.get_embedding.assert_called_once_with("cluster query filter kv")
        mock_get_async_cluster_for_search.assert_called_once()
        mock_cluster_inst.search.assert_called_once()
        search_args_f, search_kwargs_f = mock_cluster_inst.search.call_args
        assert search_kwargs_f["options"]["limit"] == 3
        assert search_kwargs_f["options"]["raw"] == filters

        mock_get_async_collection_for_kv.assert_called_once()
        mock_async_collection_instance.get.assert_called_once_with(mock_search_row.id)
        assert len(results_with_filters) == 1


@pytest.mark.asyncio
async def test_async_drop(couchbase_fts):
    """Test the async_drop method."""
    mock_bucket_inst = AsyncMock(spec=AsyncBucket)
    mock_collections_mgr = AsyncMock()  # This is the collections manager object
    mock_bucket_inst.collections = Mock(return_value=mock_collections_mgr)  # .collections() is sync
    mock_collections_mgr.drop_collection = AsyncMock()  # .drop_collection() on manager is async

    with patch.object(CouchbaseSearch, "get_async_bucket", new_callable=AsyncMock) as mock_get_async_bucket:
        mock_get_async_bucket.return_value = mock_bucket_inst

        with patch.object(couchbase_fts, "async_exists", AsyncMock(return_value=True)) as mock_async_exists:
            await couchbase_fts.async_drop()
            mock_async_exists.assert_called_once()
            mock_get_async_bucket.assert_called_once()
            mock_bucket_inst.collections.assert_called_once()  # Verifies collections manager was obtained
            mock_collections_mgr.drop_collection.assert_called_once_with(
                collection_name=couchbase_fts.collection_name, scope_name=couchbase_fts.scope_name
            )

        # Reset mocks for "not exists" case
        mock_get_async_bucket.reset_mock()
        mock_bucket_inst.collections.reset_mock()
        mock_collections_mgr.drop_collection.reset_mock()
        with patch.object(couchbase_fts, "async_exists", AsyncMock(return_value=False)) as mock_async_exists:
            await couchbase_fts.async_drop()
            mock_async_exists.assert_called_once()
            mock_get_async_bucket.assert_not_called()  # get_async_bucket should not be called if not exists
            mock_collections_mgr.drop_collection.assert_not_called()

        # Reset mocks for "exception during drop" case
        mock_get_async_bucket.reset_mock()
        mock_bucket_inst.collections.reset_mock()
        mock_collections_mgr.drop_collection.reset_mock()
        mock_collections_mgr.drop_collection.side_effect = Exception("Drop error")
        with patch.object(couchbase_fts, "async_exists", AsyncMock(return_value=True)) as mock_async_exists:
            with pytest.raises(Exception, match="Drop error"):
                await couchbase_fts.async_drop()
            mock_async_exists.assert_called_once()
            mock_get_async_bucket.assert_called_once()
            mock_bucket_inst.collections.assert_called_once()
            mock_collections_mgr.drop_collection.assert_called_once()


@pytest.mark.asyncio
async def test_async_exists(couchbase_fts):
    """Test the async_exists method."""
    mock_bucket_inst = AsyncMock(spec=AsyncBucket)
    mock_collections_mgr = AsyncMock()  # This is the collections manager object
    mock_bucket_inst.collections = Mock(return_value=mock_collections_mgr)  # .collections() is sync

    mock_scope_obj = Mock()
    mock_scope_obj.name = couchbase_fts.scope_name
    mock_collection_obj = Mock()
    mock_collection_obj.name = couchbase_fts.collection_name
    mock_scope_obj.collections = [mock_collection_obj]  # collections on a scope object is a list

    with patch.object(CouchbaseSearch, "get_async_bucket", new_callable=AsyncMock) as mock_get_async_bucket:
        mock_get_async_bucket.return_value = mock_bucket_inst

        # Case 1: Collection exists
        mock_collections_mgr.get_all_scopes = AsyncMock(return_value=[mock_scope_obj])  # get_all_scopes is async
        assert await couchbase_fts.async_exists() is True
        mock_get_async_bucket.assert_called_once()
        mock_bucket_inst.collections.assert_called_once()
        mock_collections_mgr.get_all_scopes.assert_called_once()

        # Reset mocks for subsequent cases
        mock_get_async_bucket.reset_mock()
        mock_bucket_inst.collections.reset_mock()
        mock_collections_mgr.get_all_scopes.reset_mock()

        # Case 2: Collection does not exist (different collection name)
        mock_other_collection = Mock()
        mock_other_collection.name = "other_collection"
        mock_scope_obj_with_other_coll = Mock()
        mock_scope_obj_with_other_coll.name = couchbase_fts.scope_name
        mock_scope_obj_with_other_coll.collections = [mock_other_collection]
        mock_collections_mgr.get_all_scopes = AsyncMock(return_value=[mock_scope_obj_with_other_coll])
        assert await couchbase_fts.async_exists() is False
        mock_get_async_bucket.assert_called_once()
        mock_bucket_inst.collections.assert_called_once()
        mock_collections_mgr.get_all_scopes.assert_called_once()

        mock_get_async_bucket.reset_mock()
        mock_bucket_inst.collections.reset_mock()
        mock_collections_mgr.get_all_scopes.reset_mock()

        # Case 3: Scope does not exist
        mock_other_scope = Mock()
        mock_other_scope.name = "other_scope"
        mock_other_scope.collections = [mock_collection_obj]  # Doesn't matter as scope name won't match
        mock_collections_mgr.get_all_scopes = AsyncMock(return_value=[mock_other_scope])
        assert await couchbase_fts.async_exists() is False
        mock_get_async_bucket.assert_called_once()
        mock_bucket_inst.collections.assert_called_once()
        mock_collections_mgr.get_all_scopes.assert_called_once()

        mock_get_async_bucket.reset_mock()
        mock_bucket_inst.collections.reset_mock()
        mock_collections_mgr.get_all_scopes.reset_mock()

        # Case 4: Exception during get_all_scopes
        mock_collections_mgr.get_all_scopes.side_effect = Exception("Test error")
        assert await couchbase_fts.async_exists() is False  # Should return False on error
        mock_get_async_bucket.assert_called_once()
        mock_bucket_inst.collections.assert_called_once()
        mock_collections_mgr.get_all_scopes.assert_called_once()


@pytest.mark.asyncio
async def test_async_cluster_property_caching(couchbase_fts, mock_async_cluster):
    """Test the async_cluster property caching mechanism."""
    # Get the first instance
    cluster_instance_1 = await couchbase_fts.get_async_cluster()

    # mock_async_cluster is a mock of the AsyncCluster *class*
    # mock_async_cluster.connect is the mocked connect class method
    mock_async_cluster.connect.assert_called_once_with(couchbase_fts.connection_string, couchbase_fts.cluster_options)

    # The instance returned by connect() is what's cached
    mock_returned_cluster_instance = mock_async_cluster.connect.return_value
    assert couchbase_fts._async_cluster is cluster_instance_1
    assert cluster_instance_1 is mock_returned_cluster_instance

    # Get the second instance
    cluster_instance_2 = await couchbase_fts.get_async_cluster()

    # connect should still only be called once due to caching
    mock_async_cluster.connect.assert_called_once()
    assert cluster_instance_2 is cluster_instance_1


@pytest.mark.asyncio
async def test_async_bucket_property_caching(couchbase_fts):
    """Test the async_bucket property caching mechanism."""
    mock_cluster_inst = AsyncMock(spec=AsyncCluster)
    mock_bucket_inst = AsyncMock()
    mock_cluster_inst.bucket = Mock(return_value=mock_bucket_inst)

    with patch.object(CouchbaseSearch, "get_async_cluster", new_callable=AsyncMock) as mock_get_async_cluster:
        mock_get_async_cluster.return_value = mock_cluster_inst

        bucket1 = await couchbase_fts.get_async_bucket()
        mock_get_async_cluster.assert_called_once()
        mock_cluster_inst.bucket.assert_called_once_with(couchbase_fts.bucket_name)
        assert bucket1 is mock_bucket_inst
        assert couchbase_fts._async_bucket is bucket1

        # Clear mocks for the second call to ensure caching prevents re-calls
        mock_get_async_cluster.reset_mock()
        mock_cluster_inst.bucket.reset_mock()

        bucket2 = await couchbase_fts.get_async_bucket()
        mock_get_async_cluster.assert_not_called()  # Should not call get_async_cluster again
        mock_cluster_inst.bucket.assert_not_called()  # Should not call bucket on cluster again
        assert bucket2 is bucket1


@pytest.mark.asyncio
async def test_async_scope_property_caching(couchbase_fts):
    """Test the async_scope property caching mechanism."""
    mock_bucket_inst = AsyncMock(spec=AsyncBucket)  # Use AsyncBucket spec
    mock_scope_inst = AsyncMock(spec=AsyncScope)  # Use AsyncScope spec
    mock_bucket_inst.scope = Mock(return_value=mock_scope_inst)  # scope is a sync method returning AsyncScope

    with patch.object(CouchbaseSearch, "get_async_bucket", new_callable=AsyncMock) as mock_get_async_bucket:
        mock_get_async_bucket.return_value = mock_bucket_inst

        scope1 = await couchbase_fts.get_async_scope()
        mock_get_async_bucket.assert_called_once()
        mock_bucket_inst.scope.assert_called_once_with(couchbase_fts.scope_name)
        assert scope1 is mock_scope_inst
        assert couchbase_fts._async_scope is scope1

        # Clear mocks for the second call
        mock_get_async_bucket.reset_mock()
        mock_bucket_inst.scope.reset_mock()

        scope2 = await couchbase_fts.get_async_scope()
        mock_get_async_bucket.assert_not_called()
        mock_bucket_inst.scope.assert_not_called()
        assert scope2 is scope1


@pytest.mark.asyncio
async def test_async_collection_property_caching(couchbase_fts):
    """Test the async_collection property caching mechanism."""
    mock_scope_inst = AsyncMock(spec=AsyncScope)  # Use AsyncScope spec
    mock_collection_inst = AsyncMock(spec=AsyncCollection)  # Use AsyncCollection spec
    mock_scope_inst.collection = Mock(return_value=mock_collection_inst)  # collection is a sync method

    with patch.object(CouchbaseSearch, "get_async_scope", new_callable=AsyncMock) as mock_get_async_scope:
        mock_get_async_scope.return_value = mock_scope_inst

        collection1 = await couchbase_fts.get_async_collection()
        mock_get_async_scope.assert_called_once()
        mock_scope_inst.collection.assert_called_once_with(couchbase_fts.collection_name)
        assert collection1 is mock_collection_inst
        assert couchbase_fts._async_collection is collection1

        # Clear mocks for the second call
        mock_get_async_scope.reset_mock()
        mock_scope_inst.collection.reset_mock()

        collection2 = await couchbase_fts.get_async_collection()
        mock_get_async_scope.assert_not_called()
        mock_scope_inst.collection.assert_not_called()
        assert collection2 is collection1
