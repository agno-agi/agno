import pytest

from agno.knowledge.document.base import Document
from agno.knowledge.reranker.litellm import LiteLLMReranker


@pytest.fixture
def reranker():
    return LiteLLMReranker(model="cohere/rerank-multilingual-v3.0")


@pytest.fixture
def sample_documents():
    return [
        Document(content="The capital of France is Paris."),
        Document(content="Python is a programming language."),
        Document(content="The Eiffel Tower is located in Paris, France."),
        Document(content="Machine learning is a subset of artificial intelligence."),
        Document(content="France is a country in Western Europe."),
    ]


def test_reranker_initialization(reranker):
    """Test that the reranker initializes correctly"""
    assert reranker is not None
    assert reranker.model == "cohere/rerank-multilingual-v3.0"
    assert reranker.top_n is None


def test_rerank_basic(reranker, sample_documents):
    """Test basic reranking functionality"""
    query = "What is the capital of France?"
    ranked_docs = reranker.rerank(query, sample_documents)

    assert len(ranked_docs) <= len(sample_documents)
    assert all(isinstance(doc, Document) for doc in ranked_docs)
    
    for doc in ranked_docs:
        assert hasattr(doc, 'reranking_score')
        assert doc.reranking_score is not None
        assert isinstance(doc.reranking_score, (int, float))

    scores = [doc.reranking_score for doc in ranked_docs if doc.reranking_score is not None]
    assert scores == sorted(scores, reverse=True)


def test_rerank_with_top_n(sample_documents):
    """Test reranking with top_n parameter"""
    reranker = LiteLLMReranker(model="cohere/rerank-multilingual-v3.0", top_n=3)
    query = "Programming and technology"
    
    ranked_docs = reranker.rerank(query, sample_documents)
    
    assert len(ranked_docs) <= 3
    assert len(ranked_docs) <= len(sample_documents)


def test_rerank_empty_documents(reranker):
    """Test reranking with empty document list"""
    ranked_docs = reranker.rerank("any query", [])
    assert ranked_docs == []


def test_rerank_single_document(reranker):
    """Test reranking with a single document"""
    doc = Document(content="Single document for testing.")
    ranked_docs = reranker.rerank("test query", [doc])
    
    assert len(ranked_docs) == 1
    assert ranked_docs[0].content == doc.content
    assert hasattr(ranked_docs[0], 'reranking_score')


def test_rerank_special_characters(reranker):
    """Test reranking with special characters"""
    docs = [
        Document(content="Hello, world! 🌍"),
        Document(content="こんにちは世界 (Hello World in Japanese)"),
        Document(content="Émojis and spéciál charactérs: @#$%^&*()"),
    ]
    
    query = "Hello world greetings"
    ranked_docs = reranker.rerank(query, docs)
    
    assert len(ranked_docs) > 0
    assert all(isinstance(doc, Document) for doc in ranked_docs)


def test_different_models():
    """Test different reranking models"""
    models_to_test = [
        "cohere/rerank-multilingual-v3.0",
        "cohere/rerank-english-v3.0",
    ]
    
    docs = [
        Document(content="Technology and artificial intelligence"),
        Document(content="Cooking and recipes"),
    ]
    query = "AI and machine learning"
    
    for model_id in models_to_test:
        reranker = LiteLLMReranker(model=model_id)
        try:
            ranked_docs = reranker.rerank(query, docs)
            assert isinstance(ranked_docs, list)
            assert all(isinstance(doc, Document) for doc in ranked_docs)
        except Exception as e:
            pytest.skip(f"Model {model_id} not available: {e}")


def test_rerank_relevance_scoring(reranker, sample_documents):
    """Test that more relevant documents get higher scores"""
    france_query = "Tell me about France and Paris"
    ranked_docs = reranker.rerank(france_query, sample_documents)
    
    france_docs = [doc for doc in ranked_docs if "France" in doc.content or "Paris" in doc.content]
    non_france_docs = [doc for doc in ranked_docs if "France" not in doc.content and "Paris" not in doc.content]
    
    if france_docs and non_france_docs:
        avg_france_score = sum(doc.reranking_score for doc in france_docs if doc.reranking_score) / len(france_docs)
        avg_other_score = sum(doc.reranking_score for doc in non_france_docs if doc.reranking_score) / len(non_france_docs)
        
        assert avg_france_score >= avg_other_score