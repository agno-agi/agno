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

SAMPLE_RATE = 24000
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


def _validate_metadata(record: dict[str, Any]) -> None:
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
    if "audio_config" in record:
        config = record["audio_config"]
        if not isinstance(config, dict):
            raise ValueError("60db returned invalid audio configuration")
        _validate_metadata(config)


def _record_audio(record: Any, formats: Optional[dict[int, str]] = None, offset: int = 0) -> bytes:  # noqa: FA100
    if not isinstance(record, dict):
        raise TypeError("60db returned an invalid response object")
    _validate_metadata(record)
    result = record.get("result", record.get("backendResponse", record))
    if not isinstance(result, dict):
        raise TypeError("60db returned an invalid audio result")
    _validate_metadata(result)
    declared_format = None
    if formats is not None:
        for metadata in (record, result, record.get("audio_config", {}), result.get("audio_config", {})):
            for key in ("encoding", "audio_encoding", "output_format"):
                if key in metadata and declared_format != "wav":
                    declared_format = "wav" if str(metadata[key]).lower() == "wav" else "pcm"
        if declared_format is not None:
            formats[offset] = declared_format
    value = result.get("audioContent", result.get("audio_base64"))
    if value is None:
        return b""
    if not isinstance(value, str):
        raise TypeError("60db audio must be base64 text")
    audio = base64.b64decode(value, validate=True)
    # The SDK also accepts an initial chunk containing a base64 JSON envelope.
    if audio.startswith(b"{"):
        try:
            inner = json.loads(audio)
        except (ValueError, UnicodeDecodeError):
            return audio
        if not isinstance(inner, dict) or not any(
            key in inner for key in ("audioContent", "audio_base64", "result", "backendResponse")
        ):
            raise ValueError("60db audio envelope contains no audio")
        audio = _record_audio(inner, formats, offset)
        if formats is not None and declared_format == "wav":
            formats[offset] = "wav"
        return audio
    return audio


class _UnrecognizedWAVPrefix(ValueError):
    pass


def _decode_wav(audio: bytes, offset: int) -> tuple[bytes, int]:
    if len(audio) - offset < 12 or audio[offset : offset + 4] != b"RIFF" or audio[offset + 8 : offset + 12] != b"WAVE":
        raise _UnrecognizedWAVPrefix("60db returned invalid WAV framing")
    size = int.from_bytes(audio[offset + 4 : offset + 8], "little") + 8
    if size < 12:
        raise _UnrecognizedWAVPrefix("60db returned invalid WAV size")
    if size > len(audio) - offset:
        raise ValueError("60db returned truncated WAV audio")
    with wave.open(io.BytesIO(audio[offset : offset + size]), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (
            1,
            2,
            SAMPLE_RATE,
            "NONE",
        ):
            raise ValueError("60db WAV must be mono PCM16 at 24000 Hz")
        frames = wav.getnframes()
        pcm = wav.readframes(frames)
        if len(pcm) != frames * 2:
            raise ValueError("60db returned truncated WAV audio")
        return pcm, size


def _pcm(audio: bytes, record_ends: Optional[list[int]] = None, formats: Optional[dict[int, str]] = None) -> bytes:  # noqa: FA100
    decoded = bytearray()
    offset = 0
    boundaries = iter(record_ends or [len(audio)])
    end = next(boundaries)
    pcm_declared = False
    while offset < len(audio):
        while end <= offset:
            end = next(boundaries, len(audio))
        declared_format = formats.get(offset) if formats is not None else None
        if declared_format is not None:
            pcm_declared = declared_format == "pcm"
        if declared_format == "wav" or (
            declared_format != "pcm"
            and audio[offset : offset + 4] == b"RIFF"
            and (record_ends is None or audio[offset + 8 : offset + 12] == b"WAVE")
        ):
            try:
                pcm, size = _decode_wav(audio, offset)
            except _UnrecognizedWAVPrefix:
                # An unlabeled PCM continuation may contain WAV-shaped sample bytes.
                if not pcm_declared or declared_format is not None:
                    raise
            else:
                decoded.extend(pcm)
                offset += size
                pcm_declared = False
                continue
        if record_ends is None and offset:
            raise ValueError("60db returned invalid WAV framing")
        if not pcm_declared and audio[offset : offset + 4].startswith((b"ID3", b"OggS", b"fLaC")):
            raise ValueError("60db returned compressed audio instead of PCM")
        decoded.extend(audio[offset:end])
        offset = end
    if not decoded or len(decoded) % 2:
        raise ValueError("60db returned empty or incomplete PCM16 audio")
    return bytes(decoded)


class SixtyDBTools(Toolkit):
    """Use workspace voices through 60db's HTTP API.

    Credentials stay on the agent server. Speech text is sent to 60db when the
    synthesis tool is invoked. Audio is validated and returned as PCM16 WAV.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,  # noqa: FA100
        default_voice_id: Optional[str] = None,  # noqa: FA100
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
            _validate_metadata(
                {
                    key: int(response.headers[header])
                    for key, header in (
                        ("sample_rate", "X-Sample-Rate"),
                        ("channels", "X-Channels"),
                        ("bit_depth", "X-Bit-Depth"),
                    )
                    if header in response.headers
                }
            )
            data = bytearray()
            for chunk in response.iter_bytes():
                if monotonic() > deadline:
                    raise ValueError("60db response timed out")
                data.extend(chunk)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise ValueError("60db response exceeds 32 MiB")
            return bytes(data), response.headers.get("content-type", "").split(";", 1)[0].strip().lower()

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
        except (httpx.HTTPError, ValueError, TypeError, KeyError, RecursionError):
            return json.dumps({"error": "60db voice discovery failed"})

    # Python 3.9 evaluates these annotations when generating the tool schema.
    def text_to_speech(self, agent: Union[Agent, Team], text: str, voice_id: Optional[str] = None) -> ToolResult:  # noqa: FA100
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
            formats: dict[int, str] = {}
            if content_type in {"application/x-ndjson", "application/ndjson", "text/plain"}:
                audio_records = []
                ends = []
                total = 0
                for line in body.splitlines():
                    if line.strip():
                        record = _record_audio(json.loads(line), formats, total)
                        if record:
                            audio_records.append(record)
                            total += len(record)
                            ends.append(total)
                audio = _pcm(b"".join(audio_records), ends, formats)
            elif content_type == "application/json":
                audio = _record_audio(json.loads(body), formats)
            elif content_type in {"audio/wav", "audio/x-wav", "audio/pcm", "application/octet-stream"}:
                audio = body
            else:
                raise ValueError("Unsupported audio response")
            pcm = (
                audio
                if content_type in {"application/x-ndjson", "application/ndjson", "text/plain"}
                else _pcm(audio, formats=formats)
            )
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(SAMPLE_RATE)
                wav.writeframes(pcm)
            return ToolResult(
                content="Audio generated and attached.",
                audios=[
                    Audio(
                        id=str(uuid4()),
                        content=buffer.getvalue(),
                        mime_type="audio/wav",
                        format="wav",
                        sample_rate=SAMPLE_RATE,
                    )
                ],
            )
        except (httpx.HTTPError, OSError, ValueError, TypeError, KeyError, RecursionError, EOFError, wave.Error):
            return ToolResult(content="Error: 60db speech generation failed")
