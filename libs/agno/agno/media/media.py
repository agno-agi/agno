import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from pydantic import BaseModel, field_validator, model_validator

from agno.media.reference import MediaReference
from agno.media.storage.base import AsyncMediaStorage, MediaStorage
from agno.utils.log import log_error, log_warning


def bytes_and_mime_from_url(url: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Read bytes from an http(s) URL along with the type the server declared.

    No ``file://`` support: every ``url`` reaching here is caller-supplied, so honouring one
    would let a caller read the local filesystem. Media held by the local storage backend is
    rehydrated through ``storage.download()`` instead. The declared type is returned because a
    url whose path carries no extension is otherwise unidentifiable.
    """
    import httpx

    resp = httpx.get(url, follow_redirects=True)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "").split(";")[0].strip()
    return resp.content, content_type or None


async def abytes_and_mime_from_url(url: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Async variant of bytes_and_mime_from_url."""
    import httpx

    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "").split(";")[0].strip()
        return resp.content, content_type or None


def _bytes_from_url(url: str) -> Optional[bytes]:
    """Read bytes from an http(s) URL. Raises on HTTP error responses."""
    content, _ = bytes_and_mime_from_url(url)
    return content


async def _abytes_from_url(url: str) -> Optional[bytes]:
    """Async variant of _bytes_from_url."""
    content, _ = await abytes_and_mime_from_url(url)
    return content


def _bytes_from_url_or_storage(
    media: Any, url: str, storage: Optional[Union[MediaStorage, AsyncMediaStorage]]
) -> Optional[bytes]:
    """Read ``url``, falling back to the stored object when the fetch fails.

    A storage handle names the copy this feature made, so an unreachable url is not the
    end of the road. Without one the fetch error surfaces, as it does without a handle.
    """
    try:
        return _bytes_from_url(url)
    except Exception:
        if storage is None or getattr(media, "media_reference", None) is None:
            raise
    return _resolve_from_storage(media, storage)


async def _abytes_from_url_or_storage(
    media: Any, url: str, storage: Optional[Union[MediaStorage, AsyncMediaStorage]]
) -> Optional[bytes]:
    """Async variant of :func:`_bytes_from_url_or_storage`."""
    try:
        return await _abytes_from_url(url)
    except Exception:
        if storage is None or getattr(media, "media_reference", None) is None:
            raise
    return await _aresolve_from_storage(media, storage)


def _resolve_from_storage(media: Any, storage: Optional[Union[MediaStorage, AsyncMediaStorage]]) -> Optional[bytes]:
    """Read an offloaded object's bytes back through the backend that stored it.

    Returns None when ``media`` carries no reference, when ``storage`` is not the backend
    that minted it, or when the read fails — a caller that already has ``content``, a
    ``url`` or a ``filepath`` reads from those instead.
    """
    ref = getattr(media, "media_reference", None)
    if storage is None or ref is None or not ref.storage_key:
        return None
    if isinstance(storage, AsyncMediaStorage):
        raise ValueError(
            "Cannot use sync get_content_bytes() with an AsyncMediaStorage. Use aget_content_bytes() instead."
        )

    from agno.utils.media_offload import reference_matches_storage

    # A key only resolves against the backend that wrote it, so a mismatched handle would
    # otherwise read a same-named object out of the wrong bucket.
    if not reference_matches_storage(ref, storage):
        log_warning(f"Media {getattr(media, 'id', '?')} was stored on another backend, skipping")
        return None
    try:
        return storage.download(ref.storage_key)
    except Exception as e:
        log_warning(f"Could not read stored media {getattr(media, 'id', '?')} back: {type(e).__name__}: {e}")
        return None


