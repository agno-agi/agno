from unittest.mock import MagicMock

import pytest


def test_openai_like_embedder_default_values():
    """Test that OpenAILikeEmbedder has sensible defaults for custom providers."""
    from agno.knowledge.embedder.openai_like import OpenAILikeEmbedder

    embedder = OpenAILikeEmbedder()
    assert embedder.id == "not-provided"
    assert embedder.api_key == "not-provided"
    # Default dimensions from Embedder base class
    assert embedder.dimensions == 1536


def test_openai_like_embedder_custom_params():
    """Test that OpenAILikeEmbedder accepts custom configuration."""
    from agno.knowledge.embedder.openai_like import OpenAILikeEmbedder

    embedder = OpenAILikeEmbedder(
        id="my-custom-model",
        api_key="my-api-key",
        base_url="http://localhost:8000/v1",
        dimensions=768,
    )
    assert embedder.id == "my-custom-model"
    assert embedder.api_key == "my-api-key"
    assert embedder.base_url == "http://localhost:8000/v1"
    assert embedder.dimensions == 768


def test_openai_like_embedder_does_not_override_dimensions():
    """Test that __post_init__ does not auto-set dimensions based on model id."""
    from agno.knowledge.embedder.openai_like import OpenAILikeEmbedder

    # Even with a model id that matches OpenAI patterns, dimensions should stay as user set
    embedder = OpenAILikeEmbedder(id="text-embedding-3-large", dimensions=512)
    assert embedder.dimensions == 512


def test_openai_like_embedder_creates_client_with_custom_base_url():
    """Test that the client is created with the custom base_url."""
    from agno.knowledge.embedder.openai_like import OpenAILikeEmbedder

    embedder = OpenAILikeEmbedder(
        id="my-model",
        api_key="test-key",
        base_url="http://localhost:11434/v1",
    )
    client = embedder.client
    assert str(client.base_url).rstrip("/") == "http://localhost:11434/v1"


def test_openai_like_embedder_creates_async_client_with_custom_base_url():
    """Test that the async client is created with the custom base_url."""
    from agno.knowledge.embedder.openai_like import OpenAILikeEmbedder

    embedder = OpenAILikeEmbedder(
        id="my-model",
        api_key="test-key",
        base_url="http://localhost:11434/v1",
    )
    aclient = embedder.aclient
    assert str(aclient.base_url).rstrip("/") == "http://localhost:11434/v1"


def test_openai_like_embedder_get_embedding():
    """Test that get_embedding calls the OpenAI client correctly."""
    from agno.knowledge.embedder.openai_like import OpenAILikeEmbedder

    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    mock_response.usage = MagicMock()
    mock_response.usage.model_dump.return_value = {"prompt_tokens": 5, "total_tokens": 5}

    mock_client = MagicMock()
    mock_client.embeddings.create.return_value = mock_response

    embedder = OpenAILikeEmbedder(
        id="my-model",
        api_key="test-key",
        base_url="http://localhost:8000/v1",
        dimensions=3,
        openai_client=mock_client,
    )

    result = embedder.get_embedding("test text")
    assert result == [0.1, 0.2, 0.3]
    mock_client.embeddings.create.assert_called_once()


def test_openai_like_embedder_get_embedding_and_usage():
    """Test that get_embedding_and_usage returns both embedding and usage."""
    from agno.knowledge.embedder.openai_like import OpenAILikeEmbedder

    mock_usage = MagicMock()
    mock_usage.model_dump.return_value = {"prompt_tokens": 5, "total_tokens": 5}

    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    mock_response.usage = mock_usage

    mock_client = MagicMock()
    mock_client.embeddings.create.return_value = mock_response

    embedder = OpenAILikeEmbedder(
        id="my-model",
        api_key="test-key",
        base_url="http://localhost:8000/v1",
        dimensions=3,
        openai_client=mock_client,
    )

    embedding, usage = embedder.get_embedding_and_usage("test text")
    assert embedding == [0.1, 0.2, 0.3]
    assert usage == {"prompt_tokens": 5, "total_tokens": 5}


@pytest.mark.asyncio
async def test_openai_like_embedder_async_get_embedding():
    """Test that async_get_embedding calls the async OpenAI client correctly."""
    from agno.knowledge.embedder.openai_like import OpenAILikeEmbedder

    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.4, 0.5, 0.6])]

    mock_aclient = MagicMock()
    # Make the mock awaitable

    async def mock_create(**kwargs):
        return mock_response

    mock_aclient.embeddings.create = mock_create

    embedder = OpenAILikeEmbedder(
        id="my-model",
        api_key="test-key",
        base_url="http://localhost:8000/v1",
        dimensions=3,
        async_client=mock_aclient,
    )

    result = await embedder.async_get_embedding("test text")
    assert result == [0.4, 0.5, 0.6]


@pytest.mark.asyncio
async def test_openai_like_embedder_async_get_embedding_and_usage():
    """Test that async_get_embedding_and_usage returns both embedding and usage."""
    from agno.knowledge.embedder.openai_like import OpenAILikeEmbedder

    mock_usage = MagicMock()
    mock_usage.model_dump.return_value = {"prompt_tokens": 5, "total_tokens": 5}

    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.4, 0.5, 0.6])]
    mock_response.usage = mock_usage

    mock_aclient = MagicMock()

    async def mock_create(**kwargs):
        return mock_response

    mock_aclient.embeddings.create = mock_create

    embedder = OpenAILikeEmbedder(
        id="my-model",
        api_key="test-key",
        base_url="http://localhost:8000/v1",
        dimensions=3,
        async_client=mock_aclient,
    )

    embedding, usage = await embedder.async_get_embedding_and_usage("test text")
    assert embedding == [0.4, 0.5, 0.6]
    assert usage == {"prompt_tokens": 5, "total_tokens": 5}


def test_openai_like_embedder_is_subclass_of_openai_embedder():
    """Test that OpenAILikeEmbedder properly inherits from OpenAIEmbedder."""
    from agno.knowledge.embedder.openai import OpenAIEmbedder
    from agno.knowledge.embedder.openai_like import OpenAILikeEmbedder

    assert issubclass(OpenAILikeEmbedder, OpenAIEmbedder)

    embedder = OpenAILikeEmbedder()
    assert isinstance(embedder, OpenAIEmbedder)
