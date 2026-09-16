import time
from os import getenv
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from agno.media import Audio, Image, Video
from agno.models.aimlapi.constants import AIMLAPI_HEADERS
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_debug, log_error, log_warning

DEFAULT_BASE_URL = "https://api.aimlapi.com"
# The attribution headers mean something only on this host, so a proxy or a
# self-hosted mirror in front of the API is sent none of them.
AIMLAPI_HOST = "api.aimlapi.com"

_VIDEO_TERMINAL = {"completed", "error"}
_TRANSCRIPTION_TERMINAL = {"completed", "error"}


class AIMLAPITools(Toolkit):
    """Tools for the media endpoints of AI/ML API (https://aimlapi.com).

    One key gives an agent image, video, speech and transcription models from
    many vendors behind one endpoint. Each capability is a separate tool with
    its own model, so an agent can be given only the ones it needs.

    Args:
        api_key (str, optional): AI/ML API key. Read from AIMLAPI_API_KEY if not provided.
        base_url (str): API root. Default is "https://api.aimlapi.com".
        enable_generate_image (bool): Register generate_image. Default is True.
        enable_generate_video (bool): Register generate_video. Default is True.
        enable_generate_speech (bool): Register generate_speech. Default is True.
        enable_transcribe_audio (bool): Register transcribe_audio. Default is True.
        all (bool): Register every tool, overriding the individual flags. Default is False.
        image_model (str): Image model id. Default is "openai/gpt-image-2".
        image_size (str, optional): "WIDTHxHEIGHT" when the model takes one.
        image_quality (str, optional): Quality preset when the model takes one.
        video_model (str): Video model id. Default is "bytedance/seedance-2-5".
        video_duration (int, optional): Clip length in seconds when the model takes one.
        video_resolution (str, optional): E.g. "720p" when the model takes one.
        video_aspect_ratio (str, optional): E.g. "16:9" when the model takes one.
        video_poll_interval (float): Seconds between status checks. Default is 5.
        video_timeout (float): Seconds to wait for a video before giving up. Default is 900.
        speech_model (str): Text-to-speech model id. Default is "openai/tts-1".
        speech_voice (str, optional): Voice name when the model takes one. Default is "alloy".
        speech_format (str): Output container: mp3, opus, aac, flac, wav or pcm. Default is "mp3".
        speech_speed (float, optional): Playback speed multiplier when the model takes one.
        transcription_model (str): Speech-to-text model id. Default is "deepgram/nova-3".
        transcription_language (str, optional): Language hint when the model takes one.
        transcription_poll_interval (float): Seconds between status checks. Default is 2.
        transcription_timeout (float): Seconds to wait for a transcript. Default is 300.
        request_timeout (float): Seconds allowed for one HTTP call. Default is 120.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        enable_generate_image: bool = True,
        enable_generate_video: bool = True,
        enable_generate_speech: bool = True,
        enable_transcribe_audio: bool = True,
        all: bool = False,
        image_model: str = "openai/gpt-image-2",
        image_size: Optional[str] = None,
        image_quality: Optional[str] = None,
        video_model: str = "bytedance/seedance-2-5",
        video_duration: Optional[int] = None,
        video_resolution: Optional[str] = None,
        video_aspect_ratio: Optional[str] = None,
        video_poll_interval: float = 5.0,
        video_timeout: float = 900.0,
        speech_model: str = "openai/tts-1",
        speech_voice: Optional[str] = "alloy",
        speech_format: str = "mp3",
        speech_speed: Optional[float] = None,
        transcription_model: str = "deepgram/nova-3",
        transcription_language: Optional[str] = None,
        transcription_poll_interval: float = 2.0,
        transcription_timeout: float = 300.0,
        request_timeout: float = 120.0,
        **kwargs,
    ):
        self.api_key = api_key or getenv("AIMLAPI_API_KEY")
        if not self.api_key:
            raise ValueError("AIMLAPI_API_KEY not set. Please set the AIMLAPI_API_KEY environment variable.")

        self.base_url = base_url.rstrip("/")
        self.image_model = image_model
        self.image_size = image_size
        self.image_quality = image_quality
        self.video_model = video_model
        self.video_duration = video_duration
        self.video_resolution = video_resolution
        self.video_aspect_ratio = video_aspect_ratio
        self.video_poll_interval = video_poll_interval
        self.video_timeout = video_timeout
        self.speech_model = speech_model
        self.speech_voice = speech_voice
        self.speech_format = speech_format
        self.speech_speed = speech_speed
        self.transcription_model = transcription_model
        self.transcription_language = transcription_language
        self.transcription_poll_interval = transcription_poll_interval
        self.transcription_timeout = transcription_timeout
        self.request_timeout = request_timeout

        tools: List[Any] = []
        if all or enable_generate_image:
            tools.append(self.generate_image)
        if all or enable_generate_video:
            tools.append(self.generate_video)
        if all or enable_generate_speech:
            tools.append(self.generate_speech)
        if all or enable_transcribe_audio:
            tools.append(self.transcribe_audio)

        super().__init__(name="aimlapi_tools", tools=tools, **kwargs)

    # --- HTTP ---------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if urlsplit(self.base_url).hostname == AIMLAPI_HOST:
            headers.update(AIMLAPI_HEADERS)
        return headers

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        response = httpx.post(
            f"{self.base_url}{path}", json=body, headers=self._headers(), timeout=self.request_timeout
        )
        return self._json(response)

    def _post_multipart(self, path: str, data: Dict[str, Any], files: Dict[str, Any]) -> Dict[str, Any]:
        response = httpx.post(
            f"{self.base_url}{path}", data=data, files=files, headers=self._headers(), timeout=self.request_timeout
        )
        return self._json(response)

    def _get(self, path: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        response = httpx.get(
            f"{self.base_url}{path}", params=params, headers=self._headers(), timeout=self.request_timeout
        )
        return self._json(response)

    @staticmethod
    def _json(response: httpx.Response) -> Dict[str, Any]:
        if response.status_code >= 400:
            message = response.text[:300]
            try:
                detail = response.json()
                message = detail.get("message") or detail.get("error", {}).get("message") or message
            except Exception:
                pass
            raise RuntimeError(f"AI/ML API returned HTTP {response.status_code}: {message}")
        return response.json()

    def _download(self, url: str, expected_prefix: str) -> tuple[bytes, str]:
        """Fetch a generated asset from the CDN. The asset link is public, so no key is sent."""
        response = httpx.get(url, follow_redirects=True, timeout=self.request_timeout)
        response.raise_for_status()
        mime_type = response.headers.get("content-type", "").split(";")[0].strip()
        if not mime_type.startswith(expected_prefix):
            raise RuntimeError(
                f"AI/ML API returned {mime_type or 'an untyped asset'} where {expected_prefix}* was expected"
            )
        return response.content, mime_type

    @staticmethod
    def _asset_url(value: Any) -> Optional[str]:
        """Generated assets arrive as {"url": ...}, [{"url": ...}] or a bare string."""
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, dict):
            value = value.get("url")
        return value if isinstance(value, str) and value else None

    # --- Tools --------------------------------------------------------------

    def generate_image(self, prompt: str) -> ToolResult:
        """Generate an image from a text prompt.

        Args:
            prompt (str): What the image should show.
        """
        body: Dict[str, Any] = {"model": self.image_model, "prompt": prompt}
        if self.image_size:
            body["size"] = self.image_size
        if self.image_quality:
            body["quality"] = self.image_quality
        try:
            payload = self._post("/v1/images/generations", body)
            images: List[Image] = []
            for item in payload.get("data") or []:
                url = self._asset_url(item)
                if url is None:
                    continue
                content, mime_type = self._download(url, "image/")
                images.append(Image(id=str(uuid4()), content=content, mime_type=mime_type, original_prompt=prompt))
            if not images:
                log_warning("AI/ML API returned no image data.")
                return ToolResult(content="Failed to generate image: No image data received from API.")
            log_debug(f"Generated {len(images)} image(s) with {self.image_model}")
            return ToolResult(content="Image generated successfully.", images=images)
        except Exception as e:
            log_error(f"Failed to generate image using {self.image_model}: {e}")
            return ToolResult(content=f"Failed to generate image: {e}")

    def generate_video(self, prompt: str) -> ToolResult:
        """Generate a short video from a text prompt. Takes a minute or more.

        Args:
            prompt (str): The scene, subject or action to show.
        """
        body: Dict[str, Any] = {"model": self.video_model, "prompt": prompt}
        if self.video_duration is not None:
            body["duration"] = self.video_duration
        if self.video_resolution:
            body["resolution"] = self.video_resolution
        if self.video_aspect_ratio:
            body["aspect_ratio"] = self.video_aspect_ratio
        try:
            job = self._post("/v2/video/generations", body)
            job_id = job.get("id")
            if not job_id:
                return ToolResult(content="Failed to generate video: API did not return a generation id.")
            deadline = time.monotonic() + self.video_timeout
            while job.get("status") not in _VIDEO_TERMINAL:
                if time.monotonic() > deadline:
                    return ToolResult(
                        content=f"Failed to generate video: still {job.get('status')} after {self.video_timeout:.0f}s."
                    )
                time.sleep(self.video_poll_interval)
                job = self._get("/v2/video/generations", {"generation_id": job_id})
            if job.get("status") == "error":
                error = job.get("error") or {}
                message = error.get("message") if isinstance(error, dict) else str(error)
                return ToolResult(content=f"Failed to generate video: {message or 'generation failed'}")
            url = self._asset_url(job.get("video"))
            if url is None:
                return ToolResult(content="Failed to generate video: No video data received from API.")
            content, mime_type = self._download(url, "video/")
            video = Video(id=str(uuid4()), content=content, mime_type=mime_type, original_prompt=prompt)
            log_debug(f"Generated video {video.id} with {self.video_model}")
            return ToolResult(content="Video generated successfully.", videos=[video])
        except Exception as e:
            log_error(f"Failed to generate video using {self.video_model}: {e}")
            return ToolResult(content=f"Failed to generate video: {e}")

    def generate_speech(self, text_input: str) -> ToolResult:
        """Turn text into spoken audio.

        Args:
            text_input (str): The text to read aloud.
        """
        body: Dict[str, Any] = {
            "model": self.speech_model,
            "text": text_input,
            "response_format": self.speech_format,
        }
        if self.speech_voice:
            body["voice"] = self.speech_voice
        if self.speech_speed is not None:
            body["speed"] = self.speech_speed
        try:
            payload = self._post("/v1/tts", body)
            url = self._asset_url(payload.get("audio"))
            if url is None:
                return ToolResult(content="Failed to generate speech: No audio data received from API.")
            content, mime_type = self._download(url, "audio/")
            audio = Audio(id=str(uuid4()), content=content, mime_type=mime_type)
            return ToolResult(content=f"Speech generated successfully with ID: {audio.id}", audios=[audio])
        except Exception as e:
            log_error(f"Failed to generate speech using {self.speech_model}: {e}")
            return ToolResult(content=f"Failed to generate speech: {e}")

    def transcribe_audio(self, audio_path: str) -> str:
        """Transcribe an audio file to text.

        Args:
            audio_path (str): Path to a local audio file, or an https URL of one.
        """
        data: Dict[str, Any] = {"model": self.transcription_model}
        if self.transcription_language:
            data["language"] = self.transcription_language
        try:
            if audio_path.startswith(("http://", "https://")):
                job = self._post("/v1/stt/create", {**data, "url": audio_path})
            else:
                path = Path(audio_path)
                with path.open("rb") as audio_file:
                    job = self._post_multipart("/v1/stt/create", data, {"audio": (path.name, audio_file)})
            job_id = job.get("generation_id")
            if not job_id:
                return "Failed to transcribe audio: API did not return a generation id."
            deadline = time.monotonic() + self.transcription_timeout
            while job.get("status") not in _TRANSCRIPTION_TERMINAL:
                if time.monotonic() > deadline:
                    return f"Failed to transcribe audio: still {job.get('status')} after {self.transcription_timeout:.0f}s."
                time.sleep(self.transcription_poll_interval)
                job = self._get(f"/v1/stt/{job_id}")
            if job.get("status") == "error":
                error = job.get("error") or {}
                message = error.get("message") if isinstance(error, dict) else str(error)
                return f"Failed to transcribe audio: {message or 'transcription failed'}"
            transcript = self._transcript(job.get("result") or {})
            if transcript is None:
                return "Failed to transcribe audio: No transcript received from API."
            log_debug(f"Transcript: {transcript}")
            return transcript
        except Exception as e:
            log_error(f"Failed to transcribe audio using {self.transcription_model}: {e}")
            return f"Failed to transcribe audio: {e}"

    @staticmethod
    def _transcript(result: Dict[str, Any]) -> Optional[str]:
        """The transcript out of a completed job. Providers differ in where they put it."""
        text = result.get("text") or result.get("transcript")
        if isinstance(text, str):
            return text
        channels = (result.get("results") or {}).get("channels") or []
        for channel in channels:
            for alternative in channel.get("alternatives") or []:
                transcript = alternative.get("transcript")
                if isinstance(transcript, str):
                    return transcript
        return None
