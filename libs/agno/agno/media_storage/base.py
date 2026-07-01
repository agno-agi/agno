import re
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


def sanitize_media_id(media_id: str) -> str:
    """Make a media id safe to use as a storage-key path component.

    Strips characters that could escape the storage root (path separators, ``..``),
    preventing path traversal in filesystem-backed storage and stray prefixes in S3.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(media_id))
    safe = safe.replace("..", "_")
    return safe.strip("._") or "media"


def sanitize_s3_metadata(items: Dict[str, Any], *, max_bytes: int = 1800) -> Dict[str, str]:
    """Coerce metadata to ASCII-only string values that S3 accepts.

    S3 user metadata must be ASCII and small (~2KB total). Entries that can't be
    ASCII-encoded or that would exceed the size budget are dropped — the full
    metadata is preserved on the MediaReference, so nothing is permanently lost.
    """
    safe: Dict[str, str] = {}
    total = 0
    for k, v in items.items():
        try:
            key = str(k).encode("ascii").decode("ascii")
            val = str(v).encode("ascii").decode("ascii")
        except UnicodeEncodeError:
            continue
        total += len(key) + len(val)
        if total > max_bytes:
            break
        safe[key] = val
    return safe


class MediaStorage(ABC):
    """Sync media storage backend for uploading and retrieving media files."""

    persist_remote_urls: bool = False

    @abstractmethod
    def upload(
        self,
        media_id: str,
        content: bytes,
        *,
        mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Upload content bytes, return storage_key."""
        raise NotImplementedError

    @abstractmethod
    def download(self, storage_key: str) -> bytes:
        """Download content bytes by storage_key."""
        raise NotImplementedError

    @abstractmethod
    def get_url(self, storage_key: str, *, expires_in: int = 3600) -> str:
        """Get a URL for accessing the stored content."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, storage_key: str) -> bool:
        """Delete content by storage_key. Returns True if deleted."""
        raise NotImplementedError

    @abstractmethod
    def exists(self, storage_key: str) -> bool:
        """Check if content exists at storage_key."""
        raise NotImplementedError


class AsyncMediaStorage(ABC):
    """Async media storage backend. Same method names as MediaStorage (matching AsyncBaseDb pattern)."""

    persist_remote_urls: bool = False

    @abstractmethod
    async def upload(
        self,
        media_id: str,
        content: bytes,
        *,
        mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Upload content bytes, return storage_key."""
        raise NotImplementedError

    @abstractmethod
    async def download(self, storage_key: str) -> bytes:
        """Download content bytes by storage_key."""
        raise NotImplementedError

    @abstractmethod
    async def get_url(self, storage_key: str, *, expires_in: int = 3600) -> str:
        """Get a URL for accessing the stored content."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, storage_key: str) -> bool:
        """Delete content by storage_key. Returns True if deleted."""
        raise NotImplementedError

    @abstractmethod
    async def exists(self, storage_key: str) -> bool:
        """Check if content exists at storage_key."""
        raise NotImplementedError
