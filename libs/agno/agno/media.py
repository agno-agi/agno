from pathlib import Path
from typing import Any, Optional, Union

from pydantic import BaseModel, model_validator


class Media(BaseModel):
    id: str
    original_prompt: Optional[str] = None
    revised_prompt: Optional[str] = None


class VideoArtifact(Media):
    url: str  # Remote location for file
    eta: Optional[str] = None
    length: Optional[str] = None


class ImageArtifact(Media):
    url: str  # Remote location for file
    alt_text: Optional[str] = None


class AudioArtifact(Media):
    url: Optional[str] = None  # Remote location for file
    base64_audio: Optional[str] = None  # Base64-encoded audio data
    length: Optional[str] = None
    mime_type: Optional[str] = None

    @model_validator(mode="before")
    def validate_exclusive_audio(cls, data: Any):
        """
        Ensure that either `url` or `base64_audio` is provided, but not both.
        """
        if data.get("url") and data.get("base64_audio"):
            raise ValueError("Provide either `url` or `base64_audio`, not both.")
        if not data.get("url") and not data.get("base64_audio"):
            raise ValueError("Either `url` or `base64_audio` must be provided.")
        return data


class Video(BaseModel):
    filepath: Optional[Union[Path, str]] = None  # Absolute local location for video
    content: Optional[Any] = None  # Actual video bytes content

    @model_validator(mode="before")
    def validate_exclusive_video(cls, data: Any):
        """
        Ensure that exactly one of `filepath`, or `content` is provided.
        """
        # Extract the values from the input data
        filepath = data.get("filepath")
        content = data.get("content")

        # Count how many fields are set (not None)
        count = len([field for field in [filepath, content] if field is not None])

        if count == 0:
            raise ValueError("One of `filepath` or `content` must be provided.")
        elif count > 1:
            raise ValueError("Only one of `filepath` or `content` should be provided.")

        return data


class Audio(BaseModel):
    content: Optional[Any] = None  # Actual audio bytes content
    filepath: Optional[Union[Path, str]] = None  # Absolute local location for audio
    format: Optional[str] = None

    @model_validator(mode="before")
    def validate_exclusive_audio(cls, data: Any):
        """
        Ensure that exactly one of `filepath`, or `content` is provided.
        """
        # Extract the values from the input data
        filepath = data.get("filepath")
        content = data.get("content")

        # Count how many fields are set (not None)
        count = len([field for field in [filepath, content] if field is not None])

        if count == 0:
            raise ValueError("One of `filepath` or `content` must be provided.")
        elif count > 1:
            raise ValueError("Only one of `filepath` or `content` should be provided.")

        return data


class AudioOutput(BaseModel):
    id: str
    content: str  # Base64 encoded
    expires_at: int
    transcript: str


class Image(BaseModel):
    url: Optional[str] = None  # Remote location for image
    filepath: Optional[Union[Path, str]] = None  # Absolute local location for image
    content: Optional[Any] = None  # Actual image bytes content
    detail: Optional[str] = (
        None  # low, medium, high or auto (per OpenAI spec https://platform.openai.com/docs/guides/vision?lang=node#low-or-high-fidelity-image-understanding)
    )
    id: Optional[str] = None

    @property
    def image_url_content(self) -> Optional[bytes]:
        import httpx

        if self.url:
            return httpx.get(self.url).content
        else:
            return None

    @model_validator(mode="before")
    def validate_exclusive_image(cls, data: Any):
        """
        Ensure that exactly one of `url`, `filepath`, or `content` is provided.
        """
        # Extract the values from the input data
        url = data.get("url")
        filepath = data.get("filepath")
        content = data.get("content")

        # Count how many fields are set (not None)
        count = len([field for field in [url, filepath, content] if field is not None])

        if count == 0:
            raise ValueError("One of `url`, `filepath`, or `content` must be provided.")
        elif count > 1:
            raise ValueError("Only one of `url`, `filepath`, or `content` should be provided.")

        return data
