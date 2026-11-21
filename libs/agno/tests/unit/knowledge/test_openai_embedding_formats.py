import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from openai import AsyncAzureOpenAI, AsyncOpenAI, AzureOpenAI, OpenAI

from agno.exceptions import EmbeddingError
from agno.knowledge.embedder.azure_openai import AzureOpenAIEmbedder
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.embedder.openai_like import OpenAILikeEmbedder

VECTORS = [[1.0, -2.5, 0.125], [0.0, 0.5, -1.0]]
BASE64_VECTORS = ["AACAPwAAIMAAAAA+", "AAAAAAAAAD8AAIC/"]
USAGE = {"prompt_tokens": 3, "total_tokens": 3}


@pytest.mark.asyncio
@pytest.mark.parametrize("embedder_type", [OpenAIEmbedder, AzureOpenAIEmbedder, OpenAILikeEmbedder])
@pytest.mark.parametrize("encoding", ["float", "base64", "base64_override"])
@pytest.mark.parametrize(
    "method",
    [
        "get_embedding",
        "get_embedding_and_usage",
        "async_get_embedding",
        "async_get_embedding_and_usage",
        "async_get_embeddings_batch_and_usage",
    ],
)
async def test_embedding_formats_with_sdk(embedder_type, encoding, method):
    encoding_format = "base64" if encoding == "base64_override" else encoding
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["encoding_format"] == encoding_format
        texts = body["input"] if isinstance(body["input"], list) else [body["input"]]
        vectors = BASE64_VECTORS if encoding_format == "base64" else VECTORS
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "text-embedding-3-small",
                "data": [
                    {"object": "embedding", "index": index, "embedding": vectors[index]} for index in range(len(texts))
                ],
                "usage": USAGE,
            },
        )

    client_kwargs = {"api_key": "test", "base_url": "https://embeddings.test/v1", "max_retries": 0}
    sync_client_type, async_client_type = OpenAI, AsyncOpenAI
    if embedder_type is AzureOpenAIEmbedder:
        sync_client_type, async_client_type = AzureOpenAI, AsyncAzureOpenAI
        client_kwargs["api_version"] = "2024-10-21"

    with sync_client_type(http_client=httpx.Client(transport=httpx.MockTransport(respond)), **client_kwargs) as client:
        async with async_client_type(
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)), **client_kwargs
        ) as async_client:
            embedder = embedder_type(
                openai_client=client,
                async_client=async_client,
                encoding_format="float" if encoding == "base64_override" else encoding,
                request_params={"encoding_format": "base64"} if encoding == "base64_override" else None,
            )
            is_batch = method == "async_get_embeddings_batch_and_usage"
            result = getattr(embedder, method)(["first", "second"] if is_batch else "first")
            if method.startswith("async_"):
                result = await result

    if method.endswith("and_usage"):
        embeddings, usage = result
        assert usage == ([USAGE, USAGE] if is_batch else USAGE)
    else:
        embeddings = result
    assert embeddings == (VECTORS if is_batch else VECTORS[0])
    assert len(requests) == 1


@pytest.mark.parametrize("embedder_type", [OpenAIEmbedder, AzureOpenAIEmbedder])
@pytest.mark.parametrize("embedding", ["%%%", "AAAA"])
def test_invalid_base64_embedding_raises_embedding_error(embedder_type, embedding):
    client = MagicMock()
    client.embeddings.create.return_value = SimpleNamespace(data=[SimpleNamespace(embedding=embedding)])
    embedder = embedder_type(openai_client=client, encoding_format="base64")

    with pytest.raises(EmbeddingError, match="Failed to generate embedding"):
        embedder.get_embedding("first")
