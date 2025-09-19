import pytest
from unittest.mock import MagicMock, patch

from agno.knowledge.embedder.mistral import MistralEmbedder


@pytest.fixture
def embedder():
    """Create a MistralEmbedder instance for testing"""
    return MistralEmbedder(api_key="test_key")


def test_embedder_initialization(embedder):
    """Test that the embedder initializes correctly"""
    assert embedder is not None
    assert embedder.id == "mistral-embed"
    assert embedder.dimensions == 1024
    assert embedder.api_key == "test_key"


def test_batch_methods_exist(embedder):
    """Test that batch embedding methods exist"""
    assert hasattr(embedder, 'get_embeddings_batch')
    assert hasattr(embedder, 'async_get_embeddings_batch')


@patch('agno.knowledge.embedder.mistral.Mistral')
def test_get_embeddings_batch_single_text(mock_mistral_class, embedder):
    """Test get_embeddings_batch with a single text"""
    # Mock the Mistral client and response
    mock_client = MagicMock()
    mock_mistral_class.return_value = mock_client

    # Mock the embeddings response
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    mock_client.embeddings.create.return_value = mock_response

    texts = ["Hello world"]
    embeddings = embedder.get_embeddings_batch(texts)

    assert len(embeddings) == 1
    assert embeddings[0] == [0.1, 0.2, 0.3]
    mock_client.embeddings.create.assert_called_once()
    call_args = mock_client.embeddings.create.call_args[1]
    assert call_args['inputs'] == texts
    assert call_args['model'] == "mistral-embed"


@patch('agno.knowledge.embedder.mistral.Mistral')
def test_get_embeddings_batch_multiple_texts(mock_mistral_class, embedder):
    """Test get_embeddings_batch with multiple texts"""
    # Mock the Mistral client and response
    mock_client = MagicMock()
    mock_mistral_class.return_value = mock_client

    # Mock the embeddings response for 3 texts
    mock_response = MagicMock()
    mock_response.data = [
        MagicMock(embedding=[0.1, 0.2, 0.3]),
        MagicMock(embedding=[0.4, 0.5, 0.6]),
        MagicMock(embedding=[0.7, 0.8, 0.9])
    ]
    mock_client.embeddings.create.return_value = mock_response

    texts = ["Text 1", "Text 2", "Text 3"]
    embeddings = embedder.get_embeddings_batch(texts)

    assert len(embeddings) == 3
    assert embeddings[0] == [0.1, 0.2, 0.3]
    assert embeddings[1] == [0.4, 0.5, 0.6]
    assert embeddings[2] == [0.7, 0.8, 0.9]
    mock_client.embeddings.create.assert_called_once()
    call_args = mock_client.embeddings.create.call_args[1]
    assert call_args['inputs'] == texts


@patch('agno.knowledge.embedder.mistral.Mistral')
def test_get_embeddings_batch_with_batching(mock_mistral_class, embedder):
    """Test get_embeddings_batch with batch_size parameter"""
    # Mock the Mistral client and response
    mock_client = MagicMock()
    mock_mistral_class.return_value = mock_client

    # Mock responses for two batches
    mock_response1 = MagicMock()
    mock_response1.data = [
        MagicMock(embedding=[0.1, 0.2]),
        MagicMock(embedding=[0.3, 0.4])
    ]
    mock_response2 = MagicMock()
    mock_response2.data = [
        MagicMock(embedding=[0.5, 0.6])
    ]

    mock_client.embeddings.create.side_effect = [mock_response1, mock_response2]

    texts = ["Text 1", "Text 2", "Text 3"]
    embeddings = embedder.get_embeddings_batch(texts, batch_size=2)

    assert len(embeddings) == 3
    assert embeddings[0] == [0.1, 0.2]
    assert embeddings[1] == [0.3, 0.4]
    assert embeddings[2] == [0.5, 0.6]

    # Should be called twice (once for batch of 2, once for batch of 1)
    assert mock_client.embeddings.create.call_count == 2


@patch('agno.knowledge.embedder.mistral.Mistral')
def test_get_embeddings_batch_error_handling(mock_mistral_class, embedder):
    """Test get_embeddings_batch error handling and fallback"""
    # Mock the Mistral client to raise an exception on batch call, succeed on individual calls
    mock_client = MagicMock()
    mock_mistral_class.return_value = mock_client

    # Batch call fails, individual call succeeds
    mock_client.embeddings.create.side_effect = [
        Exception("Batch API Error"),  # Batch call fails
        MagicMock(data=[MagicMock(embedding=[0.1, 0.2])]),  # Individual call succeeds
    ]

    texts = ["Text 1"]
    embeddings = embedder.get_embeddings_batch(texts)

    # Should fall back to individual calls and get successful embedding
    assert len(embeddings) == 1
    assert embeddings[0] == [0.1, 0.2]  # Individual call succeeded


@patch('agno.knowledge.embedder.mistral.Mistral')
def test_get_embeddings_batch_with_request_params(mock_mistral_class, embedder):
    """Test get_embeddings_batch respects request_params"""
    # Mock the Mistral client
    mock_client = MagicMock()
    mock_mistral_class.return_value = mock_client

    # Set request params on embedder
    embedder.request_params = {"custom_param": "value"}

    # Mock response
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2])]
    mock_client.embeddings.create.return_value = mock_response

    texts = ["Hello world"]
    embeddings = embedder.get_embeddings_batch(texts)

    # Check that custom params were included
    call_args = mock_client.embeddings.create.call_args[1]
    assert call_args['custom_param'] == "value"
    assert call_args['inputs'] == texts
    assert call_args['model'] == "mistral-embed"


@pytest.mark.asyncio
@patch('agno.knowledge.embedder.mistral.Mistral')
async def test_async_get_embeddings_batch(mock_mistral_class, embedder):
    """Test async_get_embeddings_batch with multiple texts"""
    # Mock the Mistral client
    mock_client = MagicMock()
    mock_mistral_class.return_value = mock_client

    # Mock async response
    mock_response = MagicMock()
    mock_response.data = [
        MagicMock(embedding=[0.1, 0.2]),
        MagicMock(embedding=[0.3, 0.4])
    ]

    # Create an async mock for create_async
    async def mock_create_async(**kwargs):
        return mock_response

    mock_client.embeddings.create_async = mock_create_async

    texts = ["Text 1", "Text 2"]
    embeddings = await embedder.async_get_embeddings_batch(texts)

    assert len(embeddings) == 2
    assert embeddings[0] == [0.1, 0.2]
    assert embeddings[1] == [0.3, 0.4]


@pytest.mark.asyncio
@patch('agno.knowledge.embedder.mistral.Mistral')
async def test_async_get_embeddings_batch_fallback(mock_mistral_class, embedder):
    """Test async_get_embeddings_batch falls back to sync method when async not available"""
    # Mock the Mistral client without async method
    mock_client = MagicMock()
    mock_mistral_class.return_value = mock_client
    del mock_client.embeddings.create_async  # Remove async method

    # Mock sync response
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2])]
    mock_client.embeddings.create.return_value = mock_response

    texts = ["Text 1"]
    embeddings = await embedder.async_get_embeddings_batch(texts)

    assert len(embeddings) == 1
    assert embeddings[0] == [0.1, 0.2]
