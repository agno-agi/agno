"""Workspace voice discovery and HTTP text-to-speech tools for 60db."""

import base64
import io
import json
import math
import wave
from os import getenv
from time import monotonic
from typing import Any, Literal, Optional, Union
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from agno.agent import Agent
from agno.media import Audio
from agno.team.team import Team
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.audio import pcm_to_wav_bytes
from agno.utils.log import log_error

SAMPLE_RATE = 24000
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


def _validate_metadata(record: dict[str, Any]) -> None:
    _validate_audio_metadata(record)
    if "audio_config" in record:
        config = record["audio_config"]
        if not isinstance(config, dict) or "audio_config" in config:
            raise ValueError("60db returned invalid audio configuration")
        _validate_audio_metadata(config)


def _validate_audio_metadata(record: dict[str, Any]) -> None:
    if record.get("success") is False or record.get("type") == "error" or record.get("error"):
        raise ValueError("60db reported a synthesis error")
    for key in ("encoding", "audio_encoding", "output_format"):
        if key in record and str(record[key]).lower() not in {"linear16", "pcm", "pcm16", "wav"}:
            raise ValueError("60db returned incompatible audio encoding")
    for key, expected in (
        ("sample_rate", SAMPLE_RATE),
        ("sample_rate_hertz", SAMPLE_RATE),
        ("channels", 1),
        ("bit_depth", 16),
    ):
        if key in record and record[key] != expected:
            raise ValueError("60db returned incompatible audio metadata")


