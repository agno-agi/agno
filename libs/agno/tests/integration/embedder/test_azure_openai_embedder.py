import os

import pytest

from agno.knowledge.embedder.azure_openai import AzureOpenAIEmbedder


@pytest.fixture
def embedder():
    return AzureOpenAIEmbedder()


@pytest.mark.skipif(
    not os.environ.get("AZURE_OPENAI_API_KEY") and not os.environ.get("AZURE_OPENAI_AD_TOKEN"),
    reason="Azure OpenAI credentials not set",
)
def test_get_embedding(embedder):
    """Test sync embedding returns correct dimensions"""
    embeddings = embedder.get_embedding("The quick brown fox jumps over the lazy dog.")

    assert isinstance(embeddings, list)
    assert len(embeddings) == embedder.dimensions


@pytest.mark.skipif(
    not os.environ.get("AZURE_OPENAI_API_KEY") and not os.environ.get("AZURE_OPENAI_AD_TOKEN"),
    reason="Azure OpenAI credentials not set",
)
@pytest.mark.asyncio()
async def test_async_get_embedding(embedder):
    """Test async embedding returns correct dimensions"""
    embeddings = await embedder.async_get_embedding("Async embedding test")

    assert isinstance(embeddings, list)
    assert len(embeddings) == embedder.dimensions

    if embedder.async_client:
        await embedder.async_client.close()
        embedder.async_client = None


def test_post_init_dimensions_default():
    """Test __post_init__ sets dimensions=1536 for text-embedding-3 models"""
    embedder = AzureOpenAIEmbedder(id="text-embedding-3-small")
    assert embedder.dimensions == 1536


def test_post_init_dimensions_none_for_custom_model():
    """Test __post_init__ leaves dimensions=None for non-text-embedding-3 models"""
    embedder = AzureOpenAIEmbedder(id="Cohere-embed-v3-multilingual")
    assert embedder.dimensions is None


def test_post_init_dimensions_preserved_when_explicit():
    """Test explicitly set dimensions are not overridden"""
    embedder = AzureOpenAIEmbedder(id="text-embedding-3-small", dimensions=512)
    assert embedder.dimensions == 512
