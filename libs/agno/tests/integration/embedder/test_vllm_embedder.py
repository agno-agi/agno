from unittest.mock import AsyncMock, Mock, patch

import pytest

from agno.knowledge.embedder.vllm import VLLMEmbedder


# Fixtures for remote mode tests
@pytest.fixture
def remote_embedder():
    """Create a VLLMEmbedder in remote mode."""
    return VLLMEmbedder(base_url="http://localhost:8000/v1", api_key="test-key")


@pytest.fixture
def mock_openai_response():
    """Create a mock OpenAI-compatible response."""
    response = Mock()
    response.data = [Mock(embedding=[0.1] * 4096)]
    response.usage = Mock(prompt_tokens=10, total_tokens=10)
    response.usage.model_dump.return_value = {"prompt_tokens": 10, "total_tokens": 10}
    return response


@pytest.fixture
def mock_openai_batch_response():
    """Create a mock OpenAI-compatible batch response."""
    response = Mock()
    response.data = [Mock(embedding=[0.1] * 4096), Mock(embedding=[0.2] * 4096), Mock(embedding=[0.3] * 4096)]
    response.usage = Mock(prompt_tokens=30, total_tokens=30)
    response.usage.model_dump.return_value = {"prompt_tokens": 30, "total_tokens": 30}
    return response


# ============================================================================
# Remote Mode Tests
# ============================================================================


@patch("agno.knowledge.embedder.vllm.OpenAIClient")
def test_embedder_initialization_remote(mock_client_class):
    """Test that the embedder initializes correctly in remote mode."""
    embedder = VLLMEmbedder(base_url="http://localhost:8000/v1", api_key="test-key")

    assert embedder is not None
    assert embedder.id == "intfloat/e5-mistral-7b-instruct"
    assert embedder.dimensions == 4096
    assert embedder.base_url == "http://localhost:8000/v1"
    assert embedder.api_key == "test-key"
    assert embedder.is_remote is True


@patch("agno.knowledge.embedder.vllm.OpenAIClient")
def test_get_embedding_remote(mock_client_class, mock_openai_response):
    """Test that we can get embeddings for a simple text in remote mode."""
    mock_client = Mock()
    mock_client.embeddings.create.return_value = mock_openai_response
    mock_client_class.return_value = mock_client

    embedder = VLLMEmbedder(base_url="http://localhost:8000/v1")
    text = "The quick brown fox jumps over the lazy dog."
    embeddings = embedder.get_embedding(text)

    # Basic checks on the embeddings
    assert isinstance(embeddings, list)
    assert len(embeddings) > 0
    assert all(isinstance(x, float) for x in embeddings)
    assert len(embeddings) == embedder.dimensions

    # Verify the API was called correctly
    mock_client.embeddings.create.assert_called_once()
    call_args = mock_client.embeddings.create.call_args[1]
    assert call_args["input"] == text
    assert call_args["model"] == embedder.id


@patch("agno.knowledge.embedder.vllm.OpenAIClient")
def test_get_embedding_and_usage_remote(mock_client_class, mock_openai_response):
    """Test that we can get embeddings with usage information in remote mode."""
    mock_client = Mock()
    mock_client.embeddings.create.return_value = mock_openai_response
    mock_client_class.return_value = mock_client

    embedder = VLLMEmbedder(base_url="http://localhost:8000/v1")
    text = "Test embedding with usage information."
    embedding, usage = embedder.get_embedding_and_usage(text)

    # Check embedding
    assert isinstance(embedding, list)
    assert len(embedding) > 0
    assert all(isinstance(x, float) for x in embedding)
    assert len(embedding) == embedder.dimensions

    # Check usage
    assert usage is not None
    assert isinstance(usage, dict)
    assert "prompt_tokens" in usage
    assert "total_tokens" in usage
    assert usage["prompt_tokens"] == 10
    assert usage["total_tokens"] == 10


