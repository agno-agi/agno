from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple, Union

if TYPE_CHECKING:
    from agno.media import Audio, Image, Video

EmbeddingInput = Union[str, "Image", "Audio", "Video"]


@dataclass
class Embedder:
    """Base class for managing embedders"""

    dimensions: Optional[int] = 1536
    enable_batch: bool = False
    batch_size: int = 100  # Number of texts to process in each API call

    # --- Text embedding (existing) ---

    def get_embedding(self, text: str) -> List[float]:
        raise NotImplementedError

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError

    async def async_get_embedding(self, text: str) -> List[float]:
        raise NotImplementedError

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError

    # --- Image embedding ---

    def get_image_embedding(self, image: Image) -> List[float]:
        raise NotImplementedError

    def get_image_embedding_and_usage(self, image: Image) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError

    async def async_get_image_embedding(self, image: Image) -> List[float]:
        raise NotImplementedError

    async def async_get_image_embedding_and_usage(self, image: Image) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError

    # --- Audio embedding ---

    def get_audio_embedding(self, audio: Audio) -> List[float]:
        raise NotImplementedError

    def get_audio_embedding_and_usage(self, audio: Audio) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError

    async def async_get_audio_embedding(self, audio: Audio) -> List[float]:
        raise NotImplementedError

    async def async_get_audio_embedding_and_usage(self, audio: Audio) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError

    # --- Video embedding ---

    def get_video_embedding(self, video: Video) -> List[float]:
        raise NotImplementedError

    def get_video_embedding_and_usage(self, video: Video) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError

    async def async_get_video_embedding(self, video: Video) -> List[float]:
        raise NotImplementedError

    async def async_get_video_embedding_and_usage(self, video: Video) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError

    # --- Multimodal embedding ---

    def get_multimodal_embedding(self, content: Sequence[EmbeddingInput]) -> List[float]:
        raise NotImplementedError

    def get_multimodal_embedding_and_usage(
        self, content: Sequence[EmbeddingInput]
    ) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError

    async def async_get_multimodal_embedding(self, content: Sequence[EmbeddingInput]) -> List[float]:
        raise NotImplementedError

    async def async_get_multimodal_embedding_and_usage(
        self, content: Sequence[EmbeddingInput]
    ) -> Tuple[List[float], Optional[Dict]]:
        raise NotImplementedError
