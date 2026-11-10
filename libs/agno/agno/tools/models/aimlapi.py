import asyncio
import mimetypes
import re
import time
from os import getenv
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union
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

SPEECH_FORMATS = ("mp3", "opus", "aac", "flac", "wav", "pcm")

# Statuses a job reports while it is still running. Anything outside this set is
# terminal: "completed" carries the result, "error"/"failed" carry a message, and
# an unknown status stops the loop instead of spinning until the timeout.
# Measured on the gateway 2026-09-23 across six transcription models: only
# queued, generating, completed and failed appear. "waiting" is kept because the
# Nova-3 docs example still tests for it, and treating it as in-progress can only
# ever mean one more poll.
_IN_PROGRESS = frozenset(
    {"queued", "generating", "processing", "pending", "running", "in_progress", "active", "waiting"}
)
# Deepgram-backed jobs report "error"; AssemblyAI-backed ones report "failed".
_FAILED = frozenset({"error", "failed"})
_TRANSIENT_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
_MAX_TRANSIENT_RETRIES = 3


class AIMLAPIError(RuntimeError):
    """The gateway answered with an error status."""

    def __init__(self, status_code: int, message: str):
        super().__init__(f"AI/ML API returned HTTP {status_code}: {message}")
        self.status_code = status_code


