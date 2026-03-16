from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from agno.knowledge.embedder import Embedder

if TYPE_CHECKING:
    from agno.media import Audio, Image, Video

# Registry: maps media class -> (sync_embed_method, async_embed_method)
# Lazy-initialized on first use to avoid import cycles.
_MEDIA_EMBEDDER_METHODS: Optional[Dict[type, tuple]] = None


def _get_media_embedder_methods() -> Dict[type, tuple]:
    global _MEDIA_EMBEDDER_METHODS
    if _MEDIA_EMBEDDER_METHODS is None:
        from agno.media import Audio, Image, Video

        _MEDIA_EMBEDDER_METHODS = {
            Image: ("get_image_embedding_and_usage", "async_get_image_embedding_and_usage"),
            Audio: ("get_audio_embedding_and_usage", "async_get_audio_embedding_and_usage"),
            Video: ("get_video_embedding_and_usage", "async_get_video_embedding_and_usage"),
        }
    return _MEDIA_EMBEDDER_METHODS


@dataclass
class Document:
    """Dataclass for managing a document"""

    content: str
    id: Optional[str] = None
    name: Optional[str] = None
    meta_data: Dict[str, Any] = field(default_factory=dict)
    embedder: Optional["Embedder"] = None
    embedding: Optional[List[float]] = None
    usage: Optional[Dict[str, Any]] = None
    reranking_score: Optional[float] = None
    content_id: Optional[str] = None
    content_origin: Optional[str] = None
    size: Optional[int] = None
    media: Optional[Union["Image", "Audio", "Video"]] = None

    @property
    def has_media(self) -> bool:
        """Returns True if this document has an associated media object."""
        return self.media is not None

    def embed(self, embedder: Optional[Embedder] = None) -> None:
        """Embed the document using the provided embedder.

        If the document has media attached, dispatches to the appropriate
        media embedding method. Otherwise, embeds the text content.
        """
        _embedder = embedder or self.embedder
        if _embedder is None:
            raise ValueError("No embedder provided")

        if self.media is not None:
            registry = _get_media_embedder_methods()
            media_type = type(self.media)
            if media_type not in registry:
                raise TypeError(f"Unsupported media type: {media_type.__name__}")
            method_name = registry[media_type][0]  # sync method
            self.embedding, self.usage = getattr(_embedder, method_name)(self.media)
        else:
            self.embedding, self.usage = _embedder.get_embedding_and_usage(self.content)

    async def async_embed(self, embedder: Optional[Embedder] = None) -> None:
        """Embed the document using the provided embedder.

        If the document has media attached, dispatches to the appropriate
        media embedding method. Otherwise, embeds the text content.
        """
        _embedder = embedder or self.embedder
        if _embedder is None:
            raise ValueError("No embedder provided")

        if self.media is not None:
            registry = _get_media_embedder_methods()
            media_type = type(self.media)
            if media_type not in registry:
                raise TypeError(f"Unsupported media type: {media_type.__name__}")
            method_name = registry[media_type][1]  # async method
            self.embedding, self.usage = await getattr(_embedder, method_name)(self.media)
        else:
            self.embedding, self.usage = await _embedder.async_get_embedding_and_usage(self.content)

    def to_dict(self) -> Dict[str, Any]:
        """Returns a dictionary representation of the document"""
        fields = {"name", "meta_data", "content"}
        return {
            field: getattr(self, field)
            for field in fields
            if getattr(self, field) is not None or field == "content"  # content is always included
        }

    @classmethod
    def from_dict(cls, document: Dict[str, Any]) -> "Document":
        """Returns a Document object from a dictionary representation"""
        return cls(**document)

    @classmethod
    def from_json(cls, document: str) -> "Document":
        """Returns a Document object from a json string representation"""
        import json

        return cls(**json.loads(document))
