from unittest.mock import Mock, patch

from agno.knowledge.document.base import Document
from agno.knowledge.reranker.litellm import LiteLLMReranker


@patch('agno.knowledge.reranker.litellm.litellm')
def test_reranker_initialization(mock_litellm):
    """Test that the reranker initializes correctly"""
    reranker = LiteLLMReranker(model="cohere/rerank-multilingual-v3.0")
    assert reranker is not None
    assert reranker.model == "cohere/rerank-multilingual-v3.0"
    assert reranker.top_n is None


@patch('agno.knowledge.reranker.litellm.litellm')
def test_rerank_basic(mock_litellm):
    """Test basic reranking functionality"""
    mock_response = Mock()
    mock_result1 = Mock()
    mock_result1.index = 0
    mock_result1.relevance_score = 0.4
    mock_result2 = Mock()
    mock_result2.index = 2
    mock_result2.relevance_score = 0.9
    mock_result3 = Mock()
    mock_result3.index = 1
    mock_result3.relevance_score = 0.6
    mock_response.results = [mock_result1, mock_result2, mock_result3]
    
    mock_litellm.rerank.return_value = mock_response
    
    docs = [Document(content=f"doc {i}") for i in range(3)]
    rr = LiteLLMReranker(model="cohere/rerank-multilingual-v3.0")
    ranked = rr.rerank("query", docs)
    assert [d.content for d in ranked] == ["doc 2", "doc 1", "doc 0"]
    assert ranked[0].reranking_score == 0.9


@patch('agno.knowledge.reranker.litellm.litellm')
def test_rerank_top_n(mock_litellm):
    """Test reranking with top_n parameter"""
    mock_response = Mock()
    mock_result1 = Mock()
    mock_result1.index = 0
    mock_result1.relevance_score = 0.4
    mock_result2 = Mock()
    mock_result2.index = 2
    mock_result2.relevance_score = 0.9
    mock_result3 = Mock()
    mock_result3.index = 1
    mock_result3.relevance_score = 0.6
    mock_result4 = Mock()
    mock_result4.index = 3
    mock_result4.relevance_score = 0.3
    mock_response.results = [mock_result1, mock_result2, mock_result3, mock_result4]
    
    mock_litellm.rerank.return_value = mock_response
    
    docs = [Document(content=f"doc {i}") for i in range(4)]
    rr = LiteLLMReranker(model="cohere/rerank-multilingual-v3.0", top_n=2)
    ranked = rr.rerank("query", docs)
    assert len(ranked) == 2
    assert ranked[0].reranking_score >= ranked[1].reranking_score


@patch('agno.knowledge.reranker.litellm.litellm')
def test_rerank_empty(mock_litellm):
    """Test reranking with empty document list"""
    rr = LiteLLMReranker(model="cohere/rerank-multilingual-v3.0")
    assert rr.rerank("query", []) == []


@patch('agno.knowledge.reranker.litellm.litellm')
def test_build_request(mock_litellm):
    """Test request building functionality"""
    reranker = LiteLLMReranker(model="cohere/rerank-multilingual-v3.0")
    docs = [Document(content="doc1"), Document(content="doc2")]
    request = reranker._build_request("test query", docs)
    
    assert isinstance(request, dict)
    assert request["model"] == "cohere/rerank-multilingual-v3.0"
    assert request["query"] == "test query"
    assert request["documents"] == ["doc1", "doc2"]
