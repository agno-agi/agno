"""Integration tests for FastEmbedEmbedder with real fastembed library.

These tests require the fastembed package to be installed.
Caching behavior is tested in unit tests (test_reader_embedder_state.py).
"""
import pytest

pytest.importorskip("fastembed")

from agno.knowledge.embedder.fastembed import FastEmbedEmbedder


@pytest.fixture
def embedder():
    return FastEmbedEmbedder()


def test_embedder_initialization(embedder):
    """Test that the embedder initializes correctly with real fastembed."""
    assert embedder is not None
    assert embedder.id == "BAAI/bge-small-en-v1.5"
    assert embedder.fastembed_client is not None


def test_get_embedding(embedder):
    """Test that we can get embeddings for a simple text."""
    text = "The quick brown fox jumps over the lazy dog."
    embeddings = embedder.get_embedding(text)

    assert isinstance(embeddings, list)
    assert len(embeddings) > 0
    assert all(isinstance(x, float) for x in embeddings)


def test_special_characters(embedder):
    """Test that special characters are handled correctly."""
    text = "Hello, world! 123 @#$%"
    embeddings = embedder.get_embedding(text)
    assert isinstance(embeddings, list)
    assert len(embeddings) > 0


def test_long_text(embedder):
    """Test that long text is handled correctly."""
    text = " ".join(["word"] * 500)
    embeddings = embedder.get_embedding(text)
    assert isinstance(embeddings, list)
    assert len(embeddings) > 0


def test_embedding_consistency(embedder):
    """Test that embeddings for the same text are consistent."""
    text = "Consistency test"
    embeddings1 = embedder.get_embedding(text)
    embeddings2 = embedder.get_embedding(text)

    assert len(embeddings1) == len(embeddings2)
    assert all(abs(a - b) < 1e-6 for a, b in zip(embeddings1, embeddings2))
