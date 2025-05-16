from unittest.mock import Mock, patch

import pytest
from couchbase.auth import PasswordAuthenticator
from couchbase.bucket import Bucket
from couchbase.cluster import Cluster
from couchbase.collection import Collection
from couchbase.exceptions import BucketDoesNotExistException
from couchbase.management.search import SearchIndex
from couchbase.options import ClusterOptions
from couchbase.result import GetResult, MultiMutationResult
from couchbase.scope import Scope

from agno.document import Document
from agno.vectordb.couchbase.couchbase import CouchbaseSearch, OpenAIEmbedder


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
    fts.create()
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


def test_search(couchbase_fts, mock_scope):
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
    couchbase_fts._collection.get_multi.return_value = mock_kv_response
    
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
    with patch.object(couchbase_fts, 'exists', return_value=True):
        # Test successful drop
        couchbase_fts.drop()
        mock_collections_mgr.drop_collection.assert_called_once_with(
            collection_name=couchbase_fts.collection_name, scope_name=couchbase_fts.scope_name
        )
    
    # Test when collection doesn't exist
    mock_collections_mgr.drop_collection.reset_mock()
    with patch.object(couchbase_fts, 'exists', return_value=False):
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
            CouchbaseSearch(
                bucket_name="test_bucket",
                scope_name="test_scope",
                collection_name="test_collection",
                couchbase_connection_string="couchbase://localhost",
                cluster_options=ClusterOptions(authenticator=PasswordAuthenticator("username", "password")),
                search_index="test_index",
            )


def test_get_bucket_not_exists(mock_cluster):
    mock_cluster.bucket.side_effect = BucketDoesNotExistException("Bucket does not exist")

    with pytest.raises(BucketDoesNotExistException):
        CouchbaseSearch(
            bucket_name="nonexistent_bucket",
            scope_name="test_scope",
            collection_name="test_collection",
            couchbase_connection_string="couchbase://localhost",
            cluster_options=ClusterOptions(authenticator=PasswordAuthenticator("username", "password")),
            search_index="test_index",
        )


def test_create_scope_default(couchbase_fts, mock_bucket):
    # Test with _default scope
    couchbase_fts.scope_name = "_default"
    
    # Mock the collections().get_all_scopes() to return a scope with the _default name
    mock_scope = Mock()
    mock_scope.name = "_default"
    mock_scope.collections = []
    mock_bucket.collections().get_all_scopes.return_value = [mock_scope]
    
    # Call the method
    collection = couchbase_fts._get_or_create_collection_and_scope()
    
    # Verify that create_scope was not called
    mock_bucket.collections().create_scope.assert_not_called()
    
    # Verify that the correct collection was returned
    assert collection == mock_bucket.scope().collection()


def test_create_scope_error(couchbase_fts, mock_bucket):
    # Test scope creation error
    # First, make it look like the scope doesn't exist
    mock_bucket.collections().get_all_scopes.return_value = []
    
    # Then make the create_scope method raise an exception
    mock_bucket.collections().create_scope.side_effect = Exception("Creation error")
    
    # Test that the exception is propagated
    with pytest.raises(Exception, match="Creation error"):
        couchbase_fts._get_or_create_collection_and_scope()


def test_create_collection_with_overwrite(couchbase_fts_overwrite, mock_bucket, mock_scope):
    # Test collection creation with overwrite=True
    couchbase_fts_overwrite.create()
    collections_mgr = mock_bucket.collections.return_value

    collections_mgr.drop_collection.assert_called_once_with(
        collection_name=couchbase_fts_overwrite.collection_name, scope_name=couchbase_fts_overwrite.scope_name
    )
    collections_mgr.create_collection.assert_called_once()


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