class AIMLAPITools(Toolkit):
    """Tools for the media endpoints of AI/ML API (https://aimlapi.com).

    One key gives an agent image, video, speech and transcription models from
    many vendors behind one endpoint. Each capability is a separate tool with
    its own model, so an agent can be given only the ones it needs. Every tool
    has an async variant, so the long-running video and transcription jobs do
    not block the event loop under ``arun``.

    Args:
        api_key (str, optional): AI/ML API key. Read from AIMLAPI_API_KEY if not provided.
        base_url (str): API root. Default is "https://api.aimlapi.com". A trailing "/v1"
            (the form the AIMLAPI chat model uses) is accepted and stripped.
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
        base_dir (Path or str, optional): Directory local audio files for transcription are
            read from. Default is the current working directory.
        restrict_to_base_dir (bool): Refuse local paths that resolve outside base_dir, so a
            prompt cannot make the agent upload an arbitrary file. Default is True.
        timeout (int): Seconds allowed for one HTTP call. Default is 120.
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
        base_dir: Optional[Union[Path, str]] = None,
        restrict_to_base_dir: bool = True,
        timeout: int = 120,
        **kwargs,
    ):
        self.api_key = api_key or getenv("AIMLAPI_API_KEY")
        if not self.api_key:
            raise ValueError("AIMLAPI_API_KEY not set. Please set the AIMLAPI_API_KEY environment variable.")
        if speech_format not in SPEECH_FORMATS:
            raise ValueError(f"speech_format must be one of {', '.join(SPEECH_FORMATS)}, got {speech_format!r}")

        # The chat model's base URL ends in /v1; this toolkit addresses both
        # /v1 and /v2 routes, so it wants the bare root.
        self.base_url = re.sub(r"/v\d+/?$", "", base_url.rstrip("/"))
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
        self.base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
        self.restrict_to_base_dir = restrict_to_base_dir
        self.request_timeout = timeout

        tools: List[Any] = []
        async_tools: List[Tuple[Callable[..., Any], str]] = []
        if all or enable_generate_image:
            tools.append(self.generate_image)
            async_tools.append((self.agenerate_image, "generate_image"))
        if all or enable_generate_video:
            tools.append(self.generate_video)
            async_tools.append((self.agenerate_video, "generate_video"))
        if all or enable_generate_speech:
            tools.append(self.generate_speech)
            async_tools.append((self.agenerate_speech, "generate_speech"))
        if all or enable_transcribe_audio:
            tools.append(self.transcribe_audio)
            async_tools.append((self.atranscribe_audio, "transcribe_audio"))

        super().__init__(name="aimlapi_tools", tools=tools, async_tools=async_tools, timeout=timeout, **kwargs)

    # --- HTTP ---------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if urlsplit(self.base_url).hostname == AIMLAPI_HOST:
            headers.update(AIMLAPI_HEADERS)
        return headers

    @staticmethod
    def _json(response: httpx.Response) -> Dict[str, Any]:
        if response.status_code >= 400:
            raise AIMLAPIError(response.status_code, _error_message(response))
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("AI/ML API returned a non-object JSON body")
        return body

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        response = httpx.post(
            f"{self.base_url}{path}", json=body, headers=self._headers(), timeout=self.request_timeout
        )
        return self._json(response)

    def _post_file(self, path: str, data: Dict[str, Any], file: Path) -> Dict[str, Any]:
        with file.open("rb") as handle:
            response = httpx.post(
                f"{self.base_url}{path}",
                data=data,
                files={"audio": (file.name, handle)},
                headers=self._headers(),
                timeout=self.request_timeout,
            )
        return self._json(response)

    def _get(self, path: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        response = httpx.get(
            f"{self.base_url}{path}", params=params, headers=self._headers(), timeout=self.request_timeout
        )
        return self._json(response)

    def _download(self, url: str) -> Tuple[bytes, str]:
        """Fetch a generated asset. The link is public, so no key travels with it."""
        parsed = urlsplit(url)
        if parsed.scheme != "https":
            raise RuntimeError("AI/ML API returned a non-HTTPS asset URL")
        response = httpx.get(url, follow_redirects=True, timeout=self.request_timeout)
        response.raise_for_status()
        return response.content, _asset_mime_type(response.headers.get("content-type"), url)

    async def _apost(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            response = await client.post(f"{self.base_url}{path}", json=body, headers=self._headers())
        return self._json(response)

    async def _apost_file(self, path: str, data: Dict[str, Any], file: Path) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            with file.open("rb") as handle:
                response = await client.post(
                    f"{self.base_url}{path}", data=data, files={"audio": (file.name, handle)}, headers=self._headers()
                )
        return self._json(response)

    async def _aget(self, path: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            response = await client.get(f"{self.base_url}{path}", params=params, headers=self._headers())
        return self._json(response)

    async def _adownload(self, url: str) -> Tuple[bytes, str]:
        parsed = urlsplit(url)
        if parsed.scheme != "https":
            raise RuntimeError("AI/ML API returned a non-HTTPS asset URL")
        async with httpx.AsyncClient(timeout=self.request_timeout, follow_redirects=True) as client:
            response = await client.get(url)
        response.raise_for_status()
        return response.content, _asset_mime_type(response.headers.get("content-type"), url)

    # --- polling ------------------------------------------------------------

    def _poll(self, fetch: Callable[[], Dict[str, Any]], interval: float, timeout: float, what: str) -> Dict[str, Any]:
        """Poll a job until it leaves the in-progress statuses.

        A transient gateway or network error during a poll does not abandon the
        job, which keeps running (and billing) on the other side: the poll is
        retried a few times before giving up.
        """
        deadline = time.monotonic() + timeout
        failures = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"{what} still running after {timeout:.0f}s")
            time.sleep(min(interval, remaining))
            try:
                job = fetch()
            except (AIMLAPIError, httpx.TransportError) as e:
                if not _is_transient(e) or failures >= _MAX_TRANSIENT_RETRIES:
                    raise
                failures += 1
                log_warning(f"{what}: poll failed ({e}); retry {failures}/{_MAX_TRANSIENT_RETRIES}")
                continue
            failures = 0
            if job.get("status") not in _IN_PROGRESS:
                return job

    async def _apoll(
        self, fetch: Callable[[], Awaitable[Dict[str, Any]]], interval: float, timeout: float, what: str
    ) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout
        failures = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"{what} still running after {timeout:.0f}s")
            await asyncio.sleep(min(interval, remaining))
            try:
                job = await fetch()
            except (AIMLAPIError, httpx.TransportError) as e:
                if not _is_transient(e) or failures >= _MAX_TRANSIENT_RETRIES:
                    raise
                failures += 1
                log_warning(f"{what}: poll failed ({e}); retry {failures}/{_MAX_TRANSIENT_RETRIES}")
                continue
            failures = 0
            if job.get("status") not in _IN_PROGRESS:
                return job

    # --- request and response shapes ----------------------------------------

    def _image_body(self, prompt: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"model": self.image_model, "prompt": prompt}
        if self.image_size:
            body["size"] = self.image_size
        if self.image_quality:
            body["quality"] = self.image_quality
        return body

    def _video_body(self, prompt: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"model": self.video_model, "prompt": prompt}
        if self.video_duration is not None:
            body["duration"] = self.video_duration
        if self.video_resolution:
            body["resolution"] = self.video_resolution
        if self.video_aspect_ratio:
            body["aspect_ratio"] = self.video_aspect_ratio
        return body

    def _speech_body(self, text_input: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"model": self.speech_model, "text": text_input, "response_format": self.speech_format}
        if self.speech_voice:
            body["voice"] = self.speech_voice
        if self.speech_speed is not None:
            body["speed"] = self.speech_speed
        return body

    def _transcription_data(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"model": self.transcription_model}
        if self.transcription_language:
            data["language"] = self.transcription_language
        return data

    def _local_audio(self, audio_path: str) -> Path:
        """Resolve a local path inside base_dir; the model must not pick arbitrary files."""
        safe, resolved = self._check_path(audio_path, self.base_dir, self.restrict_to_base_dir)
        if not safe:
            raise PermissionError(f"{audio_path} is outside the allowed directory {self.base_dir}")
        if not resolved.is_file():
            raise FileNotFoundError(f"{audio_path} is not a file")
        return resolved

    @staticmethod
    def _image_result(prompt: str, assets: List[Tuple[bytes, str]]) -> ToolResult:
        if not assets:
            log_warning("AI/ML API returned no image data.")
            return ToolResult(content="Failed to generate image: No image data received from API.")
        images = [
            Image(
                id=str(uuid4()),
                content=content,
                mime_type=mime_type,
                format=_subtype(mime_type),
                original_prompt=prompt,
            )
            for content, mime_type in assets
        ]
        log_debug(f"Generated {len(images)} image(s)")
        return ToolResult(content="Image generated successfully.", images=images)

    @staticmethod
    def _video_result(prompt: str, content: bytes, mime_type: str) -> ToolResult:
        video = Video(
            id=str(uuid4()), content=content, mime_type=mime_type, format=_subtype(mime_type), original_prompt=prompt
        )
        log_debug(f"Generated video {video.id} ({len(content)} bytes)")
        return ToolResult(content="Video generated successfully.", videos=[video])

    def _speech_result(self, content: bytes, mime_type: str) -> ToolResult:
        audio = Audio(id=str(uuid4()), content=content, mime_type=mime_type, format=self.speech_format)
        return ToolResult(content=f"Speech generated successfully with ID: {audio.id}", audios=[audio])

    @staticmethod
    def _job_failure(job: Dict[str, Any], what: str) -> Optional[str]:
        """A message when a finished job did not succeed, else None."""
        status = job.get("status")
        if status == "completed":
            return None
        if status in _FAILED:
            return f"Failed to {what}: {_error_text(job.get('error')) or 'generation failed'}"
        return f"Failed to {what}: job ended with status {status!r}"

    @staticmethod
    def _transcript(job: Dict[str, Any]) -> Optional[str]:
        """The transcript out of a completed job. Providers differ in where they put it."""
        result = job.get("result")
        if not isinstance(result, dict):
            return None
        for key in ("text", "transcript"):
            if isinstance(result.get(key), str):
                return result[key]
        results = result.get("results")
        channels = results.get("channels") if isinstance(results, dict) else None
        for channel in channels or []:
            if not isinstance(channel, dict):
                continue
            for alternative in channel.get("alternatives") or []:
                if isinstance(alternative, dict) and isinstance(alternative.get("transcript"), str):
                    return alternative["transcript"]
        return None

    # --- tools --------------------------------------------------------------

    def generate_image(self, prompt: str) -> ToolResult:
        """Generate an image from a text prompt.

        Args:
            prompt (str): What the image should show.
        """
        try:
            payload = self._post("/v1/images/generations", self._image_body(prompt))
            assets = [self._download(url) for url in _asset_urls(payload.get("data"))]
            return self._image_result(prompt, assets)
        except Exception as e:
            log_error(f"Failed to generate image using {self.image_model}: {e}")
            return ToolResult(content=f"Failed to generate image: {e}")

    async def agenerate_image(self, prompt: str) -> ToolResult:
        """Generate an image from a text prompt.

        Args:
            prompt (str): What the image should show.
        """
        try:
            payload = await self._apost("/v1/images/generations", self._image_body(prompt))
            assets = [await self._adownload(url) for url in _asset_urls(payload.get("data"))]
            return self._image_result(prompt, assets)
        except Exception as e:
            log_error(f"Failed to generate image using {self.image_model}: {e}")
            return ToolResult(content=f"Failed to generate image: {e}")

    def generate_video(self, prompt: str) -> ToolResult:
        """Generate a short video from a text prompt. Takes a minute or more.

        Args:
            prompt (str): The scene, subject or action to show.
        """
        try:
            job = self._post("/v2/video/generations", self._video_body(prompt))
            job_id = job.get("id")
            if not isinstance(job_id, str) or not job_id:
                return ToolResult(content="Failed to generate video: API did not return a generation id.")
            if job.get("status") in _IN_PROGRESS:
                job = self._poll(
                    lambda: self._get("/v2/video/generations", {"generation_id": job_id}),
                    self.video_poll_interval,
                    self.video_timeout,
                    "video generation",
                )
            failure = self._job_failure(job, "generate video")
            if failure:
                return ToolResult(content=failure)
            url = _asset_url(job.get("video"))
            if url is None:
                return ToolResult(content="Failed to generate video: No video data received from API.")
            content, mime_type = self._download(url)
            return self._video_result(prompt, content, mime_type)
        except Exception as e:
            log_error(f"Failed to generate video using {self.video_model}: {e}")
            return ToolResult(content=f"Failed to generate video: {e}")

    async def agenerate_video(self, prompt: str) -> ToolResult:
        """Generate a short video from a text prompt. Takes a minute or more.

        Args:
            prompt (str): The scene, subject or action to show.
        """
        try:
            job = await self._apost("/v2/video/generations", self._video_body(prompt))
            job_id = job.get("id")
            if not isinstance(job_id, str) or not job_id:
                return ToolResult(content="Failed to generate video: API did not return a generation id.")
            if job.get("status") in _IN_PROGRESS:
                job = await self._apoll(
                    lambda: self._aget("/v2/video/generations", {"generation_id": job_id}),
                    self.video_poll_interval,
                    self.video_timeout,
                    "video generation",
                )
            failure = self._job_failure(job, "generate video")
            if failure:
                return ToolResult(content=failure)
            url = _asset_url(job.get("video"))
            if url is None:
                return ToolResult(content="Failed to generate video: No video data received from API.")
            content, mime_type = await self._adownload(url)
            return self._video_result(prompt, content, mime_type)
        except Exception as e:
            log_error(f"Failed to generate video using {self.video_model}: {e}")
            return ToolResult(content=f"Failed to generate video: {e}")

    def generate_speech(self, text_input: str) -> ToolResult:
        """Turn text into spoken audio.

        Args:
            text_input (str): The text to read aloud.
        """
        try:
            payload = self._post("/v1/tts", self._speech_body(text_input))
            url = _asset_url(payload.get("audio"))
            if url is None:
                return ToolResult(content="Failed to generate speech: No audio data received from API.")
            content, mime_type = self._download(url)
            return self._speech_result(content, mime_type)
        except Exception as e:
            log_error(f"Failed to generate speech using {self.speech_model}: {e}")
            return ToolResult(content=f"Failed to generate speech: {e}")

    async def agenerate_speech(self, text_input: str) -> ToolResult:
        """Turn text into spoken audio.

        Args:
            text_input (str): The text to read aloud.
        """
        try:
            payload = await self._apost("/v1/tts", self._speech_body(text_input))
            url = _asset_url(payload.get("audio"))
            if url is None:
                return ToolResult(content="Failed to generate speech: No audio data received from API.")
            content, mime_type = await self._adownload(url)
            return self._speech_result(content, mime_type)
        except Exception as e:
            log_error(f"Failed to generate speech using {self.speech_model}: {e}")
            return ToolResult(content=f"Failed to generate speech: {e}")

    def transcribe_audio(self, audio_path: str) -> str:
        """Transcribe an audio file to text.

        Args:
            audio_path (str): Path to an audio file inside the toolkit's base directory, or an https URL of one.
        """
        try:
            if audio_path.startswith(("http://", "https://")):
                job = self._post("/v1/stt/create", {**self._transcription_data(), "url": audio_path})
            else:
                job = self._post_file("/v1/stt/create", self._transcription_data(), self._local_audio(audio_path))
            job_id = job.get("generation_id")
            if not isinstance(job_id, str) or not job_id:
                return "Failed to transcribe audio: API did not return a generation id."
            if job.get("status") in _IN_PROGRESS:
                job = self._poll(
                    lambda: self._get(f"/v1/stt/{job_id}"),
                    self.transcription_poll_interval,
                    self.transcription_timeout,
                    "transcription",
                )
            failure = self._job_failure(job, "transcribe audio")
            if failure:
                return failure
            transcript = self._transcript(job)
            if transcript is None:
                return "Failed to transcribe audio: No transcript received from API."
            log_debug(f"Transcribed {len(transcript)} characters")
            return transcript
        except Exception as e:
            log_error(f"Failed to transcribe audio using {self.transcription_model}: {e}")
            return f"Failed to transcribe audio: {e}"

    async def atranscribe_audio(self, audio_path: str) -> str:
        """Transcribe an audio file to text.

        Args:
            audio_path (str): Path to an audio file inside the toolkit's base directory, or an https URL of one.
        """
        try:
            if audio_path.startswith(("http://", "https://")):
                job = await self._apost("/v1/stt/create", {**self._transcription_data(), "url": audio_path})
            else:
                job = await self._apost_file(
                    "/v1/stt/create", self._transcription_data(), self._local_audio(audio_path)
                )
            job_id = job.get("generation_id")
            if not isinstance(job_id, str) or not job_id:
                return "Failed to transcribe audio: API did not return a generation id."
            if job.get("status") in _IN_PROGRESS:
                job = await self._apoll(
                    lambda: self._aget(f"/v1/stt/{job_id}"),
                    self.transcription_poll_interval,
                    self.transcription_timeout,
                    "transcription",
                )
            failure = self._job_failure(job, "transcribe audio")
            if failure:
                return failure
            transcript = self._transcript(job)
            if transcript is None:
                return "Failed to transcribe audio: No transcript received from API."
            log_debug(f"Transcribed {len(transcript)} characters")
            return transcript
        except Exception as e:
            log_error(f"Failed to transcribe audio using {self.transcription_model}: {e}")
            return f"Failed to transcribe audio: {e}"


# --- helpers ------------------------------------------------------------------


def _error_text(error: Any) -> Optional[str]:
    """The human-readable part of an error field, whatever shape it took."""
    if isinstance(error, str):
        return error or None
    if isinstance(error, dict):
        for key in ("message", "detail", "name"):
            if isinstance(error.get(key), str) and error[key]:
                return error[key]
    return None


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        message = body.get("message")
        if isinstance(message, str) and message:
            return message
        nested = _error_text(body.get("error"))
        if nested:
            return nested
    return response.text[:300]


def _is_transient(error: Exception) -> bool:
    if isinstance(error, httpx.TransportError):
        return True
    return isinstance(error, AIMLAPIError) and error.status_code in _TRANSIENT_STATUSES


def _asset_url(value: Any) -> Optional[str]:
    """Generated assets arrive as {"url": ...}, [{"url": ...}] or a bare string."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("url")
    return value if isinstance(value, str) and value else None


def _asset_urls(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    urls = (_asset_url(item) for item in value)
    return [url for url in urls if url is not None]


def _asset_mime_type(content_type: Optional[str], url: str) -> str:
    """The media type of a downloaded asset.

    Signed storage links often answer ``application/octet-stream``; the file
    extension in the URL is the next best source.
    """
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared and declared != "application/octet-stream":
        return declared
    guessed, _ = mimetypes.guess_type(urlsplit(url).path)
    return guessed or declared or "application/octet-stream"


def _subtype(mime_type: str) -> str:
    """'image/png' -> 'png'; the format field Agno keys media handling on."""
    subtype = mime_type.split("/", 1)[1] if "/" in mime_type else mime_type
    return {"mpeg": "mp3", "x-wav": "wav", "quicktime": "mov"}.get(subtype, subtype)
