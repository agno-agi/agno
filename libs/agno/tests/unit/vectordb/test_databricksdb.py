from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.filters import EQ
from agno.knowledge.document import Document
from agno.vectordb.databricks import DatabricksVectorDb
from agno.vectordb.search import SearchType


@pytest.fixture
def mock_embedder():
    embedder = MagicMock()
    embedder.dimensions = 3
    embedder.get_embedding.return_value = [0.1, 0.2, 0.3]
    embedder.get_embedding_and_usage.return_value = ([0.1, 0.2, 0.3], {"prompt_tokens": 3, "total_tokens": 3})
    return embedder


@pytest.fixture
def mock_vector_client():
    client = MagicMock()
    client.index_exists.return_value = False
    return client


@pytest.fixture
def mock_vector_index():
    index = MagicMock()
    index.wait_until_ready.return_value = None
    index.similarity_search.return_value = {
        "manifest": {
            "columns": [
                {"name": "id"},
                {"name": "content"},
                {"name": "name"},
                {"name": "meta_data"},
                {"name": "content_id"},
                {"name": "content_hash"},
                {"name": "usage"},
                {"name": "score"},
            ]
        },
        "result": {
            "data_array": [
                ["doc_1", "alpha content", "alpha", '{"topic":"ai","author":"alice"}', "content-1", "hash-1", None, 0.98],
                ["doc_2", "beta content", "beta", '{"topic":"ml","author":"bob"}', "content-2", "hash-2", None, 0.65],
            ]
        },
    }
    index.scan.side_effect = [
        {
            "data": [
                {
                    "id": "doc_1",
                    "content": "alpha content",
                    "name": "alpha",
                    "meta_data": '{"topic":"ai"}',
                    "content_id": "content-1",
                    "content_hash": "hash-1",
                }
            ],
            "last_primary_key": "doc_1",
        },
        {
            "data": [
                {
                    "id": "doc_2",
                    "content": "beta content",
                    "name": "beta",
                    "meta_data": '{"topic":"ml"}',
                    "content_id": "content-2",
                    "content_hash": "hash-2",
                }
            ],
            "last_primary_key": "doc_2",
        },
        {"data": [], "last_primary_key": None},
    ]
    return index


@pytest.fixture
def vector_db(mock_embedder, mock_vector_client, mock_vector_index):
    with patch("agno.vectordb.databricks.databricks._get_vector_search_client_cls", return_value=MagicMock()):
        db = DatabricksVectorDb(
            endpoint_name="vs-endpoint",
            index_name="catalog.schema.index",
            host="https://example.cloud.databricks.com",
            token="dapi-test",
            embedder=mock_embedder,
        )
        db._client = mock_vector_client
        db._index = mock_vector_index
        yield db


def test_initialization(vector_db):
    assert vector_db.name == "catalog.schema.index"
    assert vector_db.embedding_dimension == 3
    assert vector_db.schema["id"] == "string"
    assert vector_db.schema["embedding"] == "array<float>"


def test_initialization_allows_search_only_embedder_without_dimensions(mock_vector_client, mock_vector_index):
    embedder = MagicMock()
    embedder.dimensions = None
    embedder.get_embedding.return_value = [0.1, 0.2, 0.3]

    with patch("agno.vectordb.databricks.databricks._get_vector_search_client_cls", return_value=MagicMock()):
        db = DatabricksVectorDb(
            endpoint_name="vs-endpoint",
            index_name="catalog.schema.index",
            host="https://example.cloud.databricks.com",
            token="dapi-test",
            embedder=embedder,
        )
        db._client = mock_vector_client
        db._index = mock_vector_index

    assert db.embedding_dimension is None


def test_create_direct_access_index(mock_embedder, mock_vector_client):
    mock_index = MagicMock()
    mock_vector_client.index_exists.return_value = False
    mock_vector_client.create_direct_access_index.return_value = mock_index

    with patch("agno.vectordb.databricks.databricks._get_vector_search_client_cls", return_value=MagicMock()):
        db = DatabricksVectorDb(
            endpoint_name="vs-endpoint",
            index_name="catalog.schema.index",
            host="https://example.cloud.databricks.com",
            token="dapi-test",
            embedder=mock_embedder,
        )
        db._client = mock_vector_client
        db.create()

    mock_vector_client.create_direct_access_index.assert_called_once_with(
        endpoint_name="vs-endpoint",
        index_name="catalog.schema.index",
        primary_key="id",
        embedding_dimension=3,
        embedding_vector_column="embedding",
        schema=db.schema,
        embedding_model_endpoint_name=None,
    )
    mock_index.wait_until_ready.assert_called_once_with(verbose=False)


