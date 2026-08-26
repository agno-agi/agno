from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class MediaStorage(ABC):
    """Sync media storage backend for uploading and retrieving media files."""

    # Short backend identifier persisted on every MediaReference, e.g. "s3".
    backend_name: str
    # Container written to, recorded on every reference: a bucket, or the local backend's base path.
    bucket: Optional[str] = None
    # Region the container lives in.
    region: Optional[str] = None
    # If True, media that arrives as a bare URL is fetched and stored rather than left as a link.
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
    def get_url(self, storage_key: str, *, expires_in: Optional[int] = None) -> Optional[str]:
        """Get a URL for accessing the stored content.

        ``expires_in=None`` uses the backend's configured expiry. Returns ``None`` when the
        backend cannot sign a URL, meaning callers should stream the bytes instead.
        """
        raise NotImplementedError

    @abstractmethod
    def delete(self, storage_key: str) -> bool:
        """Delete content by storage_key.

        Idempotent: True means the object is gone, whether or not this call removed it.
        False means the delete failed and the object may still be there.
        """
        raise NotImplementedError

    def delete_many(self, storage_keys: List[str]) -> int:
        """Delete several objects, returning how many are now gone.

        Idempotent per key, as :meth:`delete` is. Backends with a batch API override this.
        """
        return sum(1 for key in storage_keys if self.delete(key))

    @abstractmethod
    def exists(self, storage_key: str) -> bool:
        """Check if content exists at storage_key."""
        raise NotImplementedError


class AsyncMediaStorage(ABC):
    """Async media storage backend for uploading and retrieving media files."""

    # Short backend identifier persisted on every MediaReference, e.g. "s3".
    backend_name: str
    # Container written to, recorded on every reference: a bucket, or the local backend's base path.
    bucket: Optional[str] = None
    # Region the container lives in.
    region: Optional[str] = None
    # If True, media that arrives as a bare URL is fetched and stored rather than left as a link.
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
    async def get_url(self, storage_key: str, *, expires_in: Optional[int] = None) -> Optional[str]:
        """Get a URL for accessing the stored content.

        ``expires_in=None`` uses the backend's configured expiry. Returns ``None`` when the
        backend cannot sign a URL, meaning callers should stream the bytes instead.
        """
        raise NotImplementedError

    @abstractmethod
    async def delete(self, storage_key: str) -> bool:
        """Delete content by storage_key.

        Idempotent: True means the object is gone, whether or not this call removed it.
        False means the delete failed and the object may still be there.
        """
        raise NotImplementedError

    async def delete_many(self, storage_keys: List[str]) -> int:
        """Delete several objects, returning how many are now gone.

        Idempotent per key, as :meth:`delete` is. Backends with a batch API override this.
        """
        deleted = 0
        for key in storage_keys:
            if await self.delete(key):
                deleted += 1
        return deleted

    @abstractmethod
    async def exists(self, storage_key: str) -> bool:
        """Check if content exists at storage_key."""
        raise NotImplementedError
