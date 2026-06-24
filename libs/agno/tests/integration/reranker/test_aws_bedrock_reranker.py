"""
Integration tests for AWS Bedrock Reranker.

These tests require valid AWS credentials with access to Bedrock.
Credentials can be provided via:
- Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
- AWS credentials file (~/.aws/credentials)
- AWS SSO session
- IAM role (when running on AWS infrastructure)

To run these tests:
    pytest libs/agno/tests/integration/reranker/test_aws_bedrock_reranker.py -v

Note:
- Amazon Rerank 1.0 is NOT available in us-east-1 (N. Virginia).
- Use us-west-2 or another supported region.
"""

import os

import pytest

from agno.knowledge.document import Document
from agno.knowledge.reranker.aws_bedrock import (
    AMAZON_RERANK_V1,
    COHERE_RERANK_V3_5,
    AmazonReranker,
    AwsBedrockReranker,
    CohereBedrockReranker,
)


def _has_aws_credentials() -> bool:
    """Check if AWS credentials are available via any method."""
    try:
        import boto3

        session = boto3.Session()
        credentials = session.get_credentials()
        return credentials is not None
    except Exception:
        return False


# Skip all tests if AWS credentials are not configured
pytestmark = pytest.mark.skipif(
    not _has_aws_credentials(),
    reason="AWS credentials not configured",
)


@pytest.fixture
def sample_documents():
    """Create sample documents for testing."""
    return [
        Document(content="Machine learning is a subset of artificial intelligence."),
        Document(content="The weather in Paris is typically mild in spring."),
        Document(content="Deep learning uses neural networks with many layers."),
        Document(content="Python is a popular programming language for data science."),
        Document(content="Transformers revolutionized natural language processing."),
    ]


@pytest.fixture
def ml_query():
    """A query about machine learning."""
    return "What is machine learning and how does it relate to AI?"


