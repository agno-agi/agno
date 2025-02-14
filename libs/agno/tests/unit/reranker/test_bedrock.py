import json
from typing import List
from unittest.mock import MagicMock, PropertyMock, patch

import boto3
import pytest

from agno.document import Document
from agno.reranker.bedrock import BedrockReranker


# Helper to create test documents.
def create_test_documents(num: int) -> List[Document]:
    return [Document(content=f"test content {i}") for i in range(num)]


# Helper to setup the mock for the response chain.
def setup_invoke_model_mock(mock_session, response_data: dict):
    response_json = json.dumps(response_data)
    mock_read = MagicMock(return_value=response_json)
    mock_body = MagicMock()
    mock_body.read = mock_read
    mock_response = MagicMock()
    mock_response.get = MagicMock(return_value=mock_body)
    mock_client = MagicMock()
    mock_client.invoke_model = MagicMock(return_value=mock_response)
    mock_session.client = MagicMock(return_value=mock_client)
    return mock_client


@pytest.fixture
def mock_session():
    return MagicMock(spec=boto3.Session)


@pytest.fixture
def reranker():
    # Using default constructor; attributes can be set per test as needed.
    return BedrockReranker()


def test_rerank_empty_documents(reranker):
    result = reranker._rerank("test query", [])
    assert result == []


def test_rerank_with_valid_documents(mock_session):
    reranker = BedrockReranker(top_n=2)
    reranker.bedrock_session = mock_session
    documents = create_test_documents(3)
    response_data = {
        "results": [
            {"index": 2, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.7},
            {"index": 1, "relevance_score": 0.5},
        ]
    }
    setup_invoke_model_mock(mock_session, response_data)
    result = reranker._rerank("test query", documents)
    # Only top_n documents returned.
    assert len(result) == 2
    assert result[0].reranking_score == 0.9
    assert result[1].reranking_score == 0.7
    assert result[0].content == "test content 2"
    assert result[1].content == "test content 0"


def test_rerank_error_handling(reranker):
    documents = create_test_documents(2)
    # Force _rerank to raise an error.
    with patch.object(BedrockReranker, "_rerank", side_effect=Exception("Test error")):
        result = reranker.rerank("test query", documents)
        assert result == documents


def test_rerank_with_invalid_top_n(reranker, monkeypatch):
    # Set invalid top_n to 0. It should reset to len(documents).
    reranker.top_n = 0
    documents = create_test_documents(3)
    response_data = {
        "results": [
            {"index": 0, "relevance_score": 0.9},
            {"index": 1, "relevance_score": 0.7},
            {"index": 2, "relevance_score": 0.5},
        ]
    }
    # Patch the 'session' property using PropertyMock.
    with patch.object(BedrockReranker, "session", new_callable=PropertyMock) as mock_session_prop:
        mock_session = MagicMock()
        setup_invoke_model_mock(mock_session, response_data)
        mock_session_prop.return_value = mock_session
        with patch("agno.utils.log.logger.warning") as mock_logger:
            result = reranker._rerank("test query", documents)
            mock_logger.assert_called_once()
            # Since top_n is invalid, it resets to len(documents)
            assert len(result) == len(documents)