@pytest.mark.asyncio
@patch("agno.knowledge.embedder.vllm.AsyncOpenAI")
async def test_async_get_embedding_remote(mock_async_client_class, mock_openai_response):
    """Test async embedding generation in remote mode."""
    mock_client = Mock()
    mock_client.embeddings.create = AsyncMock(return_value=mock_openai_response)
    mock_async_client_class.return_value = mock_client

    embedder = VLLMEmbedder(base_url="http://localhost:8000/v1")
    text = "Async embedding test."
    embeddings = await embedder.async_get_embedding(text)

    # Basic checks on the embeddings
    assert isinstance(embeddings, list)
    assert len(embeddings) > 0
    assert all(isinstance(x, float) for x in embeddings)
    assert len(embeddings) == embedder.dimensions


@pytest.mark.asyncio
@patch("agno.knowledge.embedder.vllm.AsyncOpenAI")
async def test_async_get_embedding_and_usage_remote(mock_async_client_class, mock_openai_response):
    """Test async embedding with usage in remote mode."""
    mock_client = Mock()
    mock_client.embeddings.create = AsyncMock(return_value=mock_openai_response)
    mock_async_client_class.return_value = mock_client

    embedder = VLLMEmbedder(base_url="http://localhost:8000/v1")
    text = "Async embedding with usage test."
    embedding, usage = await embedder.async_get_embedding_and_usage(text)

    # Check embedding
    assert isinstance(embedding, list)
    assert len(embedding) > 0
    assert all(isinstance(x, float) for x in embedding)
    assert len(embedding) == embedder.dimensions

    # Check usage
    assert usage is not None
    assert isinstance(usage, dict)
    assert "prompt_tokens" in usage
    assert "total_tokens" in usage


@pytest.mark.asyncio
@patch("agno.knowledge.embedder.vllm.AsyncOpenAI")
async def test_async_batch_embeddings_remote(mock_async_client_class, mock_openai_batch_response):
    """Test async batch embedding processing in remote mode."""
    mock_client = Mock()
    mock_client.embeddings.create = AsyncMock(return_value=mock_openai_batch_response)
    mock_async_client_class.return_value = mock_client

    embedder = VLLMEmbedder(base_url="http://localhost:8000/v1")
    texts = ["Text one", "Text two", "Text three"]
    embeddings, usages = await embedder.async_get_embeddings_batch_and_usage(texts)

    # Check embeddings
    assert isinstance(embeddings, list)
    assert len(embeddings) == 3
    for embedding in embeddings:
        assert isinstance(embedding, list)
        assert len(embedding) == embedder.dimensions
        assert all(isinstance(x, float) for x in embedding)

    # Check usages
    assert isinstance(usages, list)
    assert len(usages) == 3
    for usage in usages:
        assert usage is not None
        assert isinstance(usage, dict)
        assert "prompt_tokens" in usage
        assert "total_tokens" in usage


@patch("agno.knowledge.embedder.vllm.OpenAIClient")
def test_special_characters_remote(mock_client_class, mock_openai_response):
    """Test that special characters are handled correctly in remote mode."""
    mock_client = Mock()
    mock_client.embeddings.create.return_value = mock_openai_response
    mock_client_class.return_value = mock_client

    embedder = VLLMEmbedder(base_url="http://localhost:8000/v1")
    text = "Hello, world! こんにちは 123 @#$%"
    embeddings = embedder.get_embedding(text)

    assert isinstance(embeddings, list)
    assert len(embeddings) > 0
    assert len(embeddings) == embedder.dimensions


@patch("agno.knowledge.embedder.vllm.OpenAIClient")
def test_long_text_remote(mock_client_class, mock_openai_response):
    """Test that long text is handled correctly in remote mode."""
    mock_client = Mock()
    mock_client.embeddings.create.return_value = mock_openai_response
    mock_client_class.return_value = mock_client

    embedder = VLLMEmbedder(base_url="http://localhost:8000/v1")
    text = " ".join(["word"] * 1000)  # Create a long text
    embeddings = embedder.get_embedding(text)

    assert isinstance(embeddings, list)
    assert len(embeddings) > 0
    assert len(embeddings) == embedder.dimensions