def _pcm(audio: bytes) -> bytes:
    if audio.startswith(b"RIFF"):
        if len(audio) < 12 or int.from_bytes(audio[4:8], "little") + 8 != len(audio):
            raise ValueError("60db returned invalid or truncated WAV audio")
        with wave.open(io.BytesIO(audio), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (
                1,
                2,
                SAMPLE_RATE,
                "NONE",
            ):
                raise ValueError("60db WAV must be mono PCM16 at 24000 Hz")
            frames = wav.getnframes()
            audio = wav.readframes(frames)
            if len(audio) != frames * 2:
                raise ValueError("60db returned truncated WAV audio")
    elif audio.startswith((b"ID3", b"OggS", b"fLaC")):
        raise ValueError("60db returned compressed audio instead of PCM")
    if not audio or len(audio) % 2:
        raise ValueError("60db returned empty or incomplete PCM16 audio")
    return audio


class SixtyDBTools(Toolkit):
    """Use workspace voices through 60db's HTTP API.

    Set SIXTYDB_API_KEY or pass api_key. Call get_voices to find a workspace
    voice_id, then configure default_voice_id or supply a voice per synthesis.
    Audio is returned as mono PCM16 WAV at 24 kHz.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_voice_id: Optional[str] = None,
        speed: float = 1.0,
        base_url: str = "https://api.60db.ai",
        timeout: float = 60.0,
        enable_text_to_speech: bool = True,
        enable_get_voices: bool = True,
        all: bool = False,
        **kwargs: Any,
    ):
        """Configure authentication, voice selection and registered tool flags.

        A voice may be configured here or supplied to text_to_speech. An explicit
        api_key overrides SIXTYDB_API_KEY. timeout bounds each network operation
        and response consumption; HTTP is supported only on loopback for tests.
        """
        self.api_key = api_key if api_key is not None else getenv("SIXTYDB_API_KEY", "")
        if not self.api_key.strip():
            raise ValueError("Provide api_key or SIXTYDB_API_KEY")
        if default_voice_id is not None and not default_voice_id.strip():
            raise ValueError("default_voice_id must not be empty")
        if isinstance(speed, bool) or not math.isfinite(speed) or not 0.5 <= speed <= 2.0:
            raise ValueError("speed must be finite and between 0.5 and 2.0")
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        url = urlsplit(base_url)
        if (
            not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.scheme not in {"http", "https"}
            or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"})
        ):
            raise ValueError("base_url must be HTTPS, or HTTP on loopback, without credentials or query")
        self.default_voice_id = default_voice_id
        self.speed = speed
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        tools: list[Any] = []
        if all or enable_text_to_speech:
            tools.append(self.text_to_speech)
        if all or enable_get_voices:
            tools.append(self.get_voices)
        super().__init__(name="sixtydb_tools", tools=tools, **kwargs)

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> tuple[bytes, str]:
        deadline = monotonic() + self.timeout
        with httpx.stream(
            method,
            self.base_url + endpoint,
            headers={"Authorization": "Bearer " + self.api_key},
            timeout=self.timeout,
            follow_redirects=False,
            **kwargs,
        ) as response:
            if not 200 <= response.status_code < 300:
                raise ValueError("60db request failed (HTTP " + str(response.status_code) + ")")
            try:
                metadata = {
                    key: int(response.headers[header])
                    for key, header in (
                        ("sample_rate", "X-Sample-Rate"),
                        ("channels", "X-Channels"),
                        ("bit_depth", "X-Bit-Depth"),
                    )
                    if header in response.headers
                }
            except ValueError:
                raise ValueError("60db returned invalid HTTP audio metadata") from None
            _validate_metadata(metadata)
            data = bytearray()
            for chunk in response.iter_bytes():
                if monotonic() > deadline:
                    raise ValueError("60db response timed out")
                data.extend(chunk)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise ValueError("60db response exceeds 32 MiB")
            return bytes(data), response.headers.get("content-type", "").split(";", 1)[0].strip().lower()

    def _log_failure(self, operation: str, error: Exception) -> None:
        # Transport exceptions may contain request URLs; never log response bodies or tracebacks.
        if isinstance(error, (httpx.HTTPError, OSError)):
            detail = "network request failed"
        elif isinstance(error, json.JSONDecodeError):
            detail = f"invalid JSON at line {error.lineno}, column {error.colno}"
        else:
            detail = str(error).replace(self.api_key, "<REDACTED>")[:500]
        log_error(f"60db {operation} failed ({type(error).__name__}): {detail}", exc_info=False)

    def get_voices(self, model: Literal["quality", "fast"] = "quality") -> str:
        """List voices available in the authenticated workspace.

        Args:
            model: Voice catalog tier, quality or fast.

        Returns:
            JSON voice objects, or a sanitized error object.
        """
        if model not in {"quality", "fast"}:
            return json.dumps({"error": "model must be quality or fast"})
        try:
            body, content_type = self._request("GET", "/voices", params={"model": model})
            if content_type != "application/json":
                raise ValueError("Expected JSON voice catalog")
            result = json.loads(body)
            if (
                not isinstance(result, dict)
                or result.get("success") is not True
                or not isinstance(result.get("data"), list)
            ):
                raise ValueError("Invalid voice catalog")
            voices: list[dict[str, Any]] = []
            for voice in result["data"]:
                if not isinstance(voice, dict) or not isinstance(voice.get("voice_id"), str):
                    raise TypeError("Invalid workspace voice")
                voices.append({key: voice.get(key) for key in ("voice_id", "name", "model", "labels", "description")})
            return json.dumps(voices)
        except (httpx.HTTPError, ValueError, TypeError, KeyError, RecursionError) as error:
            self._log_failure("voice discovery", error)
            return json.dumps({"error": "60db voice discovery failed"})

    def text_to_speech(self, agent: Union[Agent, Team], text: str, voice_id: Optional[str] = None) -> ToolResult:
        """Convert text to a WAV audio artifact using a workspace voice.

        Args:
            text: Speech text, up to 5000 characters.
            voice_id: Workspace voice ID; otherwise use default_voice_id.

        Returns:
            ToolResult containing mono PCM16 WAV at 24 kHz, or a sanitized error.
        """
        voice = voice_id if voice_id is not None else self.default_voice_id
        if not text.strip() or len(text) > 5000:
            return ToolResult(content="Error: text must contain 1 to 5000 characters")
        if not voice or not voice.strip():
            return ToolResult(content="Error: provide a workspace voice_id or default_voice_id")
        try:
            body, content_type = self._request(
                "POST",
                "/tts-synthesize",
                json={
                    "text": text,
                    "voice_id": voice,
                    "speed": self.speed,
                    "timestamp_type": "NONE",
                    "audio_config": {"audio_encoding": "LINEAR16", "sample_rate_hertz": SAMPLE_RATE},
                },
            )
            if content_type != "application/json":
                raise ValueError("60db expected a JSON audio response")
            record = json.loads(body)
            if not isinstance(record, dict):
                raise TypeError("60db returned an invalid response object")
            _validate_metadata(record)
            result = record if "audio_base64" in record else record.get("backendResponse")
            if not isinstance(result, dict):
                raise TypeError("60db returned an invalid audio result")
            _validate_metadata(result)
            encoded = result.get("audio_base64")
            if not isinstance(encoded, str):
                raise TypeError("60db audio_base64 must be text")
            pcm = _pcm(base64.b64decode(encoded, validate=True))
            return ToolResult(
                content="Audio generated and attached.",
                audios=[
                    Audio(
                        id=str(uuid4()),
                        content=pcm_to_wav_bytes(pcm, channels=1, rate=SAMPLE_RATE, sample_width=2),
                        mime_type="audio/wav",
                        format="wav",
                        sample_rate=SAMPLE_RATE,
                    )
                ],
            )
        except (
            httpx.HTTPError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            RecursionError,
            EOFError,
            wave.Error,
        ) as error:
            self._log_failure("speech generation", error)
            return ToolResult(content="Error: 60db speech generation failed")