def test_upsert_serializes_documents(vector_db, mock_embedder):
    documents = [
        Document(
            content="alpha content",
            name="alpha",
            meta_data={"topic": "ai"},
            content_id="content-1",
        )
    ]

    vector_db.upsert(content_hash="hash-1", documents=documents, filters={"tenant": "test"})

    mock_embedder.get_embedding_and_usage.assert_called_once_with("alpha content")
    vector_db.index.upsert.assert_called_once()
    rows = vector_db.index.upsert.call_args.args[0]
    assert rows[0]["content"] == "alpha content"
    assert rows[0]["content_hash"] == "hash-1"
    assert rows[0]["meta_data"] == '{"topic": "ai", "tenant": "test"}'


def test_search_parses_databricks_results_and_applies_client_side_filters(vector_db, mock_embedder):
    results = vector_db.search("find ai docs", limit=2, filters={"author": "alice"})

    mock_embedder.get_embedding.assert_called_once_with("find ai docs")
    vector_db.index.similarity_search.assert_called_once_with(
        columns=vector_db.return_columns,
        query_vector=[0.1, 0.2, 0.3],
        num_results=2,
        filters=None,
        query_type="ANN",
    )
    assert len(results) == 1
    assert results[0].id == "doc_1"
    assert results[0].content == "alpha content"
    assert results[0].meta_data["author"] == "alice"
    assert results[0].reranking_score == 0.98


def test_hybrid_search_pushes_supported_filters(vector_db, mock_embedder):
    vector_db.search_type = SearchType.hybrid
    vector_db._auto_configure_index = False
    vector_db._index_defaults_loaded = True
    vector_db.schema["tenant"] = "string"
    vector_db.return_columns.append("tenant")

    vector_db.search("find ai docs", limit=2, filters={"tenant": "test", "author": "alice"})

    vector_db.index.similarity_search.assert_called_once_with(
        columns=vector_db.return_columns,
        query_vector=[0.1, 0.2, 0.3],
        num_results=2,
        filters={"tenant": "test"},
        query_type="HYBRID",
        query_text="find ai docs",
    )


def test_search_applies_filter_expr_client_side(vector_db):
    results = vector_db.search("find ai docs", limit=2, filters=[EQ("author", "alice")])

    assert len(results) == 1
    assert results[0].id == "doc_1"


def test_search_supports_client_side_filtering_on_built_in_columns(vector_db):
    results = vector_db.search("find ai docs", limit=2, filters={"content_hash": "hash-2"})

    assert len(results) == 1
    assert results[0].id == "doc_2"


def test_search_skips_provider_call_when_embedding_is_empty(vector_db, mock_embedder):
    mock_embedder.get_embedding.return_value = []

    results = vector_db.search("find ai docs", limit=2)

    assert results == []
    vector_db.index.similarity_search.assert_not_called()


