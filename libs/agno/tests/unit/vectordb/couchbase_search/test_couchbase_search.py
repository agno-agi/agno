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

from agno.knowledge.document import Document
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.filters import AND, EQ, GT, IN, LT, NOT, OR
from agno.vectordb.couchbase.couchbase import (
    CouchbaseSearch,
    _convert_filter_expr_to_sql,
)


# -------------------------------------------------
# Shared Fixtures (duplicated for isolation)
# -------------------------------------------------

@pytest.fixture
def mock_async_cluster():
    with patch("agno.vectordb.couchbase.couchbase.AsyncCluster") as MockAsyncClusterClass:
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
    with patch("agno.knowledge.embedder.openai.OpenAIEmbedder") as mock_embedder:
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


# -------------------------------------------------
# CouchbaseSearch Tests
# -------------------------------------------------

def test_init(couchbase_fts):
    assert couchbase_fts.bucket_name == "test_bucket"
    assert couchbase_fts.scope_name == "test_scope"
    assert couchbase_fts.collection_name == "test_collection"
    assert couchbase_fts.search_index_name == "test_index"


def test_insert(couchbase_fts, mock_collection):
    documents = [Document(content="test content 1"), Document(content="test content 2")]
    mock_result = Mock(spec=MultiMutationResult)
    mock_result.all_ok = True
    mock_collection.insert_multi.return_value = mock_result
    couchbase_fts.insert(documents=documents, content_hash="test_hash")
    assert mock_collection.insert_multi.called
    mock_collection.insert_multi.reset_mock()
    filters = {"category": "test", "priority": "high"}
    couchbase_fts.insert(documents=documents, filters=filters, content_hash="test_hash")
    call_args = mock_collection.insert_multi.call_args[0][0]
    for doc_id in call_args:
        assert call_args[doc_id]["filters"] == filters
    mock_result.all_ok = False
    mock_result.exceptions = {"error": "test error"}
    mock_collection.insert_multi.return_value = mock_result
    couchbase_fts.insert(documents=documents, content_hash="test_hash")


def test_upsert(couchbase_fts, mock_collection):
    documents = [Document(content="test content 1"), Document(content="test content 2")]
    mock_result = Mock(spec=MultiMutationResult)
    mock_result.all_ok = True
    mock_collection.upsert_multi.return_value = mock_result
    couchbase_fts.upsert(documents=documents, content_hash="test_hash")
    assert mock_collection.upsert_multi.called
    mock_collection.upsert_multi.reset_mock()
    filters = {"category": "test", "priority": "high"}
    couchbase_fts.upsert(documents=documents, filters=filters, content_hash="test_hash")
    call_args = mock_collection.upsert_multi.call_args[0][0]
    for doc_id in call_args:
        assert call_args[doc_id]["filters"] == filters
    mock_result.all_ok = False
    mock_result.exceptions = {"error": "test error"}
    mock_collection.upsert_multi.return_value = mock_result
    couchbase_fts.upsert(documents=documents, content_hash="test_hash")


def test_search(couchbase_fts, mock_scope, mock_collection):
    mock_search_result = Mock()
    mock_row = Mock()
    mock_row.id = "test_id"
    mock_row.score = 0.95
    mock_search_result.rows.return_value = [mock_row]
    mock_scope.search.return_value = mock_search_result
    mock_get_result = Mock(spec=GetResult)
    mock_get_result.value = {
        "name": "test doc",
        "content": "test content",
        "meta_data": {},
        "embedding": [0.1, 0.2, 0.3],
        "id": "test_id",
    }
    mock_get_result.success = True
    mock_kv_response = Mock()
    mock_kv_response.all_ok = True
    mock_kv_response.results = {"test_id": mock_get_result}
    mock_collection.get_multi.return_value = mock_kv_response
    results = couchbase_fts.search("test query", limit=5)
    assert len(results) == 1 and results[0].id == "test_id"
    filters = {"category": "test"}
    couchbase_fts.search("test query", limit=5, filters=filters)
    assert mock_scope.search.call_count == 2


