"""Unit tests for SentenceTransformerReranker model caching.

Verifies that the CrossEncoder model is created once and reused across
multiple rerank calls, preventing VRAM memory leaks.
"""

from unittest.mock import MagicMock, patch

import pytest

from agno.knowledge.document import Document


class _FakeNdArray:
    """Minimal stand-in for a numpy ndarray so we can avoid importing numpy."""

    def __init__(self, values):
        self._values = list(values)

    def tolist(self):
        return self._values


@pytest.fixture
def sample_documents():
    return [
        Document(content="Machine learning is a subset of artificial intelligence."),
        Document(content="The weather in Paris is typically mild in spring."),
        Document(content="Deep learning uses neural networks with many layers."),
    ]


@pytest.fixture
def mock_cross_encoder():
    """Mock sentence_transformers module and yield the mock CrossEncoder class."""
    mock_cross_encoder_class = MagicMock()
    mock_module = MagicMock(CrossEncoder=mock_cross_encoder_class)

    with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
        with patch("agno.knowledge.reranker.sentence_transformer.CrossEncoder", mock_cross_encoder_class):
            yield mock_cross_encoder_class


class TestSentenceTransformerRerankerCaching:
    """Tests that the CrossEncoder model is cached and reused."""

    def test_cross_encoder_created_once_across_multiple_rerank_calls(self, mock_cross_encoder, sample_documents):
        """The CrossEncoder should be instantiated only once, even after multiple rerank calls."""
        from agno.knowledge.reranker.sentence_transformer import SentenceTransformerReranker

        mock_instance = MagicMock()
        mock_instance.predict.return_value = _FakeNdArray([0.9, 0.1, 0.7])
        mock_cross_encoder.return_value = mock_instance

        reranker = SentenceTransformerReranker()

        reranker.rerank(query="What is AI?", documents=sample_documents)
        reranker.rerank(query="Tell me about weather", documents=sample_documents)
        reranker.rerank(query="Neural networks", documents=sample_documents)

        assert mock_cross_encoder.call_count == 1

    def test_client_property_returns_same_instance(self, mock_cross_encoder):
        """The client property should return the same CrossEncoder instance each time."""
        from agno.knowledge.reranker.sentence_transformer import SentenceTransformerReranker

        mock_instance = MagicMock()
        mock_cross_encoder.return_value = mock_instance

        reranker = SentenceTransformerReranker()

        client1 = reranker.client
        client2 = reranker.client

        assert client1 is client2
        assert mock_cross_encoder.call_count == 1

    def test_cross_encoder_initialized_with_correct_params(self, mock_cross_encoder):
        """The CrossEncoder should be initialized with the model name and kwargs."""
        from agno.knowledge.reranker.sentence_transformer import SentenceTransformerReranker

        mock_cross_encoder.return_value = MagicMock()

        model_kwargs = {"torch_dtype": "float16"}
        reranker = SentenceTransformerReranker(
            model="custom/reranker-model",
            model_kwargs=model_kwargs,
        )

        _ = reranker.client

        mock_cross_encoder.assert_called_once_with(
            model_name_or_path="custom/reranker-model",
            model_kwargs=model_kwargs,
        )


class TestSentenceTransformerRerankerBehavior:
    """Tests for correct reranking behavior."""

    def test_rerank_returns_documents_sorted_by_score(self, mock_cross_encoder, sample_documents):
        """Documents should be returned sorted by reranking score in descending order."""
        from agno.knowledge.reranker.sentence_transformer import SentenceTransformerReranker

        mock_instance = MagicMock()
        mock_instance.predict.return_value = _FakeNdArray([0.5, 0.9, 0.1])
        mock_cross_encoder.return_value = mock_instance

        reranker = SentenceTransformerReranker()
        result = reranker.rerank(query="test query", documents=sample_documents)

        scores = [doc.reranking_score for doc in result]
        assert scores == sorted(scores, reverse=True)
        assert scores == [0.9, 0.5, 0.1]

    def test_rerank_empty_documents_returns_empty(self, mock_cross_encoder):
        """Reranking an empty list should return an empty list without creating the client."""
        from agno.knowledge.reranker.sentence_transformer import SentenceTransformerReranker

        reranker = SentenceTransformerReranker()
        result = reranker.rerank(query="test", documents=[])

        assert result == []
        mock_cross_encoder.assert_not_called()

    def test_rerank_with_top_n(self, mock_cross_encoder, sample_documents):
        """When top_n is set, only the top N documents should be returned."""
        from agno.knowledge.reranker.sentence_transformer import SentenceTransformerReranker

        mock_instance = MagicMock()
        mock_instance.predict.return_value = _FakeNdArray([0.5, 0.9, 0.1])
        mock_cross_encoder.return_value = mock_instance

        reranker = SentenceTransformerReranker(top_n=2)
        result = reranker.rerank(query="test query", documents=sample_documents)

        assert len(result) == 2
        assert result[0].reranking_score == 0.9
        assert result[1].reranking_score == 0.5

    def test_rerank_handles_prediction_error_gracefully(self, mock_cross_encoder, sample_documents):
        """If predict raises an error, rerank should return the original documents."""
        from agno.knowledge.reranker.sentence_transformer import SentenceTransformerReranker

        mock_instance = MagicMock()
        mock_instance.predict.side_effect = RuntimeError("CUDA out of memory")
        mock_cross_encoder.return_value = mock_instance

        reranker = SentenceTransformerReranker()
        result = reranker.rerank(query="test", documents=sample_documents)

        assert result == sample_documents

    def test_different_reranker_instances_have_separate_clients(self, mock_cross_encoder):
        """Different reranker instances should each have their own CrossEncoder client."""
        from agno.knowledge.reranker.sentence_transformer import SentenceTransformerReranker

        mock_cross_encoder.return_value = MagicMock()

        reranker1 = SentenceTransformerReranker(model="model-a")
        reranker2 = SentenceTransformerReranker(model="model-b")

        _ = reranker1.client
        _ = reranker2.client

        assert mock_cross_encoder.call_count == 2