async def _aresolve_from_storage(
    media: Any, storage: Optional[Union[MediaStorage, AsyncMediaStorage]]
) -> Optional[bytes]:
    """Async variant of :func:`_resolve_from_storage`."""
    ref = getattr(media, "media_reference", None)
    if storage is None or ref is None or not ref.storage_key:
        return None

    from agno.utils.media_offload import reference_matches_storage

    if not reference_matches_storage(ref, storage):
        log_warning(f"Media {getattr(media, 'id', '?')} was stored on another backend, skipping")
        return None
    try:
        if isinstance(storage, AsyncMediaStorage):
            return await storage.download(ref.storage_key)
        # A sync backend downloads in a worker thread rather than on the running loop.
        return await asyncio.to_thread(storage.download, ref.storage_key)
    except Exception as e:
        log_warning(f"Could not read stored media {getattr(media, 'id', '?')} back: {type(e).__name__}: {e}")
        return None


def _url_from_storage(
    media: Any, storage: Optional[Union[MediaStorage, AsyncMediaStorage]], expires_in: Optional[int] = None
) -> Optional[str]:
    """Re-sign a URL for an offloaded object from its ``storage_key``.

    Always re-derived rather than read off the reference: a persisted URL is either absent
    (the usual case, since a presigned one is never stored) or stale. Returns None when the
    backend cannot produce a usable link, which is the caller's cue to fetch bytes instead.
    """
    ref = getattr(media, "media_reference", None)
    if storage is None or ref is None or not ref.storage_key:
        return None
    if isinstance(storage, AsyncMediaStorage):
        raise ValueError("Cannot use sync get_url() with an AsyncMediaStorage. Use aget_url() instead.")

    from agno.utils.media_offload import reference_matches_storage

    if not reference_matches_storage(ref, storage):
        log_warning(f"Media {getattr(media, 'id', '?')} was stored on another backend, skipping")
        return None
    try:
        url = storage.get_url(ref.storage_key, expires_in=expires_in)
    except Exception as e:
        log_warning(f"Could not sign a URL for {getattr(media, 'id', '?')}: {e}")
        return None
    # None is the backend saying it cannot sign, which is the caller's cue to fetch bytes.
    return url or None


async def _aurl_from_storage(
    media: Any, storage: Optional[Union[MediaStorage, AsyncMediaStorage]], expires_in: Optional[int] = None
) -> Optional[str]:
    """Async variant of :func:`_url_from_storage`."""
    ref = getattr(media, "media_reference", None)
    if storage is None or ref is None or not ref.storage_key:
        return None

    from agno.utils.media_offload import reference_matches_storage

    if not reference_matches_storage(ref, storage):
        log_warning(f"Media {getattr(media, 'id', '?')} was stored on another backend, skipping")
        return None
    try:
        if isinstance(storage, AsyncMediaStorage):
            url = await storage.get_url(ref.storage_key, expires_in=expires_in)
        else:
            url = await asyncio.to_thread(storage.get_url, ref.storage_key, expires_in=expires_in)
    except Exception as e:
        log_warning(f"Could not sign a URL for {getattr(media, 'id', '?')}: {e}")
        return None
    return url or None


