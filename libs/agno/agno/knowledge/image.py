"""Pluggable storage for knowledge document images.

Preserves original images extracted by readers (e.g. DocxReader, DoclingReader)
and serves them via stable URLs such as ``/knowledge/images/{content_id}/{image_id}``.
"""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable
from uuid import uuid4

from agno.exceptions import PathSecurityError
from agno.utils.log import log_debug, log_warning
from agno.utils.path_safety import safe_join_filename, safe_join_relative_path

DEFAULT_IMAGE_BASE_URL = "/knowledge/images"
DEFAULT_MEDIA_TYPE = "image/png"


@dataclass
class KnowledgeImageRef:
    """Stable reference to a stored knowledge image."""

    image_id: str
    content_id: str
    media_type: str = DEFAULT_MEDIA_TYPE


@runtime_checkable
class KnowledgeImageStore(Protocol):
    """Protocol for storing and serving knowledge document images."""

    def save(
        self,
        *,
        content_id: str,
        data: bytes,
        media_type: str = DEFAULT_MEDIA_TYPE,
    ) -> KnowledgeImageRef:
        """Persist image bytes and return a stable reference."""
        ...

    async def asave(
        self,
        *,
        content_id: str,
        data: bytes,
        media_type: str = DEFAULT_MEDIA_TYPE,
    ) -> KnowledgeImageRef:
        """Async variant of :meth:`save`."""
        ...

    def delete(self, *, content_id: str, image_id: Optional[str] = None) -> None:
        """Delete one image or all images for a content document."""
        ...

    async def adelete(self, *, content_id: str, image_id: Optional[str] = None) -> None:
        """Async variant of :meth:`delete`."""
        ...

    def open(
        self,
        ref: KnowledgeImageRef,
        *,
        user_id: Optional[str] = None,
        **context: Any,
    ) -> bytes:
        """Load image bytes. Custom stores may enforce authorization here."""
        ...

    async def aopen(
        self,
        ref: KnowledgeImageRef,
        *,
        user_id: Optional[str] = None,
        **context: Any,
    ) -> bytes:
        """Async variant of :meth:`open`."""
        ...


def build_image_url(
    ref: KnowledgeImageRef,
    *,
    image_base_url: str = DEFAULT_IMAGE_BASE_URL,
) -> str:
    """Build the fixed HTTP path for a stored image: ``/knowledge/images/{content_id}/{image_id}``."""
    base = image_base_url.rstrip("/")
    return f"{base}/{ref.content_id}/{ref.image_id}"


def build_markdown_image(
    ref: KnowledgeImageRef,
    *,
    image_base_url: str = DEFAULT_IMAGE_BASE_URL,
    alt_text: str = "",
) -> str:
    """Return an inline image link ``![alt](url)`` for the stored image."""
    return f"![{alt_text}]({build_image_url(ref, image_base_url=image_base_url)})"


def save_image_url(
    *,
    content_id: str,
    data: bytes,
    media_type: str = DEFAULT_MEDIA_TYPE,
    image_base_url: str = DEFAULT_IMAGE_BASE_URL,
) -> str:
    """Persist an image via the global store and return its public URL path."""
    ref = get_image_store().save(content_id=content_id, data=data, media_type=media_type)
    return build_image_url(ref, image_base_url=image_base_url)


def save_image_markdown(
    *,
    content_id: str,
    data: bytes,
    media_type: str = DEFAULT_MEDIA_TYPE,
    image_base_url: str = DEFAULT_IMAGE_BASE_URL,
    alt_text: str = "",
) -> str:
    """Persist an image and return an inline image link: ``![alt](url)``.

    This is a single markdown image tag for embedding in plain text, not a
    markdown document conversion.
    """
    url = save_image_url(
        content_id=content_id,
        data=data,
        media_type=media_type,
        image_base_url=image_base_url,
    )
    return f"![{alt_text}]({url})"


def _extension_for_media_type(media_type: str) -> str:
    ext = mimetypes.guess_extension(media_type.split(";")[0].strip()) or ".png"
    # guess_extension returns ".jpe" for image/jpeg on some platforms
    if ext in {".jpe", ".jpeg"}:
        return ".jpg"
    return ext


def _generate_image_id(data: bytes) -> str:
    digest = hashlib.md5(data).hexdigest()[:8]
    return f"img-{uuid4().hex[:8]}-{digest}"


