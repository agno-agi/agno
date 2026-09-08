import json

import httpx
import pytest
from pydantic import ValidationError

from agno.exceptions import ModelAuthenticationError, ModelProviderError, ModelRateLimitError
from agno.knowledge.document import Document
from agno.knowledge.reranker.siliconflow import SiliconflowReranker


@pytest.fixture
def documents():
    return [
        Document(content="Alpha"),
        Document(content="Beta"),
        Document(content="Gamma"),
    ]


def test_rerank_builds_protected_payload_and_preserves_response_order(documents):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url == "https://example.test/v1/rerank"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["X-Test"] == "value"
        assert payload == {
            "custom_option": True,
            "model": "BAAI/bge-reranker-v2-m3",
            "query": "gamma",
            "documents": ["Alpha", "Beta", "Gamma"],
            "top_n": 2,
            "return_documents": False,
            "instruction": "Rank by relevance",
            "max_chunks_per_doc": 8,
            "overlap_tokens": 20,
        }
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 2, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.4},
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reranker = SiliconflowReranker(
            api_key="test-key",
            base_url="https://example.test/v1/",
            top_n=2,
            instruction="Rank by relevance",
            max_chunks_per_doc=8,
            overlap_tokens=20,
            request_params={
                "custom_option": True,
                "model": "overridden-model",
                "query": "overridden-query",
                "top_n": 99,
                "return_documents": True,
            },
            extra_headers={"Authorization": "Bearer wrong-key", "X-Test": "value"},
            http_client=client,
            raise_on_error=True,
        )
        result = reranker.rerank("gamma", documents)

    assert result == [documents[2], documents[0]]
    assert [document.reranking_score for document in result] == [0.95, 0.4]
    assert documents[1].reranking_score is None


def test_rerank_clamps_top_n_to_document_count(documents):
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["top_n"] == 3
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 1, "relevance_score": 0.8},
                    {"index": 2, "relevance_score": 0.7},
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reranker = SiliconflowReranker(api_key="test-key", top_n=100, http_client=client, raise_on_error=True)
        result = reranker.rerank("query", documents)

    assert result == documents


def test_rerank_empty_documents_does_not_call_api():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("API should not be called")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reranker = SiliconflowReranker(api_key="test-key", http_client=client)
        assert reranker.rerank("query", []) == []


@pytest.mark.asyncio
async def test_async_rerank_matches_sync_behavior(documents):
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["top_n"] == 1
        return httpx.Response(200, json={"results": [{"index": 1, "relevance_score": 0.88}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reranker = SiliconflowReranker(api_key="test-key", top_n=1, async_http_client=client, raise_on_error=True)
        result = await reranker.arerank("beta", documents)

    assert result == [documents[1]]
    assert result[0].reranking_score == 0.88


def test_rerank_fails_open_by_default(documents):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "Model overloaded"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reranker = SiliconflowReranker(api_key="test-key", http_client=client)
        assert reranker.rerank("query", documents) == documents


def test_rerank_raises_typed_authentication_error_with_trace_id(documents):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            headers={"x-siliconcloud-trace-id": "trace-123"},
            json={"error": {"message": "Invalid API key"}},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reranker = SiliconflowReranker(api_key="test-key", http_client=client, raise_on_error=True)
        with pytest.raises(ModelAuthenticationError, match="trace-123") as error:
            reranker.rerank("query", documents)

    assert error.value.status_code == 401


def test_rerank_raises_rate_limit_error(documents):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "Rate limited"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reranker = SiliconflowReranker(api_key="test-key", http_client=client, raise_on_error=True)
        with pytest.raises(ModelRateLimitError) as error:
            reranker.rerank("query", documents)

    assert error.value.status_code == 429


def test_rerank_rejects_malformed_results_without_mutating_documents(documents):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.8},
                    {"index": 2, "relevance_score": 0.7},
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reranker = SiliconflowReranker(api_key="test-key", http_client=client, raise_on_error=True)
        with pytest.raises(ModelProviderError, match="unique"):
            reranker.rerank("query", documents)

    assert all(document.reranking_score is None for document in documents)


def test_rerank_maps_timeout_to_provider_error(documents):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reranker = SiliconflowReranker(api_key="test-key", http_client=client, raise_on_error=True)
        with pytest.raises(ModelProviderError) as error:
            reranker.rerank("query", documents)

    assert error.value.status_code == 504


def test_rerank_resolves_api_key_lazily(monkeypatch, documents):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    reranker = SiliconflowReranker(raise_on_error=True)

    with pytest.raises(ModelAuthenticationError):
        reranker.rerank("query", documents)


@pytest.mark.parametrize(
    ("field", "value"),
    [("top_n", 0), ("max_chunks_per_doc", 0), ("overlap_tokens", 81), ("timeout", 0)],
)
def test_reranker_validates_configuration(field, value):
    with pytest.raises(ValidationError):
        SiliconflowReranker(**{field: value})
