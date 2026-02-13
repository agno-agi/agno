import pytest

from agno.knowledge.embedder.litellm import LiteLLMEmbedder


@pytest.fixture
def embedder():
    return LiteLLMEmbedder(id="openai/text-embedding-3-small")


def test_embedder_initialization(embedder):
    """Test that the embedder initializes correctly"""
    assert embedder is not None
    assert embedder.id == "openai/text-embedding-3-small"
    assert embedder.batch_size == 100
    assert not embedder.enable_batch


def test_get_embedding(embedder):
    """Test that we can get embeddings for a simple text"""
    text = "The quick brown fox jumps over the lazy dog."
    embeddings = embedder.get_embedding(text)

    assert isinstance(embeddings, list)
    assert len(embeddings) > 0
    assert all(isinstance(x, float) for x in embeddings)


def test_get_embedding_and_usage(embedder):
    """Test that we can get embeddings with usage information"""
    text = "Test embedding with usage information."
    embedding, usage = embedder.get_embedding_and_usage(text)

    assert isinstance(embedding, list)
    assert len(embedding) > 0
    assert all(isinstance(x, float) for x in embedding)

    assert usage is None or isinstance(usage, dict)
    if usage:
        assert "total_tokens" in usage or "prompt_tokens" in usage


@pytest.mark.asyncio
async def test_async_get_embedding(embedder):
    """Test async embedding functionality"""
    text = "Async test text"
    embedding = await embedder.async_get_embedding(text)

    assert isinstance(embedding, list)
    assert len(embedding) > 0
    assert all(isinstance(x, float) for x in embedding)


@pytest.mark.asyncio
async def test_async_get_embedding_and_usage(embedder):
    """Test async embedding with usage"""
    text = "Async test with usage"
    embedding, usage = await embedder.async_get_embedding_and_usage(text)

    assert isinstance(embedding, list)
    assert len(embedding) > 0
    assert all(isinstance(x, float) for x in embedding)
    
    assert usage is None or isinstance(usage, dict)


@pytest.mark.asyncio
async def test_async_batch_embeddings(embedder):
    """Test async batch embedding functionality"""
    texts = ["First text", "Second text", "Third text"]
    embeddings, usages = await embedder.async_get_embeddings_batch_and_usage(texts)

    assert isinstance(embeddings, list)
    assert len(embeddings) == len(texts)
    assert all(isinstance(emb, list) for emb in embeddings)
    assert all(len(emb) > 0 for emb in embeddings)

    assert isinstance(usages, list)
    assert len(usages) == len(texts)


def test_special_characters(embedder):
    """Test that special characters are handled correctly"""
    text = "Hello, world! こんにちは 123 @#$%"
    embeddings = embedder.get_embedding(text)

    assert isinstance(embeddings, list)
    assert len(embeddings) > 0
    assert all(isinstance(x, float) for x in embeddings)


def test_empty_text(embedder):
    """Test handling of empty text"""
    embeddings = embedder.get_embedding("")
    assert isinstance(embeddings, list)


def test_different_models():
    """Test different LiteLLM models"""
    models_to_test = [
        "openai/text-embedding-3-small",
        "openai/text-embedding-ada-002",
    ]
    
    text = "Test text for different models"
    
    for model_id in models_to_test:
        embedder = LiteLLMEmbedder(id=model_id)
        try:
            embeddings = embedder.get_embedding(text)
            assert isinstance(embeddings, list)
            if embeddings: 
                assert all(isinstance(x, float) for x in embeddings)
        except Exception as e:
            pytest.skip(f"Model {model_id} not available: {e}")