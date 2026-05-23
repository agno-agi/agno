import importlib.util
from types import SimpleNamespace

import pytest

from agno.knowledge.embedder.openai import OpenAIEmbedder


class DummyEmbeddings:
    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        dims = kwargs.get("dimensions", 1536)
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.0] * dims)],
            usage=None,
        )


class DummyAsyncEmbeddings:
    def __init__(self):
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        dims = kwargs.get("dimensions", 1536)
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.0] * dims)],
            usage=None,
        )


class DummyClient:
    def __init__(self):
        self.embeddings = DummyEmbeddings()


class DummyAsyncClient:
    def __init__(self):
        self.embeddings = DummyAsyncEmbeddings()


@pytest.mark.skipif(not importlib.util.find_spec("openai"), reason="openai package not installed")
def test_dimensions_passed_for_text_embedding_3_models():
    """Dimensions should be passed for OpenAI text-embedding-3-* models."""
    embedder = OpenAIEmbedder(id="text-embedding-3-small", dimensions=512)
    embedder.openai_client = DummyClient()

    embedder.get_embedding("test")

    assert embedder.openai_client.embeddings.last_kwargs is not None
    assert embedder.openai_client.embeddings.last_kwargs.get("dimensions") == 512


@pytest.mark.skipif(not importlib.util.find_spec("openai"), reason="openai package not installed")
def test_dimensions_passed_with_custom_base_url():
    """Dimensions should be passed for third-party APIs using custom base_url (e.g., DashScope)."""
    embedder = OpenAIEmbedder(
        id="text-embedding-v4",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        dimensions=1024,
    )
    embedder.openai_client = DummyClient()

    embedder.get_embedding("test")

    assert embedder.openai_client.embeddings.last_kwargs is not None
    assert embedder.openai_client.embeddings.last_kwargs.get("dimensions") == 1024


@pytest.mark.skipif(not importlib.util.find_spec("openai"), reason="openai package not installed")
def test_dimensions_not_passed_for_legacy_openai_models():
    """Dimensions should NOT be passed for legacy OpenAI models like ada-002 (they don't support it)."""
    embedder = OpenAIEmbedder(id="text-embedding-ada-002", dimensions=256)
    embedder.openai_client = DummyClient()

    embedder.get_embedding("test")

    assert embedder.openai_client.embeddings.last_kwargs is not None
    assert "dimensions" not in embedder.openai_client.embeddings.last_kwargs


@pytest.mark.skipif(not importlib.util.find_spec("openai"), reason="openai package not installed")
@pytest.mark.asyncio
async def test_async_dimensions_passed_with_custom_base_url():
    """Async path should also pass dimensions for custom base_url."""
    embedder = OpenAIEmbedder(
        id="text-embedding-v4",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        dimensions=768,
    )
    embedder.async_client = DummyAsyncClient()

    await embedder.async_get_embedding("test")

    assert embedder.async_client.embeddings.last_kwargs is not None
    assert embedder.async_client.embeddings.last_kwargs.get("dimensions") == 768


@pytest.mark.skipif(not importlib.util.find_spec("openai"), reason="openai package not installed")
@pytest.mark.asyncio
async def test_async_dimensions_not_passed_for_legacy_models():
    """Async path should NOT pass dimensions for legacy models without base_url."""
    embedder = OpenAIEmbedder(id="text-embedding-ada-002", dimensions=256)
    embedder.async_client = DummyAsyncClient()

    await embedder.async_get_embedding("test")

    assert embedder.async_client.embeddings.last_kwargs is not None
    assert "dimensions" not in embedder.async_client.embeddings.last_kwargs
