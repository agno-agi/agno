from unittest.mock import MagicMock, patch

import pytest
from meilisearch.errors import MeilisearchApiError
from requests import Response

from agno.document import Document
from agno.embedder import Embedder
from agno.vectordb.meilisearch import MeiliSearch
from agno.vectordb.search import SearchType


@pytest.fixture
def mock_embedder():
    embedder = MagicMock(spec=Embedder)
    embedder.dimensions = 1536
    embedder.get_embedding.return_value = [0.1] * 1536
    embedder.get_embedding_and_usage.return_value = ([0.1] * 1536, {"total_tokens": 10})
    return embedder


@pytest.fixture
def meilisearch(mock_embedder):
    with patch("agno.vectordb.meilisearch.meilisearch.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        db = MeiliSearch(
            index_name="test_index",
            url="http://localhost:7700",
            embedder=mock_embedder,
            search_type=SearchType.vector,
            wait_check_task=True,
        )
        yield db


def test_init(meilisearch, mock_embedder):
    assert meilisearch.index_name == "test_index"
    assert meilisearch.url == "http://localhost:7700"
    assert meilisearch.embedder == mock_embedder
    assert meilisearch.search_type == SearchType.vector


def test_create(meilisearch):
    """Test create method."""
    with (
        patch.object(meilisearch, "exists", return_value=False),
        patch.object(meilisearch, "wait_for_task", return_value=True),
    ):
        meilisearch.create()
        meilisearch.client.create_index.assert_called_once_with("test_index", options={"primaryKey": "id"})
        meilisearch.client.index.return_value.update_settings.assert_called_once()


def test_exists(meilisearch):
    """Test exists method."""
    meilisearch.client.index.return_value = MagicMock()
    assert meilisearch.exists() is True

    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 404
    mock_response.text = '{"message": "Index not found", "code": "index_not_found"}'
    meilisearch.client.get_index.side_effect = MeilisearchApiError("index_not_found", mock_response)
    assert meilisearch.exists() is False


def test_insert(meilisearch):
    doc = Document(
        id="test_id",
        name="test_name",
        content="test_content",
        meta_data={"key": "value"},
    )
    meilisearch.client.index.return_value.add_documents.return_value = MagicMock(task_uid="1")

    with patch.object(meilisearch, "wait_for_task", return_value=True):
        meilisearch.insert([doc])

    meilisearch.client.index.return_value.add_documents.assert_called_once()
    call_args = meilisearch.client.index.return_value.add_documents.call_args[0][0]
    assert len(call_args) == 1
    assert call_args[0]["id"] == "test_id"
    assert call_args[0]["name"] == "test_name"
    assert call_args[0]["content"] == "test_content"
    assert call_args[0]["meta_data"] == {"key": "value"}


def test_search(meilisearch):
    mock_response = {
        "hits": [
            {
                "id": "test_id",
                "name": "test_name",
                "content": "test_content",
                "_vectors": {"content_embedding": {"embeddings": [0.1] * 1536}},
                "meta_data": {"key": "value"},
            }
        ]
    }
    meilisearch.client.index.return_value.search.return_value = mock_response

    results = meilisearch.search("test query", limit=5)

    assert len(results) == 1
    assert results[0].id == "test_id"
    assert results[0].name == "test_name"
    assert results[0].content == "test_content"
    assert results[0].meta_data == {"key": "value"}


def test_delete(meilisearch):
    meilisearch.client.index.return_value.delete_all_documents.return_value = MagicMock(task_uid="1")

    with patch.object(meilisearch, "wait_for_task", return_value=True):
        result = meilisearch.delete()

    assert result is True
    meilisearch.client.index.return_value.delete_all_documents.assert_called_once()


def test_drop(meilisearch):
    meilisearch.client.delete_index.return_value = MagicMock(task_uid="1")

    with (
        patch.object(meilisearch, "exists", return_value=True),
        patch.object(meilisearch, "wait_for_task", return_value=True),
    ):
        meilisearch.drop()

    meilisearch.client.delete_index.assert_called_once_with("test_index")


def test_hybrid_search(meilisearch):
    meilisearch.search_type = SearchType.hybrid
    mock_response = {
        "hits": [
            {
                "id": "test_id",
                "name": "test_name",
                "content": "test_content",
                "_vectors": {"content_embedding": {"embeddings": [0.1] * 1536}},
                "meta_data": {"key": "value"},
            }
        ]
    }
    meilisearch.client.index.return_value.search.return_value = mock_response

    results = meilisearch.search("test query", limit=5)

    assert len(results) == 1
    assert results[0].id == "test_id"
    assert results[0].name == "test_name"
    assert results[0].content == "test_content"
    assert results[0].meta_data == {"key": "value"}


def test_keyword_search(meilisearch):
    meilisearch.search_type = SearchType.keyword
    mock_response = {
        "hits": [
            {
                "id": "test_id",
                "name": "test_name",
                "content": "test_content",
                "_vectors": {"content_embedding": {"embeddings": [0.1] * 1536}},
                "meta_data": {"key": "value"},
            }
        ]
    }
    meilisearch.client.index.return_value.search.return_value = mock_response

    results = meilisearch.search("test query", limit=5)

    assert len(results) == 1
    assert results[0].id == "test_id"
    assert results[0].name == "test_name"
    assert results[0].content == "test_content"
    assert results[0].meta_data == {"key": "value"}


def test_doc_exists(meilisearch):
    meilisearch.client.index.return_value.get_document.return_value = {"id": "test_id"}
    doc = Document(id="test_id", content="test_content")
    assert meilisearch.doc_exists(doc) is True

    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 404
    mock_response.text = '{"message": "Document not found", "code": "document_not_found"}'
    meilisearch.client.index.return_value.get_document.side_effect = MeilisearchApiError(
        "document_not_found", mock_response
    )
    assert meilisearch.doc_exists(doc) is False


def test_name_exists(meilisearch):
    mock_response = MagicMock()
    mock_response.total = 1
    meilisearch.client.index.return_value.get_documents.return_value = mock_response
    assert meilisearch.name_exists("test_name") is True

    mock_response.total = 0
    assert meilisearch.name_exists("test_name") is False


def test_id_exists(meilisearch):
    meilisearch.client.index.return_value.get_document.return_value = {"id": "test_id"}
    assert meilisearch.id_exists("test_id") is True

    mock_response = MagicMock(spec=Response)
    mock_response.status_code = 404
    mock_response.text = '{"message": "Document not found", "code": "document_not_found"}'
    with patch.object(
        meilisearch.client.index.return_value,
        "get_document",
        side_effect=MeilisearchApiError("document_not_found", mock_response),
    ):
        assert meilisearch.id_exists("test_id") is False