def test_drop(mock_bucket, couchbase_fts):
    mock_collections_mgr = Mock()
    mock_bucket.collections.return_value = mock_collections_mgr
    with patch.object(couchbase_fts, "exists", return_value=True):
        couchbase_fts.drop()
        mock_collections_mgr.drop_collection.assert_called_once_with(
            collection_name=couchbase_fts.collection_name, scope_name=couchbase_fts.scope_name
        )
    mock_collections_mgr.drop_collection.reset_mock()
    with patch.object(couchbase_fts, "exists", return_value=False):
        couchbase_fts.drop()
        mock_collections_mgr.drop_collection.assert_not_called()


def test_exists(couchbase_fts, mock_scope):
    assert couchbase_fts.exists() is True
    mock_scope_without_collection = Mock()
    mock_scope_without_collection.name = "test_scope"
    mock_scope_without_collection.collections = []
    couchbase_fts._bucket.collections().get_all_scopes.return_value = [mock_scope_without_collection]
    assert couchbase_fts.exists() is False
    couchbase_fts._bucket.collections().get_all_scopes.side_effect = Exception("Test error")
    assert couchbase_fts.exists() is False


def test_prepare_doc(couchbase_fts, mock_embedder):
    document = Document(name="test doc", content="test content", meta_data={"key": "value"})
    prepared_doc = couchbase_fts.prepare_doc(document=document, content_hash="test_hash")
    assert prepared_doc["name"] == "test doc"
    assert prepared_doc["content"] == "test content"
    assert prepared_doc["meta_data"] == {"key": "value"}


def test_get_count(mock_scope, couchbase_fts):
    mock_search_indexes = Mock()
    mock_search_indexes.get_indexed_documents_count.return_value = 42
    mock_scope.search_indexes.return_value = mock_search_indexes
    count = couchbase_fts.get_count()
    assert count == 42
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
    mock_bucket.collections().create_scope.side_effect = ScopeAlreadyExistsException("Scope already exists")
    mock_bucket.collections().create_collection.side_effect = CollectionAlreadyExistsException(
        "Collection already exists"
    )
    couchbase_fts._create_collection_and_scope()
    mock_bucket.collections().create_scope.assert_called_once_with(scope_name=couchbase_fts.scope_name)
    mock_bucket.collections().create_collection.assert_called_once_with(
        collection_name=couchbase_fts.collection_name, scope_name=couchbase_fts.scope_name
    )


def test_create_scope_error(couchbase_fts, mock_bucket):
    mock_bucket.collections().create_scope.side_effect = Exception("Creation error")
    with pytest.raises(Exception, match="Creation error"):
        couchbase_fts._create_collection_and_scope()


def test_create_collection_with_overwrite(couchbase_fts_overwrite, mock_bucket, mock_scope):
    couchbase_fts_overwrite._create_collection_and_scope()
    collections_mgr = mock_bucket.collections.return_value
    collections_mgr.create_scope.assert_called_once_with(scope_name=couchbase_fts_overwrite.scope_name)
    collections_mgr.drop_collection.assert_called_once_with(
        collection_name=couchbase_fts_overwrite.collection_name, scope_name=couchbase_fts_overwrite.scope_name
    )
    collections_mgr.create_collection.assert_called_once_with(
        collection_name=couchbase_fts_overwrite.collection_name, scope_name=couchbase_fts_overwrite.scope_name
    )


def test_create_fts_index_with_overwrite(couchbase_fts_overwrite, mock_scope):
    mock_search_indexes = Mock()
    mock_scope.search_indexes.return_value = mock_search_indexes
    couchbase_fts_overwrite.create()
    mock_search_indexes.drop_index.assert_called_once_with(couchbase_fts_overwrite.search_index_name)
    mock_search_indexes.upsert_index.assert_called_once_with(couchbase_fts_overwrite.search_index_definition)


