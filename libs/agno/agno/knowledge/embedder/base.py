from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple, Union

if TYPE_CHECKING:
    from agno.media import Audio, Image, Video

EmbeddingInput = Union[str, "Image", "Audio", "Video"]
ContentInput = Union[EmbeddingInput, Sequence[EmbeddingInput]]


@dataclass
class Embedder:
    """Base class for managing embedders"""

    dimensions: Optional[int] = 1536
    enable_batch: bool = False
    batch_size: int = 100  # Number of texts to process in each API call

    def get_embedding(self, content: ContentInput) -> List[float]:
        raise NotImplementedError

    def get_embedding_and_usage(self, content: ContentInput) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError

    async def async_get_embedding(self, content: ContentInput) -> List[float]:
        raise NotImplementedError

    async def async_get_embedding_and_usage(self, content: ContentInput) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError
