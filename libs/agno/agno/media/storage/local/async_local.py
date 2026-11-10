import asyncio
from typing import Any, Dict, List, Optional

from agno.media.storage.base import AsyncMediaStorage
from agno.media.storage.local.local import LocalMediaStorage


class AsyncLocalMediaStorage(AsyncMediaStorage):
    """Async local filesystem media storage backend for development and testing.

    Each call runs the synchronous LocalMediaStorage in a worker thread so a large file
    write does not block the event loop.
    """

    backend_name = "local"

    def __init__(
        self,
        base_path: str = "./media_storage",
        persist_remote_urls: bool = False,
    ):
        self._sync = LocalMediaStorage(base_path=base_path, persist_remote_urls=persist_remote_urls)
        self.persist_remote_urls = persist_remote_urls
        # Read back off the delegate so the Path normalization is not duplicated.
        self.base_path = self._sync.base_path
        self.bucket = self._sync.bucket

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
