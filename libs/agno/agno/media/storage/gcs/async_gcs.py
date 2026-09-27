import asyncio
from typing import Any, Dict, List, Optional

from agno.media.storage.base import AsyncMediaStorage
from agno.media.storage.gcs.gcs import GCSMediaStorage


class AsyncGCSMediaStorage(AsyncMediaStorage):
    """Async Google Cloud Storage media storage backend.

    google-cloud-storage has no native async API, so each call runs the synchronous
    GCSMediaStorage in a worker thread and a large upload does not block the event loop.

    ``public`` and the signing rules are the sync backend's: see GCSMediaStorage.
    """

    backend_name = "gcs"

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "agno/media/",
        credentials_path: Optional[str] = None,
        project: Optional[str] = None,
        presigned_url_expiry: int = 3600,
        public: bool = False,
        persist_remote_urls: bool = False,
    ):
        self._sync = GCSMediaStorage(
            bucket=bucket,
            prefix=prefix,
            credentials_path=credentials_path,
            project=project,
            presigned_url_expiry=presigned_url_expiry,
            public=public,
            persist_remote_urls=persist_remote_urls,
        )
        self.persist_remote_urls = persist_remote_urls
        # Mirror the delegate's configuration so this class reads the same as the sync one.
        self.bucket = bucket
        self.prefix = prefix
        self.credentials_path = credentials_path
        self.project = project
        self.presigned_url_expiry = presigned_url_expiry
        self.public = public

    async def upload(
        self,
        media_id: str,
        content: bytes,
        *,
        mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        return await asyncio.to_thread(
            self._sync.upload, media_id, content, mime_type=mime_type, filename=filename, metadata=metadata
        )

    async def download(self, storage_key: str) -> bytes:
        return await asyncio.to_thread(self._sync.download, storage_key)

    async def get_url(self, storage_key: str, *, expires_in: Optional[int] = None) -> Optional[str]:
        return await asyncio.to_thread(self._sync.get_url, storage_key, expires_in=expires_in)

    async def delete(self, storage_key: str) -> bool:
        return await asyncio.to_thread(self._sync.delete, storage_key)

    async def delete_many(self, storage_keys: List[str]) -> int:
        # One hop to the worker thread for the whole batch, not one per key.
        return await asyncio.to_thread(self._sync.delete_many, storage_keys)

    async def exists(self, storage_key: str) -> bool:
        return await asyncio.to_thread(self._sync.exists, storage_key)
