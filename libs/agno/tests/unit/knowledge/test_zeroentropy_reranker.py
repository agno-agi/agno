import importlib
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.knowledge.document import Document


@pytest.fixture
def zeroentropy_module(monkeypatch: pytest.MonkeyPatch):
    fake_zeroentropy = ModuleType("zeroentropy")
    fake_zeroentropy.ZeroEntropy = type("ZeroEntropy", (), {})
    fake_zeroentropy.AsyncZeroEntropy = type("AsyncZeroEntropy", (), {})

    monkeypatch.setitem(sys.modules, "zeroentropy", fake_zeroentropy)
    sys.modules.pop("agno.knowledge.reranker.zeroentropy", None)

    module = importlib.import_module("agno.knowledge.reranker.zeroentropy")
    yield module

    sys.modules.pop("agno.knowledge.reranker.zeroentropy", None)


@pytest.fixture
def sample_documents():
    return [
        Document(content="Rerankers reorder retrieved results."),
        Document(content="Transformers are neural networks."),
        Document(content="Retrieval augmented generation uses reranking."),
    ]


def test_rerank_success(zeroentropy_module, sample_documents):
    mock_models = MagicMock()
    mock_models.rerank.return_value = {
        "results": [
            {"index": 2, "relevance_score": 0.92},
            {"index": 0, "relevance_score": 0.81},
            {"index": 1, "relevance_score": 0.12},
        ]
    }
    mock_client = MagicMock()
    mock_client.models = mock_models

    with patch.object(zeroentropy_module, "ZeroEntropy", return_value=mock_client):
        reranker = zeroentropy_module.ZeroEntropyReranker(api_key="test-key")
        reranked = reranker.rerank(query="What is a reranker?", documents=sample_documents)

    assert [doc.content for doc in reranked] == [
        "Retrieval augmented generation uses reranking.",
        "Rerankers reorder retrieved results.",
        "Transformers are neural networks.",
    ]
    assert reranked[0].reranking_score == pytest.approx(0.92)
    assert reranked[1].reranking_score == pytest.approx(0.81)
    assert reranked[2].reranking_score == pytest.approx(0.12)

    call_kwargs = mock_models.rerank.call_args.kwargs
    assert call_kwargs["model"] == "zerank-2"
    assert call_kwargs["query"] == "What is a reranker?"
    assert call_kwargs["documents"] == [doc.content for doc in sample_documents]
    assert "top_n" not in call_kwargs


def test_rerank_empty_documents_returns_empty(zeroentropy_module):
    mock_client = MagicMock()
    mock_client.models = MagicMock()

    with patch.object(zeroentropy_module, "ZeroEntropy", return_value=mock_client):
        reranker = zeroentropy_module.ZeroEntropyReranker(api_key="test-key")
        reranked = reranker.rerank(query="Any query", documents=[])

    assert reranked == []
    mock_client.models.rerank.assert_not_called()


def test_rerank_with_top_n(zeroentropy_module, sample_documents):
    mock_models = MagicMock()
    mock_models.rerank.return_value = {
        "results": [
            {"index": 2, "relevance_score": 0.92},
            {"index": 0, "relevance_score": 0.81},
            {"index": 1, "relevance_score": 0.12},
        ]
    }
    mock_client = MagicMock()
    mock_client.models = mock_models

    with patch.object(zeroentropy_module, "ZeroEntropy", return_value=mock_client):
        reranker = zeroentropy_module.ZeroEntropyReranker(api_key="test-key", top_n=2)
        reranked = reranker.rerank(query="What is a reranker?", documents=sample_documents)

    assert len(reranked) == 2
    assert [doc.content for doc in reranked] == [
        "Retrieval augmented generation uses reranking.",
        "Rerankers reorder retrieved results.",
    ]
    assert mock_models.rerank.call_args.kwargs["top_n"] == 2


def test_rerank_failure_returns_original_documents(zeroentropy_module, sample_documents):
    mock_models = MagicMock()
    mock_models.rerank.side_effect = RuntimeError("boom")
    mock_client = MagicMock()
    mock_client.models = mock_models

    with patch.object(zeroentropy_module, "ZeroEntropy", return_value=mock_client):
        reranker = zeroentropy_module.ZeroEntropyReranker(api_key="test-key")
        reranked = reranker.rerank(query="What is a reranker?", documents=sample_documents)

    assert reranked is sample_documents


@pytest.mark.asyncio
async def test_arerank_success(zeroentropy_module, sample_documents):
    mock_async_models = MagicMock()
    mock_async_models.rerank = AsyncMock(
        return_value={
            "results": [
                {"index": 2, "relevance_score": 0.92},
                {"index": 0, "relevance_score": 0.81},
            ]
        }
    )
    mock_async_client = MagicMock()
    mock_async_client.models = mock_async_models

    with patch.object(zeroentropy_module, "AsyncZeroEntropy", return_value=mock_async_client):
        reranker = zeroentropy_module.ZeroEntropyReranker(api_key="test-key", top_n=2)
        reranked = await reranker.arerank(query="What is a reranker?", documents=sample_documents)

    assert len(reranked) == 2
    assert [doc.content for doc in reranked] == [
        "Retrieval augmented generation uses reranking.",
        "Rerankers reorder retrieved results.",
    ]
    mock_async_models.rerank.assert_awaited_once()
    assert mock_async_models.rerank.call_args.kwargs["top_n"] == 2