@dataclass
class LocalKnowledgeImageStore:
    """Filesystem-backed knowledge image store.

    Layout: ``{base_dir}/{content_id}/{image_id}{ext}``
    """

    base_dir: str = "doc_images"

    def __post_init__(self) -> None:
        self._base_path = Path(self.base_dir)
        self._base_path.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        *,
        content_id: str,
        data: bytes,
        media_type: str = DEFAULT_MEDIA_TYPE,
    ) -> KnowledgeImageRef:
        content_id = _sanitize_id(content_id, "content_id")
        image_id = _generate_image_id(data)
        extension = _extension_for_media_type(media_type)
        content_dir = safe_join_relative_path(self._base_path, content_id)
        content_dir.mkdir(parents=True, exist_ok=True)
        path = safe_join_filename(content_dir, f"{image_id}{extension}")
        path.write_bytes(data)
        log_debug(f"Saved knowledge image: {path}")
        return KnowledgeImageRef(image_id=image_id, content_id=content_id, media_type=media_type)

    async def asave(
        self,
        *,
        content_id: str,
        data: bytes,
        media_type: str = DEFAULT_MEDIA_TYPE,
    ) -> KnowledgeImageRef:
        import asyncio

        return await asyncio.to_thread(self.save, content_id=content_id, data=data, media_type=media_type)

    def delete(self, *, content_id: str, image_id: Optional[str] = None) -> None:
        import shutil

        content_id = _sanitize_id(content_id, "content_id")
        content_dir = safe_join_relative_path(self._base_path, content_id)
        if not content_dir.exists():
            return

        if image_id is None:
            shutil.rmtree(content_dir, ignore_errors=True)
            log_debug(f"Deleted knowledge images for content: {content_id}")
            return

        image_id = _sanitize_id(image_id, "image_id")
        removed = False
        for path in content_dir.glob(f"{image_id}.*"):
            try:
                path.unlink(missing_ok=True)
                removed = True
            except OSError as e:
                log_warning(f"Failed to delete knowledge image {path}: {e}")
        if removed and content_dir.exists() and not any(content_dir.iterdir()):
            content_dir.rmdir()

    async def adelete(self, *, content_id: str, image_id: Optional[str] = None) -> None:
        import asyncio

        await asyncio.to_thread(self.delete, content_id=content_id, image_id=image_id)

    def open(
        self,
        ref: KnowledgeImageRef,
        *,
        user_id: Optional[str] = None,
        **context: Any,
    ) -> bytes:
        # Local default ignores user_id; custom stores may authorize here.
        _ = user_id, context
        content_id = _sanitize_id(ref.content_id, "content_id")
        image_id = _sanitize_id(ref.image_id, "image_id")
        content_dir = safe_join_relative_path(self._base_path, content_id)
        matches = sorted(content_dir.glob(f"{image_id}.*"))
        if not matches:
            raise FileNotFoundError(f"Knowledge image not found: {content_id}/{image_id}")
        path = matches[0]
        guessed, _ = mimetypes.guess_type(path.name)
        if guessed:
            ref.media_type = guessed
        return path.read_bytes()

    async def aopen(
        self,
        ref: KnowledgeImageRef,
        *,
        user_id: Optional[str] = None,
        **context: Any,
    ) -> bytes:
        import asyncio

        return await asyncio.to_thread(self.open, ref, user_id=user_id, **context)


# Process-wide store shared by readers, Knowledge cleanup, and AgentOS image routes.
_image_store: Optional[KnowledgeImageStore] = None


def get_image_store() -> KnowledgeImageStore:
    """Return the global knowledge image store, creating a local default if needed."""
    global _image_store
    if _image_store is None:
        _image_store = LocalKnowledgeImageStore()
    return _image_store


def set_image_store(store: Optional[KnowledgeImageStore]) -> None:
    """Replace the global knowledge image store (e.g. at application startup)."""
    global _image_store
    _image_store = store


def _sanitize_id(value: str, field_name: str) -> str:
    if not value or not value.strip():
        raise PathSecurityError(f"Invalid {field_name}: {value!r}")
    # IDs are single path segments; reject separators up front.
    if "/" in value or "\\" in value or ".." in value:
        raise PathSecurityError(f"Invalid {field_name}: {value!r}")
    from agno.utils.path_safety import sanitize_filename

    return sanitize_filename(value)