class Image(BaseModel):
    """Unified Image class for all use cases (input, output, artifacts)"""

    # Core content fields (exactly one required)
    url: Optional[str] = None  # Remote location
    filepath: Optional[Union[Path, str]] = None  # Local file path
    content: Optional[bytes] = None  # Raw image bytes (standardized to bytes)

    # Metadata fields
    id: Optional[str] = None  # For tracking/referencing
    format: Optional[str] = None  # E.g. 'png', 'jpeg', 'webp', 'gif'
    mime_type: Optional[str] = None  # E.g. 'image/png', 'image/jpeg'

    # Input-specific fields
    detail: Optional[str] = (
        None  # low, medium, high or auto (per OpenAI spec https://platform.openai.com/docs/guides/vision?lang=node#low-or-high-fidelity-image-understanding)
    )

    # Output-specific fields (from tools/LLMs)
    original_prompt: Optional[str] = None  # Original generation prompt
    revised_prompt: Optional[str] = None  # Revised generation prompt
    alt_text: Optional[str] = None  # Alt text description

    # External media storage reference (set when media is offloaded to object storage)
    media_reference: Optional[MediaReference] = None
    # User-facing custom metadata
    metadata: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    def validate_and_normalize_content(cls, data: Any):
        """Ensure exactly one content source and normalize to bytes"""
        if isinstance(data, dict):
            # media_reference is a valid source — skip normal validation
            if data.get("media_reference") is not None:
                if isinstance(data["media_reference"], dict):
                    data["media_reference"] = MediaReference.from_dict(data["media_reference"])
                if data.get("id") is None:
                    data["id"] = str(uuid4())
                return data

            url = data.get("url")
            filepath = data.get("filepath")
            content = data.get("content")

            # Count non-None sources
            sources = [x for x in [url, filepath, content] if x is not None]
            if len(sources) == 0:
                raise ValueError("One of 'url', 'filepath', or 'content' must be provided")
            elif len(sources) > 1:
                raise ValueError("Only one of 'url', 'filepath', or 'content' should be provided")

            # Auto-generate ID if not provided
            if data.get("id") is None:
                data["id"] = str(uuid4())

        return data

    def get_content_bytes(self, storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None) -> Optional[bytes]:
        """Get image content as raw bytes, loading from URL/file if needed"""
        if self.content:
            return self.content
        elif self.url:
            return _bytes_from_url_or_storage(self, self.url, storage)
        elif self.media_reference and self.media_reference.url:
            return _bytes_from_url_or_storage(self, self.media_reference.url, storage)
        elif self.filepath:
            with open(self.filepath, "rb") as f:
                return f.read()
        # Offloaded media carries only a reference on a private backend, so the bytes come
        # back through the storage handle the caller passes in.
        return _resolve_from_storage(self, storage)

    async def aget_content_bytes(
        self, storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None
    ) -> Optional[bytes]:
        if self.content:
            return self.content
        elif self.url:
            return await _abytes_from_url_or_storage(self, self.url, storage)
        elif self.media_reference and self.media_reference.url:
            return await _abytes_from_url_or_storage(self, self.media_reference.url, storage)
        elif self.filepath:
            fp = self.filepath
            return await asyncio.to_thread(lambda: Path(fp).read_bytes())
        return await _aresolve_from_storage(self, storage)

    def get_url(
        self, storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None, *, expires_in: Optional[int] = None
    ) -> Optional[str]:
        """A URL a browser or model can fetch this media from, or None.

        Prefers a URL the media already carries, else re-signs one from the stored object.
        None means there is no fetchable link — read the bytes with ``get_content_bytes``.
        Raises ValueError when ``storage`` is an AsyncMediaStorage; use ``aget_url``.
        """
        if self.url:
            return self.url
        if self.media_reference is not None and self.media_reference.url:
            return self.media_reference.url
        return _url_from_storage(self, storage, expires_in)

    async def aget_url(
        self, storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None, *, expires_in: Optional[int] = None
    ) -> Optional[str]:
        """Async variant of :meth:`get_url`."""
        if self.url:
            return self.url
        if self.media_reference is not None and self.media_reference.url:
            return self.media_reference.url
        return await _aurl_from_storage(self, storage, expires_in)

    def to_base64(self) -> Optional[str]:
        """Convert content to base64 string for transmission/storage"""
        content_bytes = self.get_content_bytes()
        if content_bytes:
            import base64

            return base64.b64encode(content_bytes).decode("utf-8")
        return None

    @classmethod
    def from_base64(
        cls,
        base64_content: str,
        id: Optional[str] = None,
        mime_type: Optional[str] = None,
        format: Optional[str] = None,
        **kwargs,
    ) -> "Image":
        """Create Image from base64 content"""
        import base64

        try:
            content_bytes = base64.b64decode(base64_content)
        except Exception:
            content_bytes = base64_content.encode("utf-8")

        return cls(content=content_bytes, id=id or str(uuid4()), mime_type=mime_type, format=format, **kwargs)

    def to_dict(self, include_base64_content: bool = True) -> Dict[str, Any]:
        """Convert to dict, optionally including base64-encoded content"""
        result: Dict[str, Any] = {
            "id": self.id,
            "url": self.url,
            "filepath": str(self.filepath) if self.filepath else None,
            "format": self.format,
            "mime_type": self.mime_type,
            "detail": self.detail,
            "original_prompt": self.original_prompt,
            "revised_prompt": self.revised_prompt,
            "alt_text": self.alt_text,
        }

        if self.media_reference is not None:
            result["media_reference"] = self.media_reference.to_dict()
        elif include_base64_content and self.content:
            result["content"] = self.to_base64()

        if self.metadata:
            result["metadata"] = self.metadata

        return {k: v for k, v in result.items() if v is not None}


class Audio(BaseModel):
    """Unified Audio class for all use cases (input, output, artifacts)"""

    # Core content fields (exactly one required)
    url: Optional[str] = None
    filepath: Optional[Union[Path, str]] = None
    content: Optional[bytes] = None  # Raw audio bytes (standardized to bytes)

    # Metadata fields
    id: Optional[str] = None
    format: Optional[str] = None  # E.g. 'mp3', 'wav', 'ogg'
    mime_type: Optional[str] = None  # E.g. 'audio/mpeg', 'audio/wav'

    # Audio-specific metadata
    duration: Optional[float] = None  # Duration in seconds
    sample_rate: Optional[int] = 24000  # Sample rate in Hz
    channels: Optional[int] = 1  # Number of audio channels

    # Output-specific fields (from LLMs)
    transcript: Optional[str] = None  # Text transcript of audio
    expires_at: Optional[int] = None  # Expiration timestamp for temporary URLs

    # External media storage reference (set when media is offloaded to object storage)
    media_reference: Optional[MediaReference] = None
    # User-facing custom metadata
    metadata: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    def validate_and_normalize_content(cls, data: Any):
        """Ensure exactly one content source and normalize to bytes"""
        if isinstance(data, dict):
            # media_reference is a valid source — skip normal validation
            if data.get("media_reference") is not None:
                if isinstance(data["media_reference"], dict):
                    data["media_reference"] = MediaReference.from_dict(data["media_reference"])
                if data.get("id") is None:
                    data["id"] = str(uuid4())
                return data

            url = data.get("url")
            filepath = data.get("filepath")
            content = data.get("content")

            sources = [x for x in [url, filepath, content] if x is not None]
            if len(sources) == 0:
                raise ValueError("One of 'url', 'filepath', or 'content' must be provided")
            elif len(sources) > 1:
                raise ValueError("Only one of 'url', 'filepath', or 'content' should be provided")

            if data.get("id") is None:
                data["id"] = str(uuid4())

        return data

    def get_content_bytes(self, storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None) -> Optional[bytes]:
        """Get audio content as raw bytes"""
        if self.content:
            return self.content
        elif self.url:
            return _bytes_from_url_or_storage(self, self.url, storage)
        elif self.media_reference and self.media_reference.url:
            return _bytes_from_url_or_storage(self, self.media_reference.url, storage)
        elif self.filepath:
            with open(self.filepath, "rb") as f:
                return f.read()
        # Offloaded media carries only a reference on a private backend, so the bytes come
        # back through the storage handle the caller passes in.
        return _resolve_from_storage(self, storage)

    async def aget_content_bytes(
        self, storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None
    ) -> Optional[bytes]:
        if self.content:
            return self.content
        elif self.url:
            return await _abytes_from_url_or_storage(self, self.url, storage)
        elif self.media_reference and self.media_reference.url:
            return await _abytes_from_url_or_storage(self, self.media_reference.url, storage)
        elif self.filepath:
            fp = self.filepath
            return await asyncio.to_thread(lambda: Path(fp).read_bytes())
        return await _aresolve_from_storage(self, storage)

    def get_url(
        self, storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None, *, expires_in: Optional[int] = None
    ) -> Optional[str]:
        """A URL a browser or model can fetch this media from, or None.

        Prefers a URL the media already carries, else re-signs one from the stored object.
        None means there is no fetchable link — read the bytes with ``get_content_bytes``.
        Raises ValueError when ``storage`` is an AsyncMediaStorage; use ``aget_url``.
        """
        if self.url:
            return self.url
        if self.media_reference is not None and self.media_reference.url:
            return self.media_reference.url
        return _url_from_storage(self, storage, expires_in)

    async def aget_url(
        self, storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None, *, expires_in: Optional[int] = None
    ) -> Optional[str]:
        """Async variant of :meth:`get_url`."""
        if self.url:
            return self.url
        if self.media_reference is not None and self.media_reference.url:
            return self.media_reference.url
        return await _aurl_from_storage(self, storage, expires_in)

    def to_base64(self) -> Optional[str]:
        """Convert content to base64 string"""
        content_bytes = self.get_content_bytes()
        if content_bytes:
            import base64

            return base64.b64encode(content_bytes).decode("utf-8")
        return None

    @classmethod
    def from_base64(
        cls,
        base64_content: str,
        id: Optional[str] = None,
        mime_type: Optional[str] = None,
        transcript: Optional[str] = None,
        expires_at: Optional[int] = None,
        sample_rate: Optional[int] = 24000,
        channels: Optional[int] = 1,
        **kwargs,
    ) -> "Audio":
        """Create Audio from base64 content (useful for API responses)"""
        import base64

        try:
            content_bytes = base64.b64decode(base64_content)
        except Exception:
            # If not valid base64, encode as UTF-8 bytes
            content_bytes = base64_content.encode("utf-8")

        return cls(
            content=content_bytes,
            id=id or str(uuid4()),
            mime_type=mime_type,
            transcript=transcript,
            expires_at=expires_at,
            sample_rate=sample_rate,
            channels=channels,
            **kwargs,
        )

    def to_dict(self, include_base64_content: bool = True) -> Dict[str, Any]:
        """Convert to dict, optionally including base64-encoded content"""
        result: Dict[str, Any] = {
            "id": self.id,
            "url": self.url,
            "filepath": str(self.filepath) if self.filepath else None,
            "format": self.format,
            "mime_type": self.mime_type,
            "duration": self.duration,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "transcript": self.transcript,
            "expires_at": self.expires_at,
        }

        if self.media_reference is not None:
            result["media_reference"] = self.media_reference.to_dict()
        elif include_base64_content and self.content:
            result["content"] = self.to_base64()

        if self.metadata:
            result["metadata"] = self.metadata

        return {k: v for k, v in result.items() if v is not None}


