from hashlib import md5
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock

import pytest


class DeterministicEmbedder:
    """A tiny embedder that needs no network or API key."""

    enable_batch = False

    def __init__(self, dimensions: int = 8):
        self.dimensions = dimensions

    def get_embedding(self, text: str) -> List[float]:
        # md5, not builtin hash(): PYTHONHASHSEED would embed the same text differently each run.
        vector = [0.0] * self.dimensions
        vector[int(md5(text.encode()).hexdigest(), 16) % self.dimensions] = 1.0
        return vector

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Dict[str, Any]]:
        return self.get_embedding(text), {"total_tokens": 1}

    async def async_get_embedding(self, text: str) -> List[float]:
        return self.get_embedding(text)

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Dict[str, Any]]:
        return self.get_embedding(text), {"total_tokens": 1}

    def embed(self, document, *args, **kwargs):
        document.embedding = self.get_embedding(document.content)
        document.usage = {"total_tokens": 1}
        return document

    async def async_embed(self, document, *args, **kwargs):
        return self.embed(document)


@pytest.fixture(scope="session")
def mock_embedder():
    """Create a mock embedder with appropriate return values."""
    mock = MagicMock()

    # Mock dimensions property
    mock.dimensions = 1024

    # Create a fixed embedding vector of the correct size
    mock_embedding: List[float] = [0.1] * 1024

    # Mock the get_embedding method
    mock.get_embedding.return_value = mock_embedding

    # Mock the get_embedding_and_usage method
    mock_usage: Dict[str, Any] = {"prompt_tokens": 10, "total_tokens": 10}
    mock.get_embedding_and_usage.return_value = (mock_embedding, mock_usage)

    return mock
