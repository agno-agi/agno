import hashlib
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional

from agno.media_storage.base import AsyncMediaStorage, MediaStorage
from agno.utils.log import logger


class LocalMediaStorage(MediaStorage):
    """Local filesystem media storage backend for development and testing."""

    def __init__(
        self,
        base_path: str = "./media_storage",
        base_url: Optional[str] = None,
        persist_remote_urls: bool = False,
    ):
        self.base_path = Path(base_path)
        self.base_url = base_url.rstrip("/") if base_url else None
        self.persist_remote_urls = persist_remote_urls
        self.base_path.mkdir(parents=True, exist_ok=True)

    @property
    def backend_name(self) -> str:
        return "local"

    def _build_key(self, media_id: str, *, filename: Optional[str] = None, mime_type: Optional[str] = None) -> str:
        ext = ""
        if filename and "." in filename:
            ext = "." + filename.rsplit(".", 1)[-1]
        elif mime_type:
            guessed = mimetypes.guess_extension(mime_type)
            if guessed:
                ext = guessed
        return f"{media_id}{ext}"

    def _resolve_path(self, storage_key: str) -> Path:
        return self.base_path / storage_key

    def upload(
        self,
        media_id: str,
        content: bytes,
        *,
        mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        key = self._build_key(media_id, filename=filename, mime_type=mime_type)
        file_path = self._resolve_path(key)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)

        # Write metadata sidecar
        if metadata or filename or mime_type:
            import json

            meta: Dict[str, Any] = {}
            if filename:
                meta["original_filename"] = filename
            if mime_type:
                meta["mime_type"] = mime_type
            meta["content_sha256"] = hashlib.sha256(content).hexdigest()
            meta["size"] = len(content)
            if metadata:
                meta.update(metadata)
            sidecar = file_path.with_suffix(file_path.suffix + ".meta.json")
            sidecar.write_text(json.dumps(meta, indent=2))

        logger.debug(f"Saved media {media_id} to {file_path}")
        return key

    def download(self, storage_key: str) -> bytes:
        file_path = self._resolve_path(storage_key)
        return file_path.read_bytes()

    def get_url(self, storage_key: str, *, expires_in: int = 3600) -> str:
        if self.base_url:
            return f"{self.base_url}/{storage_key}"
        file_path = self._resolve_path(storage_key).resolve()
        return file_path.as_uri()

    def delete(self, storage_key: str) -> bool:
        file_path = self._resolve_path(storage_key)
        try:
            file_path.unlink(missing_ok=True)
            # Also remove metadata sidecar if present
            sidecar = file_path.with_suffix(file_path.suffix + ".meta.json")
            sidecar.unlink(missing_ok=True)
            return True
        except Exception as e:
            logger.warning(f"Failed to delete {storage_key}: {e}")
            return False

    def exists(self, storage_key: str) -> bool:
        return self._resolve_path(storage_key).exists()


class AsyncLocalMediaStorage(AsyncMediaStorage):
    """Async local filesystem media storage for development and testing.

    Delegates to the synchronous LocalMediaStorage implementation.
    """

    def __init__(
        self,
        base_path: str = "./media_storage",
        base_url: Optional[str] = None,
        persist_remote_urls: bool = False,
    ):
        self._sync = LocalMediaStorage(base_path=base_path, base_url=base_url, persist_remote_urls=persist_remote_urls)
        self.persist_remote_urls = persist_remote_urls

    @property
    def backend_name(self) -> str:
        return "local"

    async def upload(
        self,
        media_id: str,
        content: bytes,
        *,
        mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        return self._sync.upload(media_id, content, mime_type=mime_type, filename=filename, metadata=metadata)

    async def download(self, storage_key: str) -> bytes:
        return self._sync.download(storage_key)

    async def get_url(self, storage_key: str, *, expires_in: int = 3600) -> str:
        return self._sync.get_url(storage_key, expires_in=expires_in)

    async def delete(self, storage_key: str) -> bool:
        return self._sync.delete(storage_key)

    async def exists(self, storage_key: str) -> bool:
        return self._sync.exists(storage_key)