def test_wait_for_index_ready_timeout(couchbase_fts, mock_cluster):
    couchbase_fts.wait_until_index_ready = 0.1
    mock_search_indexes = Mock()
    mock_index = Mock()
    mock_index.plan_params.num_replicas = 2
    mock_index.plan_params.num_replicas_actual = 1
    mock_search_indexes.get_index.return_value = mock_index
    mock_cluster.search_indexes.return_value = mock_search_indexes
    with pytest.raises(TimeoutError, match="Timeout waiting for FTS index to become ready"):
        couchbase_fts._wait_for_index_ready()


def test_name_exists(couchbase_fts, mock_scope):
    mock_rows = [{"name": "test_doc"}]
    mock_result = Mock()
    mock_result.rows.return_value = mock_rows
    mock_scope.query.return_value = mock_result
    assert couchbase_fts.name_exists("test_doc") is True
    mock_result.rows.return_value = []
    assert couchbase_fts.name_exists("nonexistent_doc") is False
    mock_scope.query.side_effect = Exception("Query error")
    assert couchbase_fts.name_exists("test_doc") is False


def test_id_exists(couchbase_fts, mock_collection):
    mock_exists_result = Mock()
    mock_exists_result.exists = True
    mock_collection.exists.return_value = mock_exists_result
    assert couchbase_fts.id_exists("test_id") is True
    mock_exists_result.exists = False
    assert couchbase_fts.id_exists("test_id") is False
    mock_collection.exists.side_effect = Exception("Test error")
    assert couchbase_fts.id_exists("test_id") is False