def test_search_auto_configures_delta_sync_indexes_from_live_style_scan(mock_vector_client):
    embedder = MagicMock()
    embedder.dimensions = None
    embedder.get_embedding.return_value = [0.1, 0.2, 0.3]

    mock_vector_index = MagicMock()
    mock_vector_index.describe.return_value = {
        "primary_key": "chunk_id",
        "index_type": "DELTA_SYNC",
        "delta_sync_index_spec": {
            "embedding_source_columns": [{"name": "chunked_text"}],
        },
    }
    mock_vector_index.scan.return_value = {
        "data": [
            {
                "fields": [
                    {"key": "review_date", "value": {"string_value": "2024-06-03T20:42:29.116"}},
                    {
                        "key": "chunked_text_vector",
                        "value": {
                            "list_value": {
                                "values": [
                                    {"number_value": 0.1},
                                    {"number_value": 0.2},
                                    {"number_value": 0.3},
                                ]
                            }
                        },
                    },
                    {"key": "chunked_text", "value": {"string_value": "alpha content"}},
                    {"key": "chunk_id", "value": {"string_value": "doc-1"}},
                ]
            }
        ],
        "last_primary_key": "doc-1",
    }
    mock_vector_index.similarity_search.return_value = {
        "manifest": {
            "columns": [
                {"name": "chunk_id"},
                {"name": "chunked_text"},
                {"name": "review_date"},
                {"name": "score"},
            ]
        },
        "result": {
            "data_array": [
                ["doc-1", "alpha content", "2024-06-03T20:42:29.116", 0.91],
            ]
        },
    }

    with patch("agno.vectordb.databricks.databricks._get_vector_search_client_cls", return_value=MagicMock()):
        db = DatabricksVectorDb(
            endpoint_name="vs-endpoint",
            index_name="workspace.default.media_gold_reviews_chunked_idx",
            host="https://example.cloud.databricks.com",
            token="dapi-test",
            embedder=embedder,
        )
        db._client = mock_vector_client
        db._index = mock_vector_index

    results = db.search("restaurant review", limit=1)

    assert db.primary_key == "chunk_id"
    assert db.text_column == "chunked_text"
    assert db.embedding_vector_column == "chunked_text_vector"
    assert set(db.return_columns) == {"chunk_id", "chunked_text", "review_date"}
    assert len(results) == 1
    assert results[0].id == "doc-1"
    assert results[0].content == "alpha content"
    assert results[0].meta_data == {"review_date": "2024-06-03T20:42:29.116"}
    mock_vector_index.similarity_search.assert_called_once_with(
        columns=db.return_columns,
        query_vector=[0.1, 0.2, 0.3],
        num_results=1,
        filters=None,
        query_type="ANN",
    )


def test_delete_by_name_uses_scan_and_primary_key_delete(vector_db):
    deleted = vector_db.delete_by_name("beta")

    assert deleted is True
    vector_db.index.delete.assert_called_once_with(primary_keys=["doc_2"])


def test_content_hash_exists_uses_scan(vector_db):
    assert vector_db.content_hash_exists("hash-2") is True

    vector_db.index.scan.side_effect = [
        {
            "data": [
                {
                    "id": "doc_1",
                    "content": "alpha content",
                    "name": "alpha",
                    "meta_data": '{"topic":"ai"}',
                    "content_id": "content-1",
                    "content_hash": "hash-1",
                }
            ],
            "last_primary_key": "doc_1",
        },
        {
            "data": [
                {
                    "id": "doc_2",
                    "content": "beta content",
                    "name": "beta",
                    "meta_data": '{"topic":"ml"}',
                    "content_id": "content-2",
                    "content_hash": "hash-2",
                }
            ],
            "last_primary_key": "doc_2",
        },
        {"data": [], "last_primary_key": None},
    ]
    assert vector_db.content_hash_exists("missing") is False


def test_update_metadata_merges_and_reupserts(vector_db):
    vector_db.update_metadata("content-2", {"status": "active"})

    vector_db.index.upsert.assert_called_once()
    updated_rows = vector_db.index.upsert.call_args.args[0]
    assert updated_rows[0]["id"] == "doc_2"
    assert updated_rows[0]["meta_data"] == '{"topic": "ml", "status": "active"}'


@pytest.mark.asyncio
async def test_async_exists(vector_db):
    with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        mock_to_thread.return_value = True

        exists = await vector_db.async_exists()

        assert exists is True
        mock_to_thread.assert_awaited_once_with(vector_db.exists)


@pytest.mark.asyncio
async def test_async_search(vector_db):
    expected = [Document(content="alpha")]
    with patch.object(vector_db, "search", return_value=expected), patch(
        "asyncio.to_thread", new_callable=AsyncMock
    ) as mock_to_thread:
        mock_to_thread.return_value = expected

        results = await vector_db.async_search("query", limit=4, filters={"tenant": "test"})

        assert results == expected
        mock_to_thread.assert_awaited_once_with(vector_db.search, "query", 4, {"tenant": "test"})
