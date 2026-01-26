from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="session")
def mock_embedder():
    """Create a mock embedder with appropriate return values."""
    mock = MagicMock()

    # Mock dimensions property
    mock.dimensions = 1024

    # Create a fixed embedding vector of the correct size
    mock_embedding: List[float] = [0.1] * 1024

    # Mock the get_embedding method (sync)
    mock.get_embedding.return_value = mock_embedding

    # Mock the get_embedding_and_usage method (sync)
    mock_usage: Dict[str, Any] = {"prompt_tokens": 10, "total_tokens": 10}
    mock.get_embedding_and_usage.return_value = (mock_embedding, mock_usage)

    # Mock the async_get_embedding method (async)
    async def async_get_embedding(text: str) -> List[float]:
        return mock_embedding

    mock.async_get_embedding = async_get_embedding

    # Mock the async_get_embedding_and_usage method (async)
    async def async_get_embedding_and_usage(text: str):
        return (mock_embedding, mock_usage)

    mock.async_get_embedding_and_usage = async_get_embedding_and_usage

    return mock
