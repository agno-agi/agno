import pytest

from agno.knowledge.embedder.huggingface import HuggingfaceCustomEmbedder


@pytest.fixture
def embedder():
    return HuggingfaceCustomEmbedder()


def test_embedder_initialization(embedder):
    """Test that the embedder initializes correctly"""
    assert embedder is not None
    assert embedder.id == "intfloat/multilingual-e5-large"
    assert embedder.api_key is not None, "HUGGINGFACE_API_KEY env variable is not set"


def test_get_embedding(embedder):
    """Test that we can get embeddings for a simple text"""
    text = "The quick brown fox jumps over the lazy dog."
    embeddings = embedder.get_embedding(text)

    # Basic checks on the embeddings
    assert isinstance(embeddings, list)
    assert len(embeddings) > 0
    assert all(isinstance(x, float) for x in embeddings)


def test_special_characters(embedder):
    """Test that special characters are handled correctly"""
    text = "Hello, world! こんにちは 123 @#$%"
    embeddings = embedder.get_embedding(text)
    assert isinstance(embeddings, list)
    assert len(embeddings) > 0


def test_long_text(embedder):
    """Test that long text is handled correctly"""
    text = " ".join(["word"] * 1000)  # Create a long text
    embeddings = embedder.get_embedding(text)
    assert isinstance(embeddings, list)
    assert len(embeddings) > 0


def test_embedding_consistency(embedder):
    """Test that embeddings for the same text are consistent"""
    text = "Consistency test"
    embeddings1 = embedder.get_embedding(text)
    embeddings2 = embedder.get_embedding(text)

    assert len(embeddings1) == len(embeddings2)
    assert all(abs(a - b) < 1e-6 for a, b in zip(embeddings1, embeddings2))