class Video(BaseModel):
    """Unified Video class for all use cases (input, output, artifacts)"""

    # Core content fields (exactly one required)
    url: Optional[str] = None
    filepath: Optional[Union[Path, str]] = None
    content: Optional[bytes] = None  # Raw video bytes (standardized to bytes)

    # Metadata fields
    id: Optional[str] = None
    format: Optional[str] = None  # E.g. 'mp4', 'mov', 'avi', 'webm'
    mime_type: Optional[str] = None  # E.g. 'video/mp4', 'video/quicktime'

    # Video-specific metadata
    duration: Optional[float] = None  # Duration in seconds
    width: Optional[int] = None  # Video width in pixels
    height: Optional[int] = None  # Video height in pixels
    fps: Optional[float] = None  # Frames per second

    # Output-specific fields (from tools)
    eta: Optional[str] = None  # Estimated time for generation
    original_prompt: Optional[str] = None
    revised_prompt: Optional[str] = None

    # External media storage reference (set when media is offloaded to object storage)
    media_reference: Optional[MediaReference] = None
    # User-facing custom metadata
    metadata: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    def validate_and_normalize_content(cls, data: Any):
        """Ensure exactly one content source and normalize to bytes"""
        if isinstance(data, dict):
            # media_reference is a valid source — skip normal validation
            if data.get("media_reference") is not None:
                if isinstance(data["media_reference"], dict):
                    data["media_reference"] = MediaReference.from_dict(data["media_reference"])
                if data.get("id") is None:
                    data["id"] = str(uuid4())
                return data

            url = data.get("url")
            filepath = data.get("filepath")
            content = data.get("content")

            sources = [x for x in [url, filepath, content] if x is not None]
            if len(sources) == 0:
                raise ValueError("One of 'url', 'filepath', or 'content' must be provided")
            elif len(sources) > 1:
                raise ValueError("Only one of 'url', 'filepath', or 'content' should be provided")

            if data.get("id") is None:
                data["id"] = str(uuid4())

        return data

    def get_content_bytes(self, storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None) -> Optional[bytes]:
        """Get video content as raw bytes"""
        if self.content:
            return self.content
        elif self.url:
            return _bytes_from_url_or_storage(self, self.url, storage)
        elif self.media_reference and self.media_reference.url:
            return _bytes_from_url_or_storage(self, self.media_reference.url, storage)
        elif self.filepath:
            with open(self.filepath, "rb") as f:
                return f.read()
        # Offloaded media carries only a reference on a private backend, so the bytes come
        # back through the storage handle the caller passes in.
        return _resolve_from_storage(self, storage)

    async def aget_content_bytes(
        self, storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None
    ) -> Optional[bytes]:
        if self.content:
            return self.content
        elif self.url:
            return await _abytes_from_url_or_storage(self, self.url, storage)
        elif self.media_reference and self.media_reference.url:
            return await _abytes_from_url_or_storage(self, self.media_reference.url, storage)
        elif self.filepath:
            fp = self.filepath
            return await asyncio.to_thread(lambda: Path(fp).read_bytes())
        return await _aresolve_from_storage(self, storage)

    def get_url(
        self, storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None, *, expires_in: Optional[int] = None
    ) -> Optional[str]:
        """A URL a browser or model can fetch this media from, or None.

        Prefers a URL the media already carries, else re-signs one from the stored object.
        None means there is no fetchable link — read the bytes with ``get_content_bytes``.
        Raises ValueError when ``storage`` is an AsyncMediaStorage; use ``aget_url``.
        """
        if self.url:
            return self.url
        if self.media_reference is not None and self.media_reference.url:
            return self.media_reference.url
        return _url_from_storage(self, storage, expires_in)

    async def aget_url(
        self, storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None, *, expires_in: Optional[int] = None
    ) -> Optional[str]:
        """Async variant of :meth:`get_url`."""
        if self.url:
            return self.url
        if self.media_reference is not None and self.media_reference.url:
            return self.media_reference.url
        return await _aurl_from_storage(self, storage, expires_in)

    def to_base64(self) -> Optional[str]:
        """Convert content to base64 string"""
        content_bytes = self.get_content_bytes()
        if content_bytes:
            import base64

            return base64.b64encode(content_bytes).decode("utf-8")
        return None

    @classmethod
    def from_base64(
        cls,
        base64_content: str,
        id: Optional[str] = None,
        mime_type: Optional[str] = None,
        format: Optional[str] = None,
        **kwargs,
    ) -> "Video":
        """Create Image from base64 content"""
        import base64

        try:
            content_bytes = base64.b64decode(base64_content)
        except Exception:
            content_bytes = base64_content.encode("utf-8")

        return cls(content=content_bytes, id=id or str(uuid4()), mime_type=mime_type, format=format, **kwargs)

    def to_dict(self, include_base64_content: bool = True) -> Dict[str, Any]:
        """Convert to dict, optionally including base64-encoded content"""
        result: Dict[str, Any] = {
            "id": self.id,
            "url": self.url,
            "filepath": str(self.filepath) if self.filepath else None,
            "format": self.format,
            "mime_type": self.mime_type,
            "duration": self.duration,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "eta": self.eta,
            "original_prompt": self.original_prompt,
            "revised_prompt": self.revised_prompt,
        }

        if self.media_reference is not None:
            result["media_reference"] = self.media_reference.to_dict()
        elif include_base64_content and self.content:
            result["content"] = self.to_base64()

        if self.metadata:
            result["metadata"] = self.metadata

        return {k: v for k, v in result.items() if v is not None}