@patch("agno.knowledge.embedder.vllm.OpenAIClient")
def test_embedding_consistency_remote(mock_client_class, mock_openai_response):
    """Test that embeddings for the same text are consistent in remote mode."""
    mock_client = Mock()
    mock_client.embeddings.create.return_value = mock_openai_response
    mock_client_class.return_value = mock_client

    embedder = VLLMEmbedder(base_url="http://localhost:8000/v1")
    text = "Consistency test"
    embeddings1 = embedder.get_embedding(text)
    embeddings2 = embedder.get_embedding(text)

    assert len(embeddings1) == len(embeddings2)
    # Since we're using mocks, they should be identical
    assert embeddings1 == embeddings2


@patch("agno.knowledge.embedder.vllm.OpenAIClient")
def test_empty_text_handling_remote(mock_client_class, mock_openai_response):
    """Test handling of empty text in remote mode."""
    mock_client = Mock()
    mock_client.embeddings.create.return_value = mock_openai_response
    mock_client_class.return_value = mock_client

    embedder = VLLMEmbedder(base_url="http://localhost:8000/v1")
    embeddings = embedder.get_embedding("")

    # Should return list (mock will provide embeddings)
    assert isinstance(embeddings, list)


@patch("agno.knowledge.embedder.vllm.OpenAIClient")
def test_custom_configuration_remote(mock_client_class, mock_openai_response):
    """Test embedder with custom configuration in remote mode."""
    # Create custom mock response with different dimensions
    custom_response = Mock()
    custom_response.data = [Mock(embedding=[0.1] * 512)]
    custom_response.usage = Mock(prompt_tokens=5, total_tokens=5)
    custom_response.usage.model_dump.return_value = {"prompt_tokens": 5, "total_tokens": 5}

    mock_client = Mock()
    mock_client.embeddings.create.return_value = custom_response
    mock_client_class.return_value = mock_client

    custom_embedder = VLLMEmbedder(
        id="custom-model",
        dimensions=512,
        base_url="http://localhost:8000/v1",
        api_key="custom-key",
        request_params={"extra_param": "value"},
    )

    text = "Test with custom configuration"
    embeddings = custom_embedder.get_embedding(text)

    assert isinstance(embeddings, list)
    assert len(embeddings) == 512  # Custom dimensions

    # Verify custom parameters were used
    call_args = mock_client.embeddings.create.call_args[1]
    assert call_args["model"] == "custom-model"
    assert call_args.get("extra_param") == "value"


# ============================================================================
# Local Mode Tests (Skipped - Require vLLM and GPU)
# ============================================================================
# To run these tests locally:
# 1. Install vLLM: pip install vllm
# 2. Ensure you have a GPU with sufficient VRAM
# 3. Run with: pytest libs/agno/tests/integration/embedder/test_vllm_embedder.py -v -m "local_vllm"
# Or to run ALL tests including local: pytest ... --run-local-vllm


@pytest.mark.local_vllm
@pytest.mark.skip(reason="Requires local vLLM installation and GPU resources")
def test_embedder_initialization_local():
    """Test that the embedder initializes correctly in local mode."""
    embedder = VLLMEmbedder()  # No base_url = local mode

    assert embedder is not None
    assert embedder.id == "intfloat/e5-mistral-7b-instruct"
    assert embedder.dimensions == 4096
    assert embedder.base_url is None
    assert embedder.is_remote is False


@pytest.mark.local_vllm
@pytest.mark.skip(reason="Requires local vLLM installation and GPU resources")
def test_get_embedding_local():
    """Test that we can get embeddings in local mode."""
    embedder = VLLMEmbedder()
    text = "The quick brown fox jumps over the lazy dog."
    embeddings = embedder.get_embedding(text)

    assert isinstance(embeddings, list)
    assert len(embeddings) > 0
    assert all(isinstance(x, float) for x in embeddings)
    assert len(embeddings) == embedder.dimensions


@pytest.mark.local_vllm
@pytest.mark.skip(reason="Requires local vLLM installation and GPU resources")
def test_local_mode_no_usage():
    """Test that local mode doesn't provide usage metrics."""
    embedder = VLLMEmbedder()
    text = "Test text for local mode."
    embedding, usage = embedder.get_embedding_and_usage(text)

    assert isinstance(embedding, list)
    assert len(embedding) > 0
    # Local mode should return None for usage
    assert usage is None


# ============================================================================
# Error Handling Tests
# ============================================================================


@patch("agno.knowledge.embedder.vllm.OpenAIClient")
def test_invalid_base_url(mock_client_class):
    """Test handling of invalid base URL."""
    mock_client = Mock()
    mock_client.embeddings.create.side_effect = Exception("Connection refused")
    mock_client_class.return_value = mock_client

    embedder = VLLMEmbedder(base_url="http://invalid-url:9999/v1")
    embeddings = embedder.get_embedding("Test text")

    # Should return empty list on error
    assert embeddings == []


@patch("agno.knowledge.embedder.vllm.OpenAIClient")
def test_network_error_handling(mock_client_class):
    """Test handling of network errors."""
    mock_client = Mock()
    mock_client.embeddings.create.side_effect = Exception("Network timeout")
    mock_client_class.return_value = mock_client

    embedder = VLLMEmbedder(base_url="http://localhost:8000/v1")
    embeddings = embedder.get_embedding("Test text")

    # Should return empty list on error
    assert embeddings == []


@patch("agno.knowledge.embedder.vllm.OpenAIClient")
def test_invalid_model_id(mock_client_class):
    """Test handling of invalid model ID."""
    mock_client = Mock()
    mock_client.embeddings.create.side_effect = Exception("Model not found")
    mock_client_class.return_value = mock_client

    embedder = VLLMEmbedder(id="invalid-model-id", base_url="http://localhost:8000/v1")
    embeddings = embedder.get_embedding("Test text")

    # Should return empty list on error
    assert embeddings == []


@pytest.mark.asyncio
@patch("agno.knowledge.embedder.vllm.AsyncOpenAI")
async def test_batch_partial_failure(mock_async_client_class):
    """Test batch processing with partial failures."""
    # First call succeeds, second call fails
    success_response = Mock()
    success_response.data = [Mock(embedding=[0.1] * 4096), Mock(embedding=[0.2] * 4096)]
    success_response.usage = Mock(prompt_tokens=20, total_tokens=20)
    success_response.usage.model_dump.return_value = {"prompt_tokens": 20, "total_tokens": 20}

    mock_client = Mock()
    mock_client.embeddings.create = AsyncMock(side_effect=[success_response, Exception("Batch failed")])
    mock_async_client_class.return_value = mock_client

    embedder = VLLMEmbedder(base_url="http://localhost:8000/v1", batch_size=2)
    texts = ["Text 1", "Text 2", "Text 3", "Text 4"]  # Two batches
    embeddings, usages = await embedder.async_get_embeddings_batch_and_usage(texts)

    # Should have 4 results total (2 successful, 2 empty from failed batch)
    assert len(embeddings) == 4
    assert len(usages) == 4

    # First two should be valid
    assert len(embeddings[0]) == 4096
    assert len(embeddings[1]) == 4096

    # Last two should be empty due to failure
    assert embeddings[2] == []
    assert embeddings[3] == []


# ============================================================================
# Property and Mode Detection Tests
# ============================================================================


def test_is_remote_property():
    """Test that is_remote property correctly detects remote mode."""
    # Remote mode
    remote_embedder = VLLMEmbedder(base_url="http://localhost:8000/v1")
    assert remote_embedder.is_remote is True

    # Local mode
    local_embedder = VLLMEmbedder()
    assert local_embedder.is_remote is False


def test_mode_detection():
    """Test that mode is correctly selected based on configuration."""
    # Remote mode with base_url
    embedder1 = VLLMEmbedder(base_url="http://localhost:8000/v1")
    assert embedder1.is_remote is True
    assert embedder1.base_url == "http://localhost:8000/v1"

    # Remote mode with base_url and API key
    embedder2 = VLLMEmbedder(base_url="http://localhost:8000/v1", api_key="test-key")
    assert embedder2.is_remote is True
    assert embedder2.api_key == "test-key"

    # Local mode without base_url
    embedder3 = VLLMEmbedder()
    assert embedder3.is_remote is False
    assert embedder3.base_url is None

    # Local mode with custom model
    embedder4 = VLLMEmbedder(id="custom-local-model")
    assert embedder4.is_remote is False
    assert embedder4.id == "custom-local-model"
