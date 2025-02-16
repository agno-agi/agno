from pathlib import Path
from typing import Any, Dict, Optional, Union

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
    format: Optional[str] = None  # E.g. `mp4`, `mov`, `avi`, `mkv`, `webm`, `flv`, `mpeg`, `mpg`, `wmv`, `three_gp`

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

    def to_dict(self) -> Dict[str, Any]:
        import base64

        return {
            "content": base64.b64encode(self.content).decode("utf-8")
            if isinstance(self.content, bytes)
            else self.content,
            "filepath": self.filepath,
            "format": self.format,
        }


class Audio(BaseModel):
    content: Optional[Any] = None  # Actual audio bytes content
    filepath: Optional[Union[Path, str]] = None  # Absolute local location for audio
    url: Optional[str] = None  # Remote location for audio
    format: Optional[str] = None

    @model_validator(mode="before")
    def validate_exclusive_audio(cls, data: Any):
        """
        Ensure that exactly one of `filepath`, or `content` is provided.
        """
        # Extract the values from the input data
        filepath = data.get("filepath")
        content = data.get("content")
        url = data.get("url")

        # Count how many fields are set (not None)
        count = len([field for field in [filepath, content, url] if field is not None])

        if count == 0:
            raise ValueError("One of `filepath` or `content` or `url` must be provided.")
        elif count > 1:
            raise ValueError("Only one of `filepath` or `content` or `url` should be provided.")

        return data

    @property
    def audio_url_content(self) -> Optional[bytes]:
        import httpx

        if self.url:
            return httpx.get(self.url).content
        else:
            return None

    def to_dict(self) -> Dict[str, Any]:
        import base64

        return {
            "content": base64.b64encode(self.content).decode("utf-8")
            if isinstance(self.content, bytes)
            else self.content,
            "filepath": self.filepath,
            "format": self.format,
        }


class AudioOutput(BaseModel):
    id: str
    content: str  # Base64 encoded
    expires_at: int
    transcript: str

    def to_dict(self) -> Dict[str, Any]:
        import base64

        return {
            "id": self.id,
            "content": base64.b64encode(self.content).decode("utf-8")
            if isinstance(self.content, bytes)
            else self.content,
            "expires_at": self.expires_at,
            "transcript": self.transcript,
        }

class AudioPlayer:
    """
    A class for playing audio.
    """

    def __init__(self, sample_rate=24000):
        try:
            import sounddevice as sd
            import numpy as np
            import threading
        except ImportError:
            raise ImportError("sounddevice, numpy, threading, and base64 are required for AudioPlayer. Please install using `pip install sounddevice numpy threading`")

        self.sample_rate = sample_rate
        self.queue = []
        self.lock = threading.Lock()

        # Create output stream with callback
        self.stream = sd.OutputStream(
            callback=self.callback,
            samplerate=sample_rate,
            channels=1,
            dtype=np.int16,
            blocksize=int(0.05 * sample_rate),  # 50ms chunks
        )
        self.playing = False

        self.np = np

    def callback(self, outdata, frames, time, status):
        """Callback function for the output stream"""
        np = self.np
        with self.lock:
            # Initialize empty data array
            data = np.empty(0, dtype=np.int16)

            # Get data from queue
            while len(data) < frames and len(self.queue) > 0:
                chunk = self.queue.pop(0)
                frames_needed = frames - len(data)
                data = np.concatenate((data, chunk[:frames_needed]))
                if len(chunk) > frames_needed:
                    # Put remaining data back in queue
                    self.queue.insert(0, chunk[frames_needed:])

            # Fill remaining space with silence if needed
            if len(data) < frames:
                data = np.concatenate((data, np.zeros(frames - len(data), dtype=np.int16)))

            # Reshape and set output
            outdata[:] = data.reshape(-1, 1)

    def play(self, audio_string):
        """Play base64 encoded audio data"""
        import base64
        np = self.np
        try:
            # Decode base64 string to bytes
            audio_bytes = base64.b64decode(audio_string)

            # Convert to numpy array
            audio_data = np.frombuffer(audio_bytes, dtype=np.int16)

            # Add to queue
            with self.lock:
                self.queue.append(audio_data)

            # Start playback if not already playing
            if not self.playing:
                self.stream.start()
                self.playing = True

        except Exception as e:
            print(f"Error playing audio: {e}")

    def stop(self):
        """Stop playback and clear queue"""
        self.stream.stop()
        self.playing = False
        with self.lock:
            self.queue = []

    def close(self):
        """Clean up resources"""
        self.stop()
        self.stream.close()

class Image(BaseModel):
    url: Optional[str] = None  # Remote location for image
    filepath: Optional[Union[Path, str]] = None  # Absolute local location for image
    content: Optional[Any] = None  # Actual image bytes content
    format: Optional[str] = None  # E.g. `png`, `jpeg`, `webp`, `gif`
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

    def to_dict(self) -> Dict[str, Any]:
        import base64

        return {
            "content": base64.b64encode(self.content).decode("utf-8")
            if isinstance(self.content, bytes)
            else self.content,
            "filepath": self.filepath,
            "url": self.url,
            "detail": self.detail,
        }