class File(BaseModel):
    id: Optional[str] = None
    url: Optional[str] = None
    filepath: Optional[Union[Path, str]] = None
    # Raw bytes content of a file
    content: Optional[Any] = None
    mime_type: Optional[str] = None

    file_type: Optional[str] = None
    filename: Optional[str] = None
    size: Optional[int] = None
    # External file object (e.g. GeminiFile, must be a valid object as expected by the model you are using)
    external: Optional[Any] = None
    format: Optional[str] = None  # E.g. `pdf`, `txt`, `csv`, `xml`, etc.
    name: Optional[str] = None  # Name of the file, mandatory for AWS Bedrock document input
    # Anthropic-only: per-file citation preference. Ignored by other providers.
    #   None  = follow the caller default (Claude enables citations unless the request
    #           would also send output_format, in which case they are suppressed).
    #   False = do not attach citations to this file.
    #   True  = attach citations when the caller allows it; ignored (with a warning)
    #           when the caller has disabled citations for the request.
    citations: Optional[bool] = None

    # External media storage reference (set when media is offloaded to object storage)
    media_reference: Optional[MediaReference] = None
    # User-facing custom metadata
    metadata: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    @classmethod
    def check_at_least_one_source(cls, data):
        """Ensure at least one of id, url, filepath, content, external, or media_reference is provided."""
        if isinstance(data, dict):
            if not any(
                data.get(field) for field in ["id", "url", "filepath", "content", "external", "media_reference"]
            ):
                raise ValueError(
                    "At least one of id, url, filepath, content, external, or media_reference must be provided"
                )
            if isinstance(data.get("media_reference"), dict):
                data["media_reference"] = MediaReference.from_dict(data["media_reference"])
            # Auto-generate after the check above; a stable id is what lets the offload cache reuse an upload.
            if data.get("id") is None:
                data["id"] = str(uuid4())
        return data

    @field_validator("mime_type")
    @classmethod
    def validate_mime_type(cls, v):
        """Validate that the mime_type is one of the allowed types."""
        if v is not None and v not in cls.valid_mime_types():
            raise ValueError(f"Invalid MIME type: {v}. Must be one of: {cls.valid_mime_types()}")
        return v

    @classmethod
    def valid_mime_types(cls) -> List[str]:
        # NOTE: Keep this in sync with `DOCUMENT_MIME_TYPES` in agno.os.utils. Every MIME type
        # the upload routers accept must be valid here, otherwise FileMedia construction fails
        # and the file is silently dropped. Not all of these are accepted by every model
        # provider (e.g. Anthropic/Gemini reject Office binary formats); those fail at the
        # model with a provider error rather than being dropped at upload.
        return [
            "application/pdf",
            "application/json",
            "application/x-javascript",
            # Office Open XML (modern Office formats)
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
            # Legacy binary Office formats
            "application/msword",  # .doc
            "application/vnd.ms-powerpoint",  # .ppt
            "application/vnd.ms-excel",  # .xls
            "application/vnd.ms-outlook",  # .msg
            "application/zip",  # .zip
            "message/rfc822",  # .eml
            "text/javascript",
            "application/x-python",
            "text/x-python",
            "text/plain",
            "text/html",
            "text/css",
            "text/markdown",
            "text/csv",
            "text/xml",
            "text/rtf",
        ]

    @classmethod
    def from_base64(
        cls,
        base64_content: str,
        id: Optional[str] = None,
        mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        name: Optional[str] = None,
        format: Optional[str] = None,
    ) -> "File":
        """Create File from base64 encoded content or plain text.

        Handles both base64-encoded binary content and plain text content. This mirrors
        ``File._normalise_content``: ``text/*`` content is persisted as raw UTF-8 strings
        (never base64), everything else is base64-encoded. The decode therefore keys off
        ``mime_type`` rather than guessing, so plain text that happens to be valid base64
        (e.g. "TestData") is not silently corrupted.
        """
        import base64

        if mime_type and mime_type.startswith("text/"):
            # Symmetric with _normalise_content: text/* content is stored as raw UTF-8,
            # so decoding it as base64 would corrupt it.
            content_bytes = base64_content.encode("utf-8")
        else:
            try:
                content_bytes = base64.b64decode(base64_content)
            except Exception:
                # Not valid base64 - fall back to treating it as raw UTF-8 text.
                content_bytes = base64_content.encode("utf-8")

        return cls(
            content=content_bytes,
            id=id,
            mime_type=mime_type,
            filename=filename,
            name=name,
            format=format,
        )

    @property
    def file_url_content(self) -> Optional[Tuple[bytes, str]]:
        if not self.url:
            return None
        try:
            content, mime_type = bytes_and_mime_from_url(self.url)
        except Exception as e:
            log_error(f"Failed to download file from {self.url}: {str(e)}")
            return None
        return content or b"", mime_type or ""

    def get_content_bytes(self, storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None) -> Optional[bytes]:
        if self.content:
            if isinstance(self.content, bytes):
                return self.content
            elif isinstance(self.content, str):
                return self.content.encode("utf-8")
            return None
        elif self.url:
            return _bytes_from_url_or_storage(self, self.url, storage)
        elif self.media_reference and self.media_reference.url:
            return _bytes_from_url_or_storage(self, self.media_reference.url, storage)
        elif self.filepath:
            with open(self.filepath, "rb") as f:
                return f.read()
        # Offloaded media carries only a reference on a private backend, so the bytes come
        # back through the storage handle the caller passes in.
        return _resolve_from_storage(self, storage)

    async def aget_content_bytes(
        self, storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None
    ) -> Optional[bytes]:
        if self.content:
            if isinstance(self.content, bytes):
                return self.content
            elif isinstance(self.content, str):
                return self.content.encode("utf-8")
            return None
        elif self.url:
            return await _abytes_from_url_or_storage(self, self.url, storage)
        elif self.media_reference and self.media_reference.url:
            return await _abytes_from_url_or_storage(self, self.media_reference.url, storage)
        elif self.filepath:
            fp = self.filepath
            return await asyncio.to_thread(lambda: Path(fp).read_bytes())
        return await _aresolve_from_storage(self, storage)

    def get_url(
        self, storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None, *, expires_in: Optional[int] = None
    ) -> Optional[str]:
        """A URL a browser or model can fetch this media from, or None.

        Prefers a URL the media already carries, else re-signs one from the stored object.
        None means there is no fetchable link — read the bytes with ``get_content_bytes``.
        Raises ValueError when ``storage`` is an AsyncMediaStorage; use ``aget_url``.
        """
        if self.url:
            return self.url
        if self.media_reference is not None and self.media_reference.url:
            return self.media_reference.url
        return _url_from_storage(self, storage, expires_in)

    async def aget_url(
        self, storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None, *, expires_in: Optional[int] = None
    ) -> Optional[str]:
        """Async variant of :meth:`get_url`."""
        if self.url:
            return self.url
        if self.media_reference is not None and self.media_reference.url:
            return self.media_reference.url
        return await _aurl_from_storage(self, storage, expires_in)

    def _normalise_content(self) -> Optional[Union[str, bytes]]:
        if self.content is None:
            return None
        content_normalised: Union[str, bytes] = self.content
        if content_normalised and isinstance(content_normalised, bytes):
            from base64 import b64encode

            try:
                if self.mime_type and self.mime_type.startswith("text/"):
                    content_normalised = content_normalised.decode("utf-8")
                else:
                    content_normalised = b64encode(content_normalised).decode("utf-8")
            except UnicodeDecodeError:
                if isinstance(self.content, bytes):
                    content_normalised = b64encode(self.content).decode("utf-8")
            except Exception:
                try:
                    if isinstance(self.content, bytes):
                        content_normalised = b64encode(self.content).decode("utf-8")
                except Exception:
                    pass
        return content_normalised

    def to_dict(self, include_base64_content: bool = True) -> Dict[str, Any]:
        """Convert to dict, optionally including base64-encoded content"""
        response_dict: Dict[str, Any] = {
            "id": self.id,
            "url": self.url,
            "filepath": str(self.filepath) if self.filepath else None,
            "mime_type": self.mime_type,
            "file_type": self.file_type,
            "filename": self.filename,
            "size": self.size,
            "external": self.external,
            "format": self.format,
            "name": self.name,
        }

        if self.media_reference is not None:
            response_dict["media_reference"] = self.media_reference.to_dict()
        elif include_base64_content:
            content_normalised = self._normalise_content()
            if content_normalised is not None:
                response_dict["content"] = content_normalised

        if self.metadata:
            response_dict["metadata"] = self.metadata

        return {k: v for k, v in response_dict.items() if v is not None}
