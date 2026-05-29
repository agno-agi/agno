"""Tests for SemanticChunking wrapper that adapts Agno embedders to chonkie."""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import List
from unittest.mock import patch

import pytest

from agno.knowledge.chunking.semantic import SemanticChunking
from agno.knowledge.document.base import Document
from agno.knowledge.embedder.base import Embedder


@dataclass
class DummyEmbedder(Embedder):
    """Minimal embedder stub for testing."""

    id: str = "azure-embedding-deployment"
    dimensions: int = 1024

    def get_embedding(self, text: str) -> List[float]:
        return [0.0] * self.dimensions


@pytest.fixture
def fake_chonkie_capturing():
    """Fixture that patches SemanticChunker and captures init kwargs."""
    captured = {}

    class FakeSemanticChunker:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def chunk(self, text: str):
            return [SimpleNamespace(text=text)]

    with patch("agno.knowledge.chunking.semantic.SemanticChunker", FakeSemanticChunker):
        yield captured


def test_semantic_chunking_wraps_embedder(fake_chonkie_capturing):
    """Test that SemanticChunking wraps embedder and passes to chonkie."""
    embedder = DummyEmbedder(id="azure-deploy", dimensions=1536)
    sc = SemanticChunking(embedder=embedder, chunk_size=123, similarity_threshold=0.7)

    _ = sc.chunk(Document(content="Hello world"))

    wrapper = fake_chonkie_capturing["embedding_model"]
    assert wrapper is not None
    assert hasattr(wrapper, "_embedder")
    assert wrapper._embedder is embedder
    assert fake_chonkie_capturing["chunk_size"] == 123
    assert abs(fake_chonkie_capturing["threshold"] - 0.7) < 1e-9


def test_semantic_chunking_wrapper_calls_embedder(fake_chonkie_capturing):
    """Test that wrapper's embed method calls the Agno embedder."""
    call_log: List[str] = []

    @dataclass
    class TrackingEmbedder(Embedder):
        dimensions: int = 1536

        def get_embedding(self, text: str) -> List[float]:
            call_log.append(text)
            return [0.1] * self.dimensions

    embedder = TrackingEmbedder()
    sc = SemanticChunking(embedder=embedder, chunk_size=500)

    _ = sc.chunk(Document(content="Test content"))

    wrapper = fake_chonkie_capturing["embedding_model"]
    result = wrapper.embed("test text")

    assert "test text" in call_log
    assert len(result) == 1536


def test_semantic_chunking_wrapper_dimension(fake_chonkie_capturing):
    """Test that wrapper exposes correct dimension from embedder."""
    embedder = DummyEmbedder(id="test", dimensions=768)
    sc = SemanticChunking(embedder=embedder)

    _ = sc.chunk(Document(content="Test"))

    wrapper = fake_chonkie_capturing["embedding_model"]
    assert wrapper.dimension == 768


def test_semantic_chunking_passes_all_parameters(fake_chonkie_capturing):
    """Test that all SemanticChunking params are passed to chonkie."""
    embedder = DummyEmbedder()
    sc = SemanticChunking(
        embedder=embedder,
        chunk_size=500,
        similarity_threshold=0.6,
        similarity_window=5,
        min_sentences_per_chunk=2,
        min_characters_per_sentence=30,
        delimiters=[". ", "! "],
        include_delimiters="next",
        skip_window=1,
        filter_window=7,
        filter_polyorder=2,
        filter_tolerance=0.3,
    )

    _ = sc.chunk(Document(content="Test"))

    assert fake_chonkie_capturing["chunk_size"] == 500
    assert abs(fake_chonkie_capturing["threshold"] - 0.6) < 1e-9
    assert fake_chonkie_capturing["similarity_window"] == 5
    assert fake_chonkie_capturing["min_sentences_per_chunk"] == 2
    assert fake_chonkie_capturing["min_characters_per_sentence"] == 30
    assert fake_chonkie_capturing["delim"] == [". ", "! "]
    assert fake_chonkie_capturing["include_delim"] == "next"
    assert fake_chonkie_capturing["skip_window"] == 1
    assert fake_chonkie_capturing["filter_window"] == 7
    assert fake_chonkie_capturing["filter_polyorder"] == 2
    assert abs(fake_chonkie_capturing["filter_tolerance"] - 0.3) < 1e-9


def test_semantic_chunking_default_embedder():
    """Test that OpenAIEmbedder is used when no embedder provided."""
    sc = SemanticChunking(chunk_size=100)
    assert sc.embedder is not None
    assert "OpenAIEmbedder" in type(sc.embedder).__name__


def test_semantic_chunking_chunker_params(fake_chonkie_capturing):
    """Test that chunker_params are passed through to chonkie."""
    embedder = DummyEmbedder()
    sc = SemanticChunking(
        embedder=embedder,
        chunk_size=500,
        chunker_params={"future_param": "value", "another_param": 42},
    )

    _ = sc.chunk(Document(content="Test"))

    assert fake_chonkie_capturing["chunk_size"] == 500
    assert fake_chonkie_capturing["future_param"] == "value"
    assert fake_chonkie_capturing["another_param"] == 42


def test_semantic_chunking_chunker_params_override(fake_chonkie_capturing):
    """Test that chunker_params can override default params."""
    embedder = DummyEmbedder()
    sc = SemanticChunking(
        embedder=embedder,
        chunk_size=500,
        similarity_window=3,  # default
        chunker_params={"similarity_window": 10},  # override
    )

    _ = sc.chunk(Document(content="Test"))

    assert fake_chonkie_capturing["similarity_window"] == 10


def test_semantic_chunking_string_embedder_passed_directly(fake_chonkie_capturing):
    """Test that string embedder is passed directly to chonkie without wrapping."""
    sc = SemanticChunking(embedder="text-embedding-3-small", chunk_size=100)

    _ = sc.chunk(Document(content="Test"))

    assert fake_chonkie_capturing["embedding_model"] == "text-embedding-3-small"
    assert isinstance(fake_chonkie_capturing["embedding_model"], str)


def test_semantic_chunking_base_embeddings_not_wrapped(fake_chonkie_capturing):
    """Test that BaseEmbeddings subclass is passed directly without wrapping."""
    import numpy as np
    from chonkie.embeddings.base import BaseEmbeddings

    class CustomChonkieEmbedder(BaseEmbeddings):
        def embed(self, text: str):
            return np.zeros(768, dtype=np.float32)

        @property
        def dimension(self):
            return 768

        def get_tokenizer(self):
            return lambda x: len(x.split())

    custom_embedder = CustomChonkieEmbedder()
    sc = SemanticChunking(embedder=custom_embedder, chunk_size=100)

    _ = sc.chunk(Document(content="Test"))

    # Should be the same object, not wrapped
    assert fake_chonkie_capturing["embedding_model"] is custom_embedder
    assert not hasattr(fake_chonkie_capturing["embedding_model"], "_embedder")


def test_semantic_chunking_wrapper_dtype_float32(fake_chonkie_capturing):
    """Test that wrapper.embed() returns numpy array with float32 dtype."""
    import numpy as np

    embedder = DummyEmbedder(dimensions=1536)
    sc = SemanticChunking(embedder=embedder, chunk_size=100)

    _ = sc.chunk(Document(content="Test"))

    wrapper = fake_chonkie_capturing["embedding_model"]
    result = wrapper.embed("test text")

    assert isinstance(result, np.ndarray)
    assert result.dtype == np.float32
