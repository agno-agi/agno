import importlib.util
from types import SimpleNamespace

import pytest

from agno.knowledge.embedder.openai import OpenAIEmbedder


@pytest.mark.skipif(not importlib.util.find_spec("openai"), reason="openai package not installed")
def test_dimensions_propagated_when_explicitly_set():
    """Ensure dimensions parameter is passed when explicitly set, regardless of model."""

    class DummyEmbeddings:
        def __init__(self):
            self.last_kwargs = None

        def create(self, **kwargs):
            self.last_kwargs = kwargs
            dims = kwargs.get("dimensions", 1)
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=[0.0] * dims)],
                usage=None,
            )

    class DummyClient:
        def __init__(self):
            self.embeddings = DummyEmbeddings()

    embedder = OpenAIEmbedder(id="text-embedding-v4", dimensions=512)
    embedder.openai_client = DummyClient()

    _ = embedder.get_embedding("hello world")

    assert embedder.openai_client.embeddings.last_kwargs is not None, "Embeddings request not captured"
    assert (
        embedder.openai_client.embeddings.last_kwargs.get("dimensions") == 512
    ), "dimensions parameter not propagated when explicitly set"


@pytest.mark.skipif(not importlib.util.find_spec("openai"), reason="openai package not installed")
def test_dimensions_propagated_for_any_model():
    """Ensure dimensions parameter is passed for ANY model when explicitly set (future-proof)."""

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

    class DummyClient:
        def __init__(self):
            self.embeddings = DummyEmbeddings()

    embedder = OpenAIEmbedder(id="text-embedding-ada-002", dimensions=256)
    embedder.openai_client = DummyClient()

    _ = embedder.get_embedding("test")

    assert embedder.openai_client.embeddings.last_kwargs.get("dimensions") == 256, (
        "dimensions should be passed for legacy models too"
    )

    embedder2 = OpenAIEmbedder(id="text-embedding-v5-ultra", dimensions=2048)
    embedder2.openai_client = DummyClient()

    _ = embedder2.get_embedding("test")

    assert embedder2.openai_client.embeddings.last_kwargs.get("dimensions") == 2048, (
        "dimensions should be passed for any future models"
    )


@pytest.mark.skipif(not importlib.util.find_spec("openai"), reason="openai package not installed")
def test_dimensions_not_passed_when_none():
    """Ensure dimensions parameter is NOT passed when set to None (respects model defaults)."""

    class DummyEmbeddings:
        def __init__(self):
            self.last_kwargs = None

        def create(self, **kwargs):
            self.last_kwargs = kwargs
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=[0.0] * 1536)],
                usage=None,
            )

    class DummyClient:
        def __init__(self):
            self.embeddings = DummyEmbeddings()

    embedder = OpenAIEmbedder(id="text-embedding-3-small")
    embedder.dimensions = None
    embedder.openai_client = DummyClient()

    _ = embedder.get_embedding("test")

    assert "dimensions" not in embedder.openai_client.embeddings.last_kwargs, (
        "dimensions should NOT be passed when None (use model default)"
    )