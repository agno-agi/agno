from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


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
