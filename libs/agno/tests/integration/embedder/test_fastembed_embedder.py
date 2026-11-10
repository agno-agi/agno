import pytest

pytest.importorskip("fastembed")

from agno.knowledge.embedder.fastembed import FastEmbedEmbedder


@pytest.fixture
def embedder():
    return FastEmbedEmbedder()


def test_embedder_initialization(embedder):
    assert embedder.id == "BAAI/bge-small-en-v1.5"
    assert embedder.fastembed_client is None  # Lazy init, not created yet


def test_get_embedding(embedder):
    text = "The quick brown fox jumps over the lazy dog."
    embeddings = embedder.get_embedding(text)

    assert isinstance(embeddings, list)
    assert len(embeddings) > 0
    assert all(isinstance(x, float) for x in embeddings)


def test_embedding_consistency(embedder):
    text = "Consistency test"
    embeddings1 = embedder.get_embedding(text)
    embeddings2 = embedder.get_embedding(text)

    assert len(embeddings1) == len(embeddings2)
    assert all(abs(a - b) < 1e-6 for a, b in zip(embeddings1, embeddings2))


def test_client_cached_after_first_use(embedder):
    assert embedder.fastembed_client is None
    embedder.get_embedding("trigger init")
    assert embedder.fastembed_client is not None

    # Second call should reuse the same client
    client_ref = embedder.fastembed_client
    embedder.get_embedding("second call")
    assert embedder.fastembed_client is client_ref
