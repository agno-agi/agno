from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class Embedder:
    """Base class for managing embedders"""

    dimensions: Optional[int] = 1536

    def get_embedding(self, text: str) -> List[float]:
        raise NotImplementedError

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError

    def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        return [self.get_embedding(text) for text in texts]
