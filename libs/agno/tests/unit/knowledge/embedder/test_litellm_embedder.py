from unittest.mock import AsyncMock, Mock, patch

import pytest

from agno.knowledge.embedder.litellm import LiteLLMEmbedder


@patch('agno.knowledge.embedder.litellm.litellm')
def test_embedder_initialization(mock_litellm):
    """Test that the embedder initializes correctly"""
    embedder = LiteLLMEmbedder(id="openai/text-embedding-3-small")
    assert embedder is not None
    assert embedder.id == "openai/text-embedding-3-small"
    assert embedder.batch_size == 100
    assert not embedder.enable_batch


@patch('agno.knowledge.embedder.litellm.litellm')
def test_get_embedding(mock_litellm):
    """Test that we can get embeddings for a simple text"""
    mock_response = Mock()
    mock_data_item = Mock()
    mock_data_item.embedding = [0.1, 0.2, 0.3]
    mock_response.data = [mock_data_item]
    
    mock_usage = Mock()
    mock_usage.model_dump.return_value = {
        "prompt_tokens": 3,
        "completion_tokens": 0,
        "total_tokens": 3
    }
    mock_response.usage = mock_usage
    
    mock_litellm.embedding.return_value = mock_response
    
    embedder = LiteLLMEmbedder(id="openai/text-embedding-3-small")
    emb = embedder.get_embedding("hello world")
    assert emb == [0.1, 0.2, 0.3]


@patch('agno.knowledge.embedder.litellm.litellm')
def test_get_embedding_and_usage(mock_litellm):
    """Test that we can get embeddings with usage information"""
    mock_response = Mock()
    mock_data_item = Mock()
    mock_data_item.embedding = [0.1, 0.2, 0.3]
    mock_response.data = [mock_data_item]
    
    mock_usage = Mock()
    mock_usage.model_dump.return_value = {
        "prompt_tokens": 3,
        "completion_tokens": 0,
        "total_tokens": 3
    }
    mock_response.usage = mock_usage
    
    mock_litellm.embedding.return_value = mock_response
    
    embedder = LiteLLMEmbedder(id="openai/text-embedding-3-small")
    emb, usage = embedder.get_embedding_and_usage("hello world")
    assert emb == [0.1, 0.2, 0.3]
    assert usage and usage["prompt_tokens"] == 3


@patch('agno.knowledge.embedder.litellm.litellm')
@pytest.mark.asyncio
async def test_async_get_embedding(mock_litellm):
    """Test async embedding functionality"""
    mock_response = Mock()
    mock_data_item = Mock()
    mock_data_item.embedding = [0.1, 0.2, 0.3]
    mock_response.data = [mock_data_item]
    
    mock_usage = Mock()
    mock_usage.model_dump.return_value = {
        "prompt_tokens": 3,
        "completion_tokens": 0,
        "total_tokens": 3
    }
    mock_response.usage = mock_usage
    
    mock_litellm.aembedding = AsyncMock(return_value=mock_response)
    
    embedder = LiteLLMEmbedder(id="openai/text-embedding-3-small")
    emb = await embedder.async_get_embedding("async test")
    assert emb == [0.1, 0.2, 0.3]


@patch('agno.knowledge.embedder.litellm.litellm')
@pytest.mark.asyncio
async def test_async_get_embedding_and_usage(mock_litellm):
    """Test async embedding with usage"""
    mock_response = Mock()
    mock_data_item = Mock()
    mock_data_item.embedding = [0.1, 0.2, 0.3]
    mock_response.data = [mock_data_item]
    
    mock_usage = Mock()
    mock_usage.model_dump.return_value = {
        "prompt_tokens": 3,
        "completion_tokens": 0,
        "total_tokens": 3
    }
    mock_response.usage = mock_usage
    
    mock_litellm.aembedding = AsyncMock(return_value=mock_response)
    
    embedder = LiteLLMEmbedder(id="openai/text-embedding-3-small")
    emb, usage = await embedder.async_get_embedding_and_usage("async test")
    assert emb == [0.1, 0.2, 0.3]
    assert usage and usage["total_tokens"] == 3


@patch('agno.knowledge.embedder.litellm.litellm')
@pytest.mark.asyncio
async def test_async_batch_embeddings(mock_litellm):
    """Test async batch embedding functionality"""
    mock_response = Mock()
    mock_data_item1 = Mock()
    mock_data_item1.embedding = [0.1, 0.2, 0.3]
    mock_data_item2 = Mock()
    mock_data_item2.embedding = [0.1, 0.2, 0.3]
    mock_response.data = [mock_data_item1, mock_data_item2]
    
    mock_usage = Mock()
    mock_usage.model_dump.return_value = {
        "prompt_tokens": 6,
        "completion_tokens": 0,
        "total_tokens": 6
    }
    mock_response.usage = mock_usage
    
    mock_litellm.aembedding = AsyncMock(return_value=mock_response)
    
    embedder = LiteLLMEmbedder(id="openai/text-embedding-3-small")
    texts = ["First text", "Second text"]
    embeddings, usages = await embedder.async_get_embeddings_batch_and_usage(texts)

    assert isinstance(embeddings, list)
    assert len(embeddings) == len(texts)
    assert all(emb == [0.1, 0.2, 0.3] for emb in embeddings)

    assert isinstance(usages, list)
    assert len(usages) == len(texts)
    assert all(usage and usage["total_tokens"] == 6 for usage in usages)


@patch('agno.knowledge.embedder.litellm.litellm')
def test_build_request(mock_litellm):
    """Test request building functionality"""
    embedder = LiteLLMEmbedder(id="openai/text-embedding-3-small")
    texts = ["Hello world", "Test text"]
    request = embedder._build_request(texts)

    assert isinstance(request, dict)
    assert request["model"] == "openai/text-embedding-3-small"
    assert request["input"] == texts


@patch('agno.knowledge.embedder.litellm.litellm')
def test_build_request_with_params(mock_litellm):
    """Test request building with additional parameters"""
    embedder = LiteLLMEmbedder(
        id="openai/text-embedding-3-small",
        api_key="test-key",
        api_base="https://custom.api.com",
        request_params={"encoding_format": "float"}
    )
    
    texts = ["Test"]
    request = embedder._build_request(texts)
    
    assert request["model"] == "openai/text-embedding-3-small"
    assert request["input"] == texts
    assert request["api_key"] == "test-key"
    assert request["api_base"] == "https://custom.api.com"
    assert request["encoding_format"] == "float"
