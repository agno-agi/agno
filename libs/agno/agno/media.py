from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from pydantic import BaseModel, field_validator, model_validator


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

    @model_validator(mode="before")
    def validate_and_normalize_content(cls, data: Any):
        """Ensure exactly one content source and normalize to bytes"""
        if isinstance(data, dict):
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

    def get_content_bytes(self) -> Optional[bytes]:
        """Get image content as raw bytes, loading from URL/file if needed"""
        if self.content:
            return self.content
        elif self.url:
            import httpx

            return httpx.get(self.url).content
        elif self.filepath:
            with open(self.filepath, "rb") as f:
                return f.read()
        return None

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
        result = {
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

        if include_base64_content and self.content:
            result["content"] = self.to_base64()

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

    @model_validator(mode="before")
    def validate_and_normalize_content(cls, data: Any):
        """Ensure exactly one content source and normalize to bytes"""
        if isinstance(data, dict):
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

    def get_content_bytes(self) -> Optional[bytes]:
        """Get audio content as raw bytes"""
        if self.content:
            return self.content
        elif self.url:
            import httpx

            return httpx.get(self.url).content
        elif self.filepath:
            with open(self.filepath, "rb") as f:
                return f.read()
        return None

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
        result = {
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

        if include_base64_content and self.content:
            result["content"] = self.to_base64()

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

    @model_validator(mode="before")
    def validate_and_normalize_content(cls, data: Any):
        """Ensure exactly one content source and normalize to bytes"""
        if isinstance(data, dict):
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

    def get_content_bytes(self) -> Optional[bytes]:
        """Get video content as raw bytes"""
        if self.content:
            return self.content
        elif self.url:
            import httpx

            return httpx.get(self.url).content
        elif self.filepath:
            with open(self.filepath, "rb") as f:
                return f.read()
        return None

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
        result = {
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

        if include_base64_content and self.content:
            result["content"] = self.to_base64()

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

    @model_validator(mode="before")
    @classmethod
    def check_at_least_one_source(cls, data):
        """Ensure at least one of url, filepath, or content is provided."""
        if isinstance(data, dict) and not any(data.get(field) for field in ["url", "filepath", "content", "external"]):
            raise ValueError("At least one of url, filepath, content or external must be provided")
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
        return [
            "application/pdf",
            "application/json",
            "application/x-javascript",
            "application/json",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/javascript",
            "application/x-python",
            "text/x-python",
            "text/plain",
            "text/html",
            "text/css",
            "text/md",
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
        """Create File from base64 encoded content"""
        import base64

        content_bytes = base64.b64decode(base64_content)
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
        import httpx

        if self.url:
            response = httpx.get(self.url)
            content = response.content
            mime_type = response.headers.get("Content-Type", "").split(";")[0]
            return content, mime_type
        else:
            return None

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

    def to_dict(self) -> Dict[str, Any]:
        content_normalised = self._normalise_content()

        response_dict = {
            "id": self.id,
            "url": self.url,
            "filepath": str(self.filepath) if self.filepath else None,
            "content": content_normalised,
            "mime_type": self.mime_type,
            "file_type": self.file_type,
            "filename": self.filename,
            "size": self.size,
            "external": self.external,
            "format": self.format,
            "name": self.name,
        }
        return {k: v for k, v in response_dict.items() if v is not None}