def test_create_fts_index_cluster_level(mock_cluster, mock_embedder):
    mock_search_indexes = Mock()
    mock_cluster.search_indexes.return_value = mock_search_indexes
    mock_bucket = Mock(spec=Bucket)
    mock_cluster.bucket.return_value = mock_bucket
    collections_manager = Mock()
    mock_bucket.collections.return_value = collections_manager
    mock_scope = Mock(spec=Scope)
    mock_scope.name = "test_scope"
    mock_bucket.scope.return_value = mock_scope
    mock_collection = Mock(spec=Collection)
    mock_collection.name = "test_collection"
    mock_scope.collection.return_value = mock_collection
    mock_scope.collections = [mock_collection]
    collections_manager.get_all_scopes.return_value = [mock_scope]
    fts = CouchbaseSearch(
        bucket_name="test_bucket",
        scope_name="test_scope",
        collection_name="test_collection",
        couchbase_connection_string="couchbase://localhost",
        cluster_options=ClusterOptions(
            authenticator=PasswordAuthenticator("username", "password"),
        ),
        overwrite=True,
        is_global_level_index=True,
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
    fts.create()
    mock_search_indexes.drop_index.assert_called_once_with("test_index")
    mock_search_indexes.upsert_index.assert_called_once()
    upsert_call = mock_search_indexes.upsert_index.call_args[0][0]
    assert isinstance(upsert_call, SearchIndex) and upsert_call.name == "test_index"


def test_get_count_cluster_level(mock_cluster, mock_embedder):
    mock_search_indexes = Mock()
    mock_search_indexes.get_indexed_documents_count.return_value = 42
    mock_cluster.search_indexes.return_value = mock_search_indexes
    fts = CouchbaseSearch(
        bucket_name="test_bucket",
        scope_name="test_scope",
        collection_name="test_collection",
        couchbase_connection_string="couchbase://localhost",
        cluster_options=ClusterOptions(
            authenticator=PasswordAuthenticator("username", "password"),
        ),
        is_global_level_index=True,
        search_index="test_index",
        embedder=mock_embedder,
    )
    count = fts.get_count()
    mock_cluster.search_indexes.assert_called_once()
    mock_search_indexes.get_indexed_documents_count.assert_called_once_with("test_index")
    assert count == 42


def test_search_cluster_level(mock_cluster, mock_embedder):
    mock_search_result = Mock()
    mock_row = Mock()
    mock_row.id = "test_id"
    mock_row.score = 0.95
    mock_search_result.rows.return_value = [mock_row]
    mock_cluster.search.return_value = mock_search_result
    mock_collection = Mock(spec=Collection)
    mock_get_result = Mock(spec=GetResult)
    mock_get_result.value = {
        "name": "test doc",
        "content": "test content",
        "meta_data": {},
        "embedding": [0.1, 0.2, 0.3],
        "id": "test_id",
    }
    mock_get_result.success = True
    mock_kv_response = Mock()
    mock_kv_response.all_ok = True
    mock_kv_response.results = {"test_id": mock_get_result}
    mock_collection.get_multi.return_value = mock_kv_response
    fts = CouchbaseSearch(
        bucket_name="test_bucket",
        scope_name="test_scope",
        collection_name="test_collection",
        couchbase_connection_string="couchbase://localhost",
        cluster_options=ClusterOptions(
            authenticator=PasswordAuthenticator("username", "password"),
        ),
        is_global_level_index=True,
        search_index="test_index",
        embedder=mock_embedder,
    )
    fts._collection = mock_collection
    fts._cluster = mock_cluster
    results = fts.search("test query", limit=5)
    mock_cluster.search.assert_called_once()
    assert len(results) == 1 and results[0].id == "test_id"


@pytest.mark.asyncio
async def test_async_create(couchbase_fts):
    with (
        patch.object(couchbase_fts, "_async_create_collection_and_scope", new_callable=AsyncMock) as mock_coll,
        patch.object(couchbase_fts, "_async_create_fts_index", new_callable=AsyncMock) as mock_fts,
    ):
        await couchbase_fts.async_create()
        mock_coll.assert_called_once()
        mock_fts.assert_called_once()


@pytest.mark.asyncio
async def test_async_id_exists(couchbase_fts):
    mock_collection_inst = AsyncMock(spec=AsyncCollection)
    mock_get_result = Mock()
    mock_collection_inst.exists = AsyncMock(return_value=mock_get_result)
    with patch.object(CouchbaseSearch, "get_async_collection", new_callable=AsyncMock) as mock_get_async_collection:
        mock_get_async_collection.return_value = mock_collection_inst
        mock_get_result.exists = True
        assert await couchbase_fts.async_id_exists("test_id") is True
        mock_get_result.exists = False
        mock_collection_inst.exists.reset_mock()
        assert await couchbase_fts.async_id_exists("test_id") is False
        mock_collection_inst.exists.side_effect = Exception("Test error")
        assert await couchbase_fts.async_id_exists("test_id") is False


@pytest.mark.asyncio
async def test_async_name_exists(couchbase_fts):
    mock_scope_inst = AsyncMock(spec=AsyncScope)
    mock_query_result = Mock()
    mock_scope_inst.query = Mock(return_value=mock_query_result)
    with patch.object(CouchbaseSearch, "get_async_scope", new_callable=AsyncMock) as mock_get_async_scope:
        mock_get_async_scope.return_value = mock_scope_inst
        async def rows_found():
            yield {"name": "test_doc"}
        mock_query_result.rows = rows_found
        assert await couchbase_fts.async_name_exists("test_doc") is True
        async def rows_not_found():
            if False:
                yield
        mock_query_result.rows = rows_not_found
        assert await couchbase_fts.async_name_exists("nonexistent_doc") is False
        mock_scope_inst.query.side_effect = Exception("Query error")
        assert await couchbase_fts.async_name_exists("test_doc") is False


@pytest.mark.asyncio
async def test_async_insert(couchbase_fts, mock_embedder):
    documents = [Document(name="doc1", content="content1"), Document(name="doc2", content="content2")]
    filters = {"category": "test", "priority": "high"}
    mock_async_collection_instance = AsyncMock(spec=AsyncCollection)
    mock_async_collection_instance.insert = AsyncMock(return_value=None)
    with patch.object(couchbase_fts, "get_async_collection", AsyncMock(return_value=mock_async_collection_instance)):
        await couchbase_fts.async_insert(documents=copy.deepcopy(documents), content_hash="test_hash")
        await couchbase_fts.async_insert(documents=copy.deepcopy(documents), content_hash="test_hash", filters=filters)


@pytest.mark.asyncio
async def test_async_upsert(couchbase_fts, mock_embedder):
    documents = [Document(name="doc1", content="content1"), Document(name="doc2", content="content2")]
    filters = {"category": "test", "priority": "high"}
    mock_async_collection_instance = AsyncMock(spec=AsyncCollection)
    mock_async_collection_instance.upsert = AsyncMock(return_value=None)
    with patch.object(couchbase_fts, "get_async_collection", AsyncMock(return_value=mock_async_collection_instance)):
        await couchbase_fts.async_upsert(documents=copy.deepcopy(documents), content_hash="test_hash")
        await couchbase_fts.async_upsert(documents=copy.deepcopy(documents), content_hash="test_hash", filters=filters)


@pytest.mark.asyncio
async def test_async_search_scope_level(couchbase_fts, mock_embedder):
    mock_scope_inst = AsyncMock(spec=AsyncScope)
    mock_search_result_obj = Mock()
    mock_search_row = Mock()
    mock_search_row.id = "test_id_scope_search"
    mock_search_row.score = 0.95
    async def async_rows():
        yield mock_search_row
    mock_search_result_obj.rows = async_rows
    mock_scope_inst.search = Mock(return_value=mock_search_result_obj)
    mock_async_collection_instance = AsyncMock(spec=AsyncCollection)
    mock_get_result_kv = AsyncMock(spec=GetResult)
    mock_get_result_kv.content_as = {dict: {"name": "test doc from kv", "content": "test content from kv", "meta_data": {"source": "kv_scope"}, "embedding": [0.1, 0.2, 0.3]}}
    mock_async_collection_instance.get = AsyncMock(return_value=mock_get_result_kv)
    with (
        patch.object(couchbase_fts, "get_async_scope", AsyncMock(return_value=mock_scope_inst)),
        patch.object(couchbase_fts, "get_async_collection", AsyncMock(return_value=mock_async_collection_instance)),
    ):
        couchbase_fts.is_global_level_index = False
        results = await couchbase_fts.async_search("test query scope kv", limit=5)
        assert len(results) == 1 and results[0].id == mock_search_row.id


@pytest.mark.asyncio
async def test_async_search_cluster_level(couchbase_fts, mock_embedder):
    mock_cluster_inst = AsyncMock(spec=AsyncCluster)
    mock_search_result_obj = Mock()
    mock_search_row = Mock()
    mock_search_row.id = "test_id_cluster_search"
    mock_search_row.score = 0.90
    async def async_rows():
        yield mock_search_row
    mock_search_result_obj.rows = async_rows
    mock_cluster_inst.search = Mock(return_value=mock_search_result_obj)
    mock_async_collection_instance = AsyncMock(spec=AsyncCollection)
    mock_get_result_kv = AsyncMock(spec=GetResult)
    mock_get_result_kv.content_as = {dict: {"name": "cluster test doc from kv", "content": "cluster test content from kv", "meta_data": {"source": "kv_cluster"}, "embedding": [0.4, 0.5, 0.6]}}
    mock_async_collection_instance.get = AsyncMock(return_value=mock_get_result_kv)
    with (
        patch.object(couchbase_fts, "get_async_cluster", AsyncMock(return_value=mock_cluster_inst)),
        patch.object(couchbase_fts, "get_async_collection", AsyncMock(return_value=mock_async_collection_instance)),
    ):
        couchbase_fts.is_global_level_index = True
        results = await couchbase_fts.async_search("cluster query kv", limit=3)
        assert len(results) == 1 and results[0].id == mock_search_row.id


@pytest.mark.asyncio
async def test_async_drop(couchbase_fts):
    mock_bucket_inst = AsyncMock(spec=AsyncBucket)
    mock_collections_mgr = AsyncMock()
    mock_bucket_inst.collections = Mock(return_value=mock_collections_mgr)
    mock_collections_mgr.drop_collection = AsyncMock()
    with patch.object(CouchbaseSearch, "get_async_bucket", new_callable=AsyncMock) as mock_get_async_bucket:
        mock_get_async_bucket.return_value = mock_bucket_inst
        with patch.object(couchbase_fts, "async_exists", AsyncMock(return_value=True)):
            await couchbase_fts.async_drop()
            mock_collections_mgr.drop_collection.assert_called_once()
            # Reset the mock so the next branch starts with a clean slate.
            mock_collections_mgr.drop_collection.reset_mock()
        with patch.object(couchbase_fts, "async_exists", AsyncMock(return_value=False)):
            await couchbase_fts.async_drop()
            mock_collections_mgr.drop_collection.assert_not_called()


@pytest.mark.asyncio
async def test_async_exists(couchbase_fts):
    mock_bucket_inst = AsyncMock(spec=AsyncBucket)
    mock_collections_mgr = AsyncMock()
    mock_bucket_inst.collections = Mock(return_value=mock_collections_mgr)
    mock_scope_obj = Mock()
    mock_scope_obj.name = couchbase_fts.scope_name
    mock_collection_obj = Mock()
    mock_collection_obj.name = couchbase_fts.collection_name
    mock_scope_obj.collections = [mock_collection_obj]
    with patch.object(CouchbaseSearch, "get_async_bucket", new_callable=AsyncMock) as mock_get_async_bucket:
        mock_get_async_bucket.return_value = mock_bucket_inst
        mock_collections_mgr.get_all_scopes = AsyncMock(return_value=[mock_scope_obj])
        assert await couchbase_fts.async_exists() is True
        mock_collections_mgr.get_all_scopes = AsyncMock(return_value=[])
        assert await couchbase_fts.async_exists() is False
        mock_collections_mgr.get_all_scopes.side_effect = Exception("Test error")
        assert await couchbase_fts.async_exists() is False


@pytest.mark.asyncio
async def test_async_cluster_property_caching(couchbase_fts, mock_async_cluster):
    cluster_instance_1 = await couchbase_fts.get_async_cluster()
    mock_async_cluster.connect.assert_called_once_with(couchbase_fts.connection_string, couchbase_fts.cluster_options)
    cluster_instance_2 = await couchbase_fts.get_async_cluster()
    assert cluster_instance_2 is cluster_instance_1


@pytest.mark.asyncio
async def test_async_bucket_property_caching(couchbase_fts):
    mock_cluster_inst = AsyncMock(spec=AsyncCluster)
    mock_bucket_inst = AsyncMock()
    mock_cluster_inst.bucket = Mock(return_value=mock_bucket_inst)
    with patch.object(CouchbaseSearch, "get_async_cluster", new_callable=AsyncMock) as mock_get_async_cluster:
        mock_get_async_cluster.return_value = mock_cluster_inst
        bucket1 = await couchbase_fts.get_async_bucket()
        bucket2 = await couchbase_fts.get_async_bucket()
    assert bucket1 is bucket2


@pytest.mark.asyncio
async def test_async_scope_property_caching(couchbase_fts):
    mock_bucket_inst = AsyncMock(spec=AsyncBucket)
    mock_scope_inst = AsyncMock(spec=AsyncScope)
    mock_bucket_inst.scope = Mock(return_value=mock_scope_inst)
    with patch.object(CouchbaseSearch, "get_async_bucket", new_callable=AsyncMock) as mock_get_async_bucket:
        mock_get_async_bucket.return_value = mock_bucket_inst
        scope1 = await couchbase_fts.get_async_scope()
        scope2 = await couchbase_fts.get_async_scope()
    assert scope1 is scope2


@pytest.mark.asyncio
async def test_async_collection_property_caching(couchbase_fts):
    mock_scope_inst = AsyncMock(spec=AsyncScope)
    mock_collection_inst = AsyncMock(spec=AsyncCollection)
    mock_scope_inst.collection = Mock(return_value=mock_collection_inst)
    with patch.object(CouchbaseSearch, "get_async_scope", new_callable=AsyncMock) as mock_get_async_scope:
        mock_get_async_scope.return_value = mock_scope_inst
        collection1 = await couchbase_fts.get_async_collection()
        collection2 = await couchbase_fts.get_async_collection()
    assert collection1 is collection2


def test_delete_by_id(couchbase_fts, mock_collection):
    with patch.object(couchbase_fts, "id_exists") as mock_id_exists:
        mock_id_exists.return_value = True
        result = couchbase_fts.delete_by_id("doc_1")
        assert result is True
        mock_collection.remove.assert_called_with("doc_1")
        mock_id_exists.return_value = False
        result = couchbase_fts.delete_by_id("nonexistent_id")
        assert result is False


def test_delete_by_name(couchbase_fts, mock_scope, mock_collection):
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
    result = couchbase_fts.delete_by_name("test_document")
    assert result is True
    mock_collection.remove_multi.assert_called_once()
    mock_result.rows.return_value = []
    result = couchbase_fts.delete_by_name("nonexistent_document")
    assert result is False  # returns False when no documents found
    mock_scope.query.side_effect = Exception("Query error")
    result = couchbase_fts.delete_by_name("test_document")
    assert result is False


def test_delete_by_metadata(couchbase_fts, mock_scope, mock_collection):
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
    result = couchbase_fts.delete_by_metadata(metadata)
    assert result is True and mock_collection.remove_multi.call_count == 1
    mock_result.rows.return_value = []
    result = couchbase_fts.delete_by_metadata({"category": "nonexistent"})
    assert result is False
    result = couchbase_fts.delete_by_metadata({})
    assert result is False
    mock_scope.query.side_effect = Exception("Query error")
    result = couchbase_fts.delete_by_metadata({"category": "test"})
    assert result is False


def test_delete_by_content_id(couchbase_fts, mock_scope, mock_collection):
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
    result = couchbase_fts.delete_by_content_id("content_123")
    assert result is True
    mock_result.rows.return_value = []
    result = couchbase_fts.delete_by_content_id("nonexistent_content")
    assert result is False
    mock_scope.query.side_effect = Exception("Query error")
    result = couchbase_fts.delete_by_content_id("content_123")
    assert result is False


def test_delete_by_id_exception_handling(couchbase_fts, mock_collection):
    with patch.object(couchbase_fts, "id_exists") as mock_id_exists:
        mock_id_exists.return_value = True
        mock_collection.remove.side_effect = Exception("Remove error")
        result = couchbase_fts.delete_by_id("doc_1")
        assert result is False
        mock_id_exists.side_effect = Exception("Exists check error")
        result = couchbase_fts.delete_by_id("doc_1")
        assert result is False


def test_delete_by_name_exception_handling(couchbase_fts, mock_scope):
    mock_scope.query.side_effect = Exception("Query error")
    result = couchbase_fts.delete_by_name("test_document")
    assert result is False


def test_delete_by_metadata_exception_handling(couchbase_fts, mock_scope):
    mock_scope.query.side_effect = Exception("Query error")
    result = couchbase_fts.delete_by_metadata({"category": "test"})
    assert result is False


def test_delete_by_content_id_exception_handling(couchbase_fts, mock_scope):
    mock_scope.query.side_effect = Exception("Query error")
    result = couchbase_fts.delete_by_content_id("content_123")
    assert result is False


# -------------------------------------------------
# Filter Conversion Tests
# -------------------------------------------------

def test_convert_filter_eq_string():
    """Test EQ filter with string value"""
    filter_expr = EQ(key="category", value="electronics")
    result = _convert_filter_expr_to_sql(filter_expr)
    assert result == "d.metadata.category = 'electronics'"


def test_convert_filter_eq_number():
    """Test EQ filter with numeric value"""
    filter_expr = EQ(key="price", value=99.99)
    result = _convert_filter_expr_to_sql(filter_expr)
    assert result == "d.metadata.price = 99.99"


def test_convert_filter_gt():
    """Test GT (greater than) filter"""
    filter_expr = GT(key="rating", value=4.5)
    result = _convert_filter_expr_to_sql(filter_expr)
    assert result == "d.metadata.rating > 4.5"


def test_convert_filter_lt():
    """Test LT (less than) filter"""
    filter_expr = LT(key="stock", value=10)
    result = _convert_filter_expr_to_sql(filter_expr)
    assert result == "d.metadata.stock < 10"


def test_convert_filter_in_strings():
    """Test IN filter with string values"""
    filter_expr = IN(key="color", values=["red", "blue", "green"])
    result = _convert_filter_expr_to_sql(filter_expr)
    assert result == "d.metadata.color IN ['red', 'blue', 'green']"


def test_convert_filter_in_numbers():
    """Test IN filter with numeric values"""
    filter_expr = IN(key="size", values=[8, 9, 10, 11])
    result = _convert_filter_expr_to_sql(filter_expr)
    assert result == "d.metadata.size IN [8, 9, 10, 11]"


def test_convert_filter_and():
    """Test AND filter combining multiple conditions"""
    filter_expr = AND(
        EQ(key="category", value="electronics"),
        GT(key="price", value=50)
    )
    result = _convert_filter_expr_to_sql(filter_expr)
    assert result == "(d.metadata.category = 'electronics' AND d.metadata.price > 50)"


def test_convert_filter_or():
    """Test OR filter combining multiple conditions"""
    filter_expr = OR(
        EQ(key="color", value="red"),
        EQ(key="color", value="blue")
    )
    result = _convert_filter_expr_to_sql(filter_expr)
    assert result == "(d.metadata.color = 'red' OR d.metadata.color = 'blue')"


def test_convert_filter_not():
    """Test NOT filter negating a condition"""
    filter_expr = NOT(expression=EQ(key="discontinued", value="true"))
    result = _convert_filter_expr_to_sql(filter_expr)
    assert result == "NOT (d.metadata.discontinued = 'true')"


def test_convert_filter_list_implicit_and():
    """Test list of FilterExpr with implicit AND"""
    filter_list = [
        EQ(key="category", value="books"),
        GT(key="rating", value=4.0),
        LT(key="price", value=30)
    ]
    result = _convert_filter_expr_to_sql(filter_list)
    assert result == "(d.metadata.category = 'books' AND d.metadata.rating > 4.0 AND d.metadata.price < 30)"


def test_convert_filter_empty_list():
    """Test empty list returns empty string"""
    result = _convert_filter_expr_to_sql([])
    assert result == ""


def test_convert_filter_complex_nested():
    """Test complex nested filter expression"""
    filter_expr = AND(
        OR(
            EQ(key="category", value="electronics"),
            EQ(key="category", value="computers")
        ),
        GT(key="price", value=100),
        NOT(expression=EQ(key="refurbished", value="true"))
    )
    result = _convert_filter_expr_to_sql(filter_expr)
    expected = "((d.metadata.category = 'electronics' OR d.metadata.category = 'computers') AND d.metadata.price > 100 AND NOT (d.metadata.refurbished = 'true'))"
    assert result == expected


def test_convert_filter_custom_prefix():
    """Test filter conversion with custom metadata prefix"""
    filter_expr = EQ(key="status", value="active")
    result = _convert_filter_expr_to_sql(filter_expr, metadata_prefix="doc.metadata")
    assert result == "doc.metadata.status = 'active'"


def test_convert_filter_unsupported_type():
    """Test that unsupported filter type raises ValueError"""
    with pytest.raises(ValueError, match="Unsupported filter type"):
        _convert_filter_expr_to_sql("invalid_filter")
