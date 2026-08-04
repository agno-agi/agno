import hashlib
import os
from pathlib import Path
from tempfile import mkstemp
from typing import Any, Dict, Optional

from agno.media.storage.base import MediaStorage
from agno.media.storage.utils import build_storage_key
from agno.utils.log import log_debug, log_warning
from agno.utils.path_safety import safe_join_relative_path


class LocalMediaStorage(MediaStorage):
    """Local filesystem media storage backend for development and testing.

    ``base_url`` decides whether a stored key is addressable at all. Set it to the prefix
    some other server exposes ``base_path`` under and ``get_url`` returns that link, which
    is then persisted on the ``MediaReference`` for readers to use directly. Leave it unset
    and ``get_url`` falls back to a ``file://`` URI that only works on this machine, so
    every reader has to come back through ``download`` or the AgentOS media route.
    """

    backend_name = "local"

    def __init__(
        self,
        base_path: str = "./media_storage",
        base_url: Optional[str] = None,
        persist_remote_urls: bool = False,
    ):
        # Resolved once: a relative base_path would otherwise be re-joined against the cwd on
        # every call, so a chdir moves the store and delete() reports True for a file it never
        # touched.
        self.base_path = Path(base_path).resolve()
        self.base_url = base_url.rstrip("/") if base_url else None
        self.persist_remote_urls = persist_remote_urls
        self.base_path.mkdir(parents=True, exist_ok=True)

    def upload(
        self,
        media_id: str,
        content: bytes,
        *,
        mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        key = build_storage_key(media_id, filename=filename, mime_type=mime_type)
        file_path = safe_join_relative_path(self.base_path, key)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename: content-addressed keys mean two runs can write the same object
        # while a third reads it, and a truncating write serves a partial file. os.replace is
        # atomic within a filesystem, so a reader sees the old bytes or the new ones.
        tmp_fd, tmp_name = mkstemp(dir=str(file_path.parent), prefix=f".{file_path.name}.", suffix=".part")
        try:
            with os.fdopen(tmp_fd, "wb") as tmp:
                tmp.write(content)
            os.replace(tmp_name, file_path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

        # Write metadata sidecar
        if metadata or filename or mime_type:
            import json

            # content-sha256 and original-filename use the shared metadata spelling. mime_type
            # is recorded here because a plain filesystem has nowhere else to keep it.
            meta: Dict[str, Any] = {}
            if filename:
                meta["original-filename"] = filename
            if mime_type:
                meta["mime_type"] = mime_type
            meta["content-sha256"] = hashlib.sha256(content).hexdigest()
            meta["size"] = len(content)
            if metadata:
                meta.update(metadata)
            sidecar = file_path.with_suffix(file_path.suffix + ".meta.json")
            sidecar.write_text(json.dumps(meta, indent=2))

        log_debug(f"Saved media {media_id} to {file_path}")
        return key

    def download(self, storage_key: str) -> bytes:
        file_path = safe_join_relative_path(self.base_path, storage_key)
        return file_path.read_bytes()

    def get_url(self, storage_key: str, *, expires_in: Optional[int] = None) -> str:
        # Local URLs are a static path or a file:// URI; neither expires, so expires_in
        # has nothing to apply to.
        if self.base_url:
            return f"{self.base_url}/{storage_key}"
        try:
            return safe_join_relative_path(self.base_path, storage_key).as_uri()
        except Exception as e:
            # The contract for a key this backend cannot address is "", not an exception.
            log_debug(f"Could not build a local URL for {storage_key}: {e}")
            return ""

    def delete(self, storage_key: str) -> bool:
        try:
            # Joined inside the try so a key that fails containment returns False like any other
            # failed delete, rather than raising and stranding the rest of a delete_many batch.
            file_path = safe_join_relative_path(self.base_path, storage_key)
            file_path.unlink(missing_ok=True)
            # Also remove metadata sidecar if present
            sidecar = file_path.with_suffix(file_path.suffix + ".meta.json")
            sidecar.unlink(missing_ok=True)
            return True
        except Exception as e:
            log_warning(f"Failed to delete {storage_key}: {e}")
            return False

    def exists(self, storage_key: str) -> bool:
        try:
            # Joined inside the try for the same reason delete() does: a key this backend
            # cannot address is "not there" as far as the caller is concerned.
            return safe_join_relative_path(self.base_path, storage_key).exists()
        except Exception:
            return False
