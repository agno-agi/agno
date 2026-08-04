from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class MediaStorage(ABC):
    """Sync media storage backend for uploading and retrieving media files."""

    # Short backend identifier persisted on every MediaReference, e.g. "s3". Every backend sets it.
    backend_name: str
    # Container this backend writes to, recorded verbatim on every MediaReference so a reader
    # can tell where a stored key lives. None on a backend with no container concept (local disk).
    bucket: Optional[str] = None
    # Region the container lives in, recorded on the MediaReference alongside the bucket.
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
    def get_url(self, storage_key: str, *, expires_in: Optional[int] = None) -> str:
        """Get a URL for accessing the stored content.

        ``expires_in=None`` means "use whatever expiry this backend is configured with";
        a backend whose URLs never expire ignores the argument entirely.

        Returns ``""`` when the backend cannot produce a usable URL for this key — GCS
        with non-signing application-default credentials is the case that happens in
        practice. Callers treat the empty string as "no URL, read the bytes instead"
        rather than as a failure, so a backend must not raise for it.
        """
        raise NotImplementedError

    @abstractmethod
    def delete(self, storage_key: str) -> bool:
        """Delete content by storage_key.

        Idempotent: True means the object is gone, whether this call removed it or it
        was already absent. S3's DeleteObject cannot tell those apart without a second
        round-trip, so no backend promises to — deleting twice is not an error. False
        means the delete itself failed and the object may still be there.
        """
        raise NotImplementedError

    def delete_many(self, storage_keys: List[str]) -> int:
        """Delete several objects, returning how many are now gone.

        Idempotent per key, exactly as :meth:`delete` is. Backends whose API takes a
        batch override this; the default is a loop so a third-party backend only has
        to implement ``delete``.
        """
        return sum(1 for key in storage_keys if self.delete(key))

    @abstractmethod
    def exists(self, storage_key: str) -> bool:
        """Check if content exists at storage_key."""
        raise NotImplementedError


class AsyncMediaStorage(ABC):
    """Async media storage backend. Same method names as MediaStorage (matching AsyncBaseDb pattern)."""

    # Short backend identifier persisted on every MediaReference, e.g. "s3". Every backend sets it.
    backend_name: str
    # Container this backend writes to, recorded verbatim on every MediaReference so a reader
    # can tell where a stored key lives. None on a backend with no container concept (local disk).
    bucket: Optional[str] = None
    # Region the container lives in, recorded on the MediaReference alongside the bucket.
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
    async def get_url(self, storage_key: str, *, expires_in: Optional[int] = None) -> str:
        """Get a URL for accessing the stored content.

        ``expires_in=None`` means "use whatever expiry this backend is configured with";
        a backend whose URLs never expire ignores the argument entirely.

        Returns ``""`` when the backend cannot produce a usable URL for this key — GCS
        with non-signing application-default credentials is the case that happens in
        practice. Callers treat the empty string as "no URL, read the bytes instead"
        rather than as a failure, so a backend must not raise for it.
        """
        raise NotImplementedError

    @abstractmethod
    async def delete(self, storage_key: str) -> bool:
        """Delete content by storage_key.

        Idempotent: True means the object is gone, whether this call removed it or it
        was already absent. S3's DeleteObject cannot tell those apart without a second
        round-trip, so no backend promises to — deleting twice is not an error. False
        means the delete itself failed and the object may still be there.
        """
        raise NotImplementedError

    async def delete_many(self, storage_keys: List[str]) -> int:
        """Delete several objects, returning how many are now gone.

        Idempotent per key, exactly as :meth:`delete` is. Backends whose API takes a
        batch override this; the default is a loop so a third-party backend only has
        to implement ``delete``.
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
