"""
Unit tests for parallel fallback in OpenAIEmbedder batch embedding.

When a batch embedding call fails, the embedder falls back to individual
calls. These tests verify that:
1. The fallback executes calls in parallel (not sequentially)
2. Concurrency is limited by a semaphore
3. Individual failures don't break the entire batch
4. Successful results are collected correctly
5. EMBEDDER_FALLBACK_CONCURRENCY env var is validated properly
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.knowledge.embedder.openai import OpenAIEmbedder


@pytest.fixture()
def embedder():
    """Create an OpenAIEmbedder with mocked async client."""
    mock_aclient = MagicMock()
    e = OpenAIEmbedder(id="text-embedding-3-small", api_key="test-key", async_client=mock_aclient)
    return e, mock_aclient


@pytest.mark.asyncio
async def test_fallback_collects_all_results(embedder):
    """When batch fails, fallback should return one embedding per input text."""
    e, mock_aclient = embedder

    # Make batch call fail
    mock_aclient.embeddings.create = AsyncMock(side_effect=Exception("batch failed"))

    # Make individual calls succeed
    e.async_get_embedding_and_usage = AsyncMock(return_value=([0.1, 0.2, 0.3], {"prompt_tokens": 5, "total_tokens": 5}))

    texts = ["hello", "world", "test"]
    embeddings, usage = await e.async_get_embeddings_batch_and_usage(texts)

    assert len(embeddings) == 3
    assert len(usage) == 3
    assert all(emb == [0.1, 0.2, 0.3] for emb in embeddings)
    assert e.async_get_embedding_and_usage.call_count == 3


@pytest.mark.asyncio
async def test_fallback_handles_individual_failures(embedder):
    """When some individual calls fail, those should return empty embeddings."""
    e, mock_aclient = embedder

    # Make batch call fail
    mock_aclient.embeddings.create = AsyncMock(side_effect=Exception("batch failed"))

    # Make individual calls: first succeeds, second fails, third succeeds
    call_count = 0

    async def mock_individual(text):
        nonlocal call_count
        call_count += 1
        if text == "bad":
            raise Exception("individual failed")
        return [0.1, 0.2], {"prompt_tokens": 3}

    e.async_get_embedding_and_usage = mock_individual

    texts = ["good", "bad", "good2"]
    embeddings, usage = await e.async_get_embeddings_batch_and_usage(texts)

    assert len(embeddings) == 3
    assert len(usage) == 3
    # First and third should succeed
    assert embeddings[0] == [0.1, 0.2]
    assert embeddings[2] == [0.1, 0.2]
    # Second should be empty (failed)
    assert embeddings[1] == []
    assert usage[1] is None


@pytest.mark.asyncio
async def test_fallback_respects_concurrency_limit(embedder):
    """Fallback should limit concurrent calls via semaphore."""
    e, mock_aclient = embedder

    # Make batch call fail
    mock_aclient.embeddings.create = AsyncMock(side_effect=Exception("batch failed"))

    max_concurrent_observed = 0
    current_concurrent = 0
    lock = asyncio.Lock()

    original_fn = AsyncMock(return_value=([0.1], {"prompt_tokens": 1}))

    async def tracking_individual(text):
        nonlocal max_concurrent_observed, current_concurrent
        async with lock:
            current_concurrent += 1
            if current_concurrent > max_concurrent_observed:
                max_concurrent_observed = current_concurrent
        try:
            # Small delay to allow concurrency to build up
            await asyncio.sleep(0.01)
            return await original_fn(text)
        finally:
            async with lock:
                current_concurrent -= 1

    e.async_get_embedding_and_usage = tracking_individual

    # Use more texts than default concurrency (5) to test the semaphore
    texts = [f"text_{i}" for i in range(15)]

    with patch.dict("os.environ", {"EMBEDDER_FALLBACK_CONCURRENCY": "3"}):
        embeddings, usage = await e.async_get_embeddings_batch_and_usage(texts)

    assert len(embeddings) == 15
    # Concurrency should never exceed the semaphore limit of 3
    assert max_concurrent_observed <= 3
    # But it should have been concurrent (more than 1 at a time)
    assert max_concurrent_observed > 1


@pytest.mark.asyncio
async def test_batch_success_skips_fallback(embedder):
    """When batch succeeds, fallback should not be triggered."""
    e, mock_aclient = embedder

    mock_response = MagicMock()
    mock_response.data = [
        MagicMock(embedding=[0.1, 0.2]),
        MagicMock(embedding=[0.3, 0.4]),
    ]
    mock_response.usage = MagicMock()
    mock_response.usage.model_dump.return_value = {"prompt_tokens": 10}

    mock_aclient.embeddings.create = AsyncMock(return_value=mock_response)
    e.async_get_embedding_and_usage = AsyncMock()

    texts = ["hello", "world"]
    embeddings, usage = await e.async_get_embeddings_batch_and_usage(texts)

    assert len(embeddings) == 2
    assert embeddings[0] == [0.1, 0.2]
    # Individual fallback should never be called
    e.async_get_embedding_and_usage.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_all_fail_returns_empty(embedder):
    """When batch and all individual calls fail, return empty embeddings."""
    e, mock_aclient = embedder

    mock_aclient.embeddings.create = AsyncMock(side_effect=Exception("batch failed"))
    e.async_get_embedding_and_usage = AsyncMock(side_effect=Exception("all failed"))

    texts = ["a", "b", "c"]
    embeddings, usage = await e.async_get_embeddings_batch_and_usage(texts)

    assert len(embeddings) == 3
    assert all(emb == [] for emb in embeddings)
    assert all(u is None for u in usage)


@pytest.mark.asyncio
async def test_fallback_non_numeric_concurrency_env_uses_default(embedder):
    """Non-numeric EMBEDDER_FALLBACK_CONCURRENCY should fall back to default 5."""
    e, mock_aclient = embedder

    mock_aclient.embeddings.create = AsyncMock(side_effect=Exception("batch failed"))
    e.async_get_embedding_and_usage = AsyncMock(return_value=([0.1], {"prompt_tokens": 1}))

    texts = ["a", "b"]
    with patch.dict("os.environ", {"EMBEDDER_FALLBACK_CONCURRENCY": "not_a_number"}):
        embeddings, usage = await e.async_get_embeddings_batch_and_usage(texts)

    assert len(embeddings) == 2
    assert all(emb == [0.1] for emb in embeddings)


@pytest.mark.asyncio
async def test_fallback_zero_concurrency_env_uses_minimum_one(embedder):
    """EMBEDDER_FALLBACK_CONCURRENCY=0 should be clamped to 1, not hang."""
    e, mock_aclient = embedder

    mock_aclient.embeddings.create = AsyncMock(side_effect=Exception("batch failed"))
    e.async_get_embedding_and_usage = AsyncMock(return_value=([0.5], {"prompt_tokens": 2}))

    texts = ["x", "y", "z"]
    with patch.dict("os.environ", {"EMBEDDER_FALLBACK_CONCURRENCY": "0"}):
        embeddings, usage = await e.async_get_embeddings_batch_and_usage(texts)

    assert len(embeddings) == 3
    assert all(emb == [0.5] for emb in embeddings)
