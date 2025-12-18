"""Tests for SemanticChunking wrapper that adapts Agno embedders to chonkie."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

from agno.knowledge.chunking.semantic import SemanticChunking
from agno.knowledge.document.base import Document


class DummyEmbedder:
    """Minimal embedder stub for testing."""

    def __init__(self, id: str = "azure-embedding-deployment", dimensions: int = 1024):
        self.id = id
        self.dimensions = dimensions

    def get_embedding(self, text: str):
        return [0.0] * self.dimensions


class FakeBaseEmbeddings:
    """Fake BaseEmbeddings for testing."""

    pass


def _install_fake_chonkie(chunker_class):
    """Install fake chonkie module with embeddings submodule."""
    chonkie_mod = ModuleType("chonkie")
    setattr(chonkie_mod, "SemanticChunker", chunker_class)

    embeddings_mod = ModuleType("chonkie.embeddings")
    base_mod = ModuleType("chonkie.embeddings.base")
    setattr(base_mod, "BaseEmbeddings", FakeBaseEmbeddings)

    setattr(embeddings_mod, "base", base_mod)
    setattr(chonkie_mod, "embeddings", embeddings_mod)

    sys.modules["chonkie"] = chonkie_mod
    sys.modules["chonkie.embeddings"] = embeddings_mod
    sys.modules["chonkie.embeddings.base"] = base_mod


def _remove_fake_chonkie():
    """Remove fake chonkie modules."""
    sys.modules.pop("chonkie", None)
    sys.modules.pop("chonkie.embeddings", None)
    sys.modules.pop("chonkie.embeddings.base", None)


@pytest.fixture
def fake_chonkie_capturing():
    """Fixture that installs fake chonkie and captures init kwargs."""
    captured = {}

    class FakeSemanticChunker:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def chunk(self, text: str):
            return [SimpleNamespace(text=text)]

    _install_fake_chonkie(FakeSemanticChunker)
    yield captured
    _remove_fake_chonkie()


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
    call_log = []

    class TrackingEmbedder:
        def __init__(self):
            self.dimensions = 1536

        def get_embedding(self, text: str):
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
