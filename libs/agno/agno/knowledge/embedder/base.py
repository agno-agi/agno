from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from agno.exceptions import EmbeddingError


def raise_embedding_error(error: Exception, model_id: Optional[str] = None, provider: Optional[str] = None) -> "None":
    """Re-raise a provider exception as an ``EmbeddingError``, preserving its status code."""
    if isinstance(error, EmbeddingError):
        raise error

    status_code = getattr(error, "status_code", None)
    if not isinstance(status_code, int):
        # Some SDKs expose the HTTP status on a nested response object instead
        status_code = getattr(getattr(error, "response", None), "status_code", None)
    if not isinstance(status_code, int):
        status_code = 502

    raise EmbeddingError(
        f"Failed to generate embedding: {error}",
        status_code=status_code,
        model_id=model_id,
        provider=provider,
    ) from error


@dataclass
class Embedder:
    """Base class for managing embedders"""

    dimensions: Optional[int] = 1536
    enable_batch: bool = False
    batch_size: int = 100  # Number of texts to process in each API call

    def get_embedding(self, text: str) -> List[float]:
        raise NotImplementedError

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError

    async def async_get_embedding(self, text: str) -> List[float]:
        raise NotImplementedError

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError
