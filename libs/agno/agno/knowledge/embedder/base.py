from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


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

    def get_embeddings_batch_and_usage(self, texts: List[str]) -> Tuple[List[List[float]], List[Optional[Dict]]]:
        """
        Get embeddings and usage for multiple texts in batches (sync version).

        Default implementation falls back to individual calls.
        Subclasses should override for native batch support.

        Args:
            texts: List of text strings to embed

        Returns:
            Tuple of (List of embedding vectors, List of usage dictionaries)
        """
        all_embeddings: List[List[float]] = []
        all_usage: List[Optional[Dict]] = []
        for text in texts:
            embedding, usage = self.get_embedding_and_usage(text)
            all_embeddings.append(embedding)
            all_usage.append(usage)
        return all_embeddings, all_usage

    async def async_get_embedding(self, text: str) -> List[float]:
        raise NotImplementedError

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError
