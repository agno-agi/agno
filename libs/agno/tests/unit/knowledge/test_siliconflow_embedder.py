import json

import httpx
import pytest

from agno.exceptions import ModelAuthenticationError, ModelProviderError, ModelRateLimitError
from agno.knowledge.embedder.siliconflow import SiliconflowEmbedder


def _embedding_response(vectors, usage=None):
    return {
        "object": "list",
        "model": "test-model",
        "data": [{"object": "embedding", "embedding": vector, "index": index} for index, vector in enumerate(vectors)],
        "usage": usage,
    }


def test_default_model_and_dimensions():
    embedder = SiliconflowEmbedder()

    assert embedder.id == "BAAI/bge-m3"
    assert embedder.dimensions == 1024
    assert embedder.enable_batch is True
    assert embedder.batch_size == 32


def test_custom_model_requires_explicit_dimensions():
    with pytest.raises(ValueError, match="dimensions must be provided"):
        SiliconflowEmbedder(id="custom/model")


@pytest.mark.parametrize("batch_size", [0, 33, True])
def test_batch_size_is_validated(batch_size):
    with pytest.raises(ValueError, match="batch_size"):
        SiliconflowEmbedder(batch_size=batch_size)


def test_get_embedding_uses_float_payload_and_omits_dimensions_for_bge():
    vector = [0.25] * 1024

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url == "https://example.test/v1/embeddings"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["X-Test"] == "value"
        assert payload == {
            "custom_option": True,
            "model": "BAAI/bge-m3",
            "input": "hello",
            "encoding_format": "float",
        }
        return httpx.Response(200, json=_embedding_response([vector]))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        embedder = SiliconflowEmbedder(
            api_key="test-key",
            base_url="https://example.test/v1/",
            request_params={
                "custom_option": True,
                "model": "overridden-model",
                "input": "overridden-input",
                "encoding_format": "base64",
                "dimensions": 5,
            },
            extra_headers={"Authorization": "Bearer wrong-key", "X-Test": "value"},
            http_client=client,
        )
        result = embedder.get_embedding("hello")

    assert result == vector


def test_qwen_model_sends_configured_dimensions():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["dimensions"] == 2
        return httpx.Response(200, json=_embedding_response([[0.1, 0.2]]))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        embedder = SiliconflowEmbedder(
            id="Qwen/Qwen3-Embedding-0.6B",
            dimensions=2,
            api_key="test-key",
            http_client=client,
        )
        assert embedder.get_embedding("hello") == [0.1, 0.2]


def test_send_dimensions_can_be_overridden():
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["dimensions"] == 2
        return httpx.Response(200, json=_embedding_response([[0.1, 0.2]]))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        embedder = SiliconflowEmbedder(
            id="custom/model",
            dimensions=2,
            send_dimensions=True,
            api_key="test-key",
            http_client=client,
        )
        assert embedder.get_embedding("hello") == [0.1, 0.2]


def test_get_embedding_and_usage_returns_usage():
    usage = {"prompt_tokens": 3, "total_tokens": 3}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_embedding_response([[0.1, 0.2]], usage))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        embedder = SiliconflowEmbedder(id="custom/model", dimensions=2, api_key="test-key", http_client=client)
        embedding, result_usage = embedder.get_embedding_and_usage("hello")

    assert embedding == [0.1, 0.2]
    assert result_usage == usage


def test_sync_batch_chunks_requests_restores_index_order_and_copies_usage():
    request_sizes = []
    usage = {"prompt_tokens": 10, "total_tokens": 10}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        inputs = payload["input"]
        request_sizes.append(len(inputs))
        data = [
            {"object": "embedding", "embedding": [float(index), 1.0], "index": index}
            for index in reversed(range(len(inputs)))
        ]
        return httpx.Response(200, json={"data": data, "usage": usage})

    texts = [f"text-{index}" for index in range(35)]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        embedder = SiliconflowEmbedder(id="custom/model", dimensions=2, api_key="test-key", http_client=client)
        embeddings, usages = embedder.get_embeddings_batch_and_usage(texts)

    assert request_sizes == [32, 3]
    assert embeddings[0] == [0.0, 1.0]
    assert embeddings[31] == [31.0, 1.0]
    assert embeddings[32] == [0.0, 1.0]
    assert len(embeddings) == len(usages) == len(texts)
    assert all(item == usage for item in usages)
    assert usages[0] is not usages[1]


@pytest.mark.asyncio
async def test_async_single_and_batch_embedding():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        inputs = payload["input"]
        values = inputs if isinstance(inputs, list) else [inputs]
        return httpx.Response(
            200,
            json=_embedding_response([[float(index), 0.5] for index, _ in enumerate(values)], {"total_tokens": 4}),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        embedder = SiliconflowEmbedder(id="custom/model", dimensions=2, api_key="test-key", async_http_client=client)
        embedding, usage = await embedder.async_get_embedding_and_usage("hello")
        embeddings, usages = await embedder.async_get_embeddings_batch_and_usage(["one", "two"])

    assert embedding == [0.0, 0.5]
    assert usage == {"total_tokens": 4}
    assert embeddings == [[0.0, 0.5], [1.0, 0.5]]
    assert usages == [{"total_tokens": 4}, {"total_tokens": 4}]


def test_empty_batch_returns_empty_without_api_call():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("API should not be called")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        embedder = SiliconflowEmbedder(api_key="test-key", http_client=client)
        assert embedder.get_embeddings_batch_and_usage([]) == ([], [])


def test_invalid_text_is_rejected_before_api_call():
    embedder = SiliconflowEmbedder(api_key="test-key")

    with pytest.raises(ValueError, match="non-empty"):
        embedder.get_embedding("")


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, ModelAuthenticationError),
        (403, ModelAuthenticationError),
        (429, ModelRateLimitError),
        (503, ModelProviderError),
    ],
)
def test_http_errors_are_mapped_to_agno_exceptions(status_code, error_type):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"message": "provider error"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        embedder = SiliconflowEmbedder(api_key="test-key", http_client=client)
        with pytest.raises(error_type) as error:
            embedder.get_embedding("hello")

    assert error.value.status_code == status_code


def test_malformed_embedding_dimension_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_embedding_response([[0.1]]))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        embedder = SiliconflowEmbedder(id="custom/model", dimensions=2, api_key="test-key", http_client=client)
        with pytest.raises(ModelProviderError, match="2 values"):
            embedder.get_embedding("hello")


def test_timeout_is_mapped_to_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        embedder = SiliconflowEmbedder(api_key="test-key", http_client=client)
        with pytest.raises(ModelProviderError) as error:
            embedder.get_embedding("hello")

    assert error.value.status_code == 504


def test_api_key_is_resolved_lazily(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    embedder = SiliconflowEmbedder()

    with pytest.raises(ModelAuthenticationError):
        embedder.get_embedding("hello")
