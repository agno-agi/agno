from typing import Any, Dict, Optional

from pydantic import BaseModel


class MediaReference(BaseModel):
    """Lightweight reference stored in DB instead of base64 content."""

    media_id: str
    storage_key: str  # S3 object key — also serves as discriminator for deserialization
    storage_backend: str  # "s3", "local", etc.
    bucket: Optional[str] = None
    region: Optional[str] = None
    url: Optional[str] = None  # presigned or public URL
    mime_type: Optional[str] = None
    filename: Optional[str] = None
    size: Optional[int] = None  # bytes
    content_hash: Optional[str] = None  # SHA-256
    media_type: Optional[str] = None  # "image", "audio", "video", "file"
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MediaReference":
        return cls(**data)
