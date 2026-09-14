from unittest.mock import AsyncMock, MagicMock

import pytest
from openai.types.create_embedding_response import CreateEmbeddingResponse

from agno.knowledge.embedder.azure_openai import AzureOpenAIEmbedder
from agno.knowledge.embedder.openai import OpenAIEmbedder


@pytest.mark.asyncio
@pytest.mark.parametrize("embedder_cls", [OpenAIEmbedder, AzureOpenAIEmbedder])
@pytest.mark.parametrize("indices", [[2, 0, 1], [0, 2], [2], []])
async def test_batch_preserves_input_positions(embedder_cls, indices):
    response = CreateEmbeddingResponse(
        data=[{"object": "embedding", "index": index, "embedding": [float(index)]} for index in indices],
        model="test-embedding",
        object="list",
        usage={"prompt_tokens": 3, "total_tokens": 3},
    )
    client = MagicMock()
    client.embeddings.create = AsyncMock(return_value=response)
    embedder = embedder_cls(async_client=client)

    embeddings, usage = await embedder.async_get_embeddings_batch_and_usage(["first", "second", "third"])

    assert embeddings == [[float(index)] if index in indices else [] for index in range(3)]
    assert len(usage) == 3
    client.embeddings.create.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("embedder_cls", [OpenAIEmbedder, AzureOpenAIEmbedder])
async def test_response_indices_restart_for_each_batch(embedder_cls):
    def response(indices):
        return CreateEmbeddingResponse(
            data=[{"object": "embedding", "index": index, "embedding": [value]} for index, value in indices],
            model="test-embedding",
            object="list",
            usage={"prompt_tokens": 2, "total_tokens": 2},
        )

    client = MagicMock()
    client.embeddings.create = AsyncMock(side_effect=[response([(1, 2.0), (0, 1.0)]), response([(0, 3.0)])])
    embedder = embedder_cls(async_client=client, batch_size=2)

    embeddings, usage = await embedder.async_get_embeddings_batch_and_usage(["first", "second", "third"])

    assert embeddings == [[1.0], [2.0], [3.0]]
    assert len(usage) == 3
    assert client.embeddings.create.await_count == 2