class TestAwsBedrockRerankerCohere:
    """Tests for Cohere Rerank 3.5 on Bedrock."""

    @pytest.fixture
    def reranker(self):
        return AwsBedrockReranker(
            model=COHERE_RERANK_V3_5,
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

    def test_reranker_initialization(self, reranker):
        """Test that the reranker initializes correctly."""
        assert reranker is not None
        assert reranker.model == COHERE_RERANK_V3_5
        assert reranker.top_n is None

    def test_rerank_documents(self, reranker, sample_documents, ml_query):
        """Test basic document reranking."""
        reranked = reranker.rerank(query=ml_query, documents=sample_documents)

        assert isinstance(reranked, list)
        assert len(reranked) == len(sample_documents)

        # Check that all documents have reranking scores
        for doc in reranked:
            assert doc.reranking_score is not None
            assert isinstance(doc.reranking_score, float)

        # Check that results are sorted by relevance (descending)
        scores = [doc.reranking_score for doc in reranked]
        assert scores == sorted(scores, reverse=True)

    def test_rerank_with_top_n(self, sample_documents, ml_query):
        """Test reranking with top_n limit."""
        reranker = AwsBedrockReranker(
            model=COHERE_RERANK_V3_5,
            top_n=3,
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

        reranked = reranker.rerank(query=ml_query, documents=sample_documents)

        assert len(reranked) == 3
        # Top results should be ML-related
        assert all(doc.reranking_score is not None for doc in reranked)

    def test_rerank_empty_documents(self, reranker):
        """Test reranking with empty document list."""
        reranked = reranker.rerank(query="Any query", documents=[])
        assert reranked == []

    def test_rerank_single_document(self, reranker, ml_query):
        """Test reranking with a single document."""
        single_doc = [Document(content="Machine learning is amazing.")]
        reranked = reranker.rerank(query=ml_query, documents=single_doc)

        assert len(reranked) == 1
        assert reranked[0].reranking_score is not None

    def test_ml_documents_ranked_higher(self, reranker, sample_documents, ml_query):
        """Test that ML-related documents are ranked higher for ML query."""
        reranked = reranker.rerank(query=ml_query, documents=sample_documents)

        # The top results should be about ML/AI/deep learning
        top_contents = [doc.content.lower() for doc in reranked[:3]]
        ml_related_count = sum(
            1
            for content in top_contents
            if any(term in content for term in ["machine learning", "ai", "deep learning", "neural"])
        )

        # At least 2 of the top 3 should be ML-related
        assert ml_related_count >= 2


class TestAwsBedrockRerankerAmazon:
    """Tests for Amazon Rerank 1.0 on Bedrock."""

    @pytest.fixture
    def reranker(self):
        # Note: Amazon Rerank 1.0 is NOT available in us-east-1
        return AwsBedrockReranker(
            model=AMAZON_RERANK_V1,
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

    def test_reranker_initialization(self, reranker):
        """Test that the Amazon reranker initializes correctly."""
        assert reranker is not None
        assert reranker.model == AMAZON_RERANK_V1

    def test_rerank_documents(self, reranker, sample_documents, ml_query):
        """Test document reranking with Amazon model."""
        reranked = reranker.rerank(query=ml_query, documents=sample_documents)

        assert isinstance(reranked, list)
        assert len(reranked) == len(sample_documents)

        for doc in reranked:
            assert doc.reranking_score is not None

    def test_rerank_with_top_n(self, sample_documents, ml_query):
        """Test Amazon reranker with top_n limit."""
        reranker = AwsBedrockReranker(
            model=AMAZON_RERANK_V1,
            top_n=2,
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

        reranked = reranker.rerank(query=ml_query, documents=sample_documents)
        assert len(reranked) == 2


class TestConvenienceClasses:
    """Tests for convenience reranker classes."""

    def test_cohere_bedrock_reranker(self, sample_documents, ml_query):
        """Test CohereBedrockReranker convenience class."""
        reranker = CohereBedrockReranker(
            top_n=3,
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

        assert reranker.model == COHERE_RERANK_V3_5

        reranked = reranker.rerank(query=ml_query, documents=sample_documents)
        assert len(reranked) == 3

    def test_amazon_reranker(self, sample_documents, ml_query):
        """Test AmazonReranker convenience class."""
        reranker = AmazonReranker(
            top_n=3,
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

        assert reranker.model == AMAZON_RERANK_V1

        reranked = reranker.rerank(query=ml_query, documents=sample_documents)
        assert len(reranked) == 3


class TestRerankerEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.fixture
    def reranker(self):
        return AwsBedrockReranker(
            model=COHERE_RERANK_V3_5,
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

    def test_long_document(self, reranker):
        """Test reranking with a long document."""
        long_content = "Machine learning is powerful. " * 500
        documents = [
            Document(content=long_content),
            Document(content="Short document about weather."),
        ]

        reranked = reranker.rerank(query="What is machine learning?", documents=documents)

        assert len(reranked) == 2
        for doc in reranked:
            assert doc.reranking_score is not None

    def test_special_characters_in_query(self, reranker, sample_documents):
        """Test reranking with special characters in query."""
        query = "What's ML & AI? @#$%"
        reranked = reranker.rerank(query=query, documents=sample_documents)

        assert len(reranked) == len(sample_documents)

    def test_special_characters_in_documents(self, reranker):
        """Test reranking with special characters in documents."""
        documents = [
            Document(content="Machine learning (ML) & artificial intelligence (AI) are related!"),
            Document(content="Hello @world #test $special %chars"),
        ]

        reranked = reranker.rerank(query="What is ML?", documents=documents)
        assert len(reranked) == 2

    def test_invalid_top_n_ignored(self, sample_documents, ml_query):
        """Test that invalid top_n values are handled gracefully."""
        reranker = AwsBedrockReranker(
            model=COHERE_RERANK_V3_5,
            top_n=-1,  # Invalid value
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

        # Should still work, treating invalid top_n as None
        reranked = reranker.rerank(query=ml_query, documents=sample_documents)
        assert len(reranked) == len(sample_documents)

    def test_unicode_content(self, reranker):
        """Test reranking with Unicode content."""
        documents = [
            Document(content="Machine learning is powerful."),
            Document(content="Aprendizaje automatico es importante."),
        ]

        reranked = reranker.rerank(query="What is machine learning?", documents=documents)
        assert len(reranked) == 2


class TestRerankerWithAdditionalFields:
    """Tests for additional model request fields."""

    def test_additional_model_request_fields(self, sample_documents, ml_query):
        """Test reranker with additional model-specific parameters."""
        reranker = AwsBedrockReranker(
            model=COHERE_RERANK_V3_5,
            top_n=3,
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
            additional_model_request_fields={},  # Empty dict should work
        )

        reranked = reranker.rerank(query=ml_query, documents=sample_documents)
        assert len(reranked) == 3
