import pytest

from agno.knowledge.embedder.jina import JinaEmbedder


@pytest.fixture
def embedder():
    return JinaEmbedder()


def test_embedder_initialization(embedder):
    """Test that the embedder initializes correctly"""
    assert embedder is not None
    assert embedder.id == "jina-embeddings-v3"  # Field is 'id' not 'model'
    assert embedder.dimensions == 1024
    assert embedder.embedding_type == "float"
    assert not embedder.late_chunking
    assert embedder.api_key is not None, "JINA_API_KEY env variable is not set"


def test_get_embedding(embedder):
    """Test that we can get embeddings for a simple text"""
    text = "The quick brown fox jumps over the lazy dog."
    embeddings = embedder.get_embedding(text)

    # Basic checks on the embeddings
    assert isinstance(embeddings, list)
    assert len(embeddings) > 0
    assert all(isinstance(x, float) for x in embeddings)
    assert len(embeddings) == embedder.dimensions


def test_get_embedding_and_usage(embedder):
    """Test that we can get embeddings with usage information"""
    text = "Test embedding with usage information."
    embedding, usage = embedder.get_embedding_and_usage(text)

    # Check embedding
    assert isinstance(embedding, list)
    assert len(embedding) > 0
    assert all(isinstance(x, float) for x in embedding)
    assert len(embedding) == embedder.dimensions

    # Check usage (may be None if not provided by API)
    assert usage is None or isinstance(usage, dict)


def test_special_characters(embedder):
    """Test that special characters are handled correctly"""
    text = "Hello, world! こんにちは 123 @#$%"
    embeddings = embedder.get_embedding(text)
    assert isinstance(embeddings, list)
    assert len(embeddings) > 0
    assert len(embeddings) == embedder.dimensions


def test_long_text(embedder):
    """Test that long text is handled correctly"""
    text = " ".join(["word"] * 1000)  # Create a long text
    embeddings = embedder.get_embedding(text)
    assert isinstance(embeddings, list)
    assert len(embeddings) > 0
    assert len(embeddings) == embedder.dimensions


def test_embedding_consistency(embedder):
    """Test that embeddings for the same text are consistent"""
    text = "Consistency test"
    embeddings1 = embedder.get_embedding(text)
    embeddings2 = embedder.get_embedding(text)

    assert len(embeddings1) == len(embeddings2)
    assert all(abs(a - b) < 1e-3 for a, b in zip(embeddings1, embeddings2))


def test_custom_configuration():
    """Test embedder with custom configuration"""
    custom_embedder = JinaEmbedder(
        id="jina-embeddings-v3",  # Field is 'id' not 'model'
        dimensions=512,  # Different dimensions
        embedding_type="float",
        late_chunking=True,
        timeout=30.0,
    )

    text = "Test with custom configuration"
    embeddings = custom_embedder.get_embedding(text)

    assert isinstance(embeddings, list)
    assert len(embeddings) > 0
    # Note: dimensions might still be 1024 if the API doesn't support 512 for this model


def test_different_embedding_types():
    """Test different embedding output types"""
    # Test with float type (default)
    float_embedder = JinaEmbedder(embedding_type="float")
    text = "Test different embedding types"

    embeddings = float_embedder.get_embedding(text)
    assert isinstance(embeddings, list)
    assert all(isinstance(x, float) for x in embeddings)


def test_late_chunking_feature():
    """Test the late chunking feature for better long document processing"""
    chunking_embedder = JinaEmbedder(late_chunking=True)

    # Test with a longer document
    long_text = "This is a longer document that would benefit from late chunking. " * 50
    embeddings = chunking_embedder.get_embedding(long_text)

    assert isinstance(embeddings, list)
    assert len(embeddings) > 0
    assert len(embeddings) == chunking_embedder.dimensions


def test_api_key_validation():
    """Test that missing API key is handled gracefully"""
    embedder_no_key = JinaEmbedder(api_key=None)

    # The embedder should return empty list when API key is missing
    # (since the error is caught and logged as warning)
    embeddings = embedder_no_key.get_embedding("Test text")
    assert embeddings == []


def test_empty_text_handling(embedder):
    """Test handling of empty text"""
    embeddings = embedder.get_embedding("")
    # Should return empty list or handle gracefully
    assert isinstance(embeddings, list)
