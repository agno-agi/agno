"""Gemini text to speech, streamed one phrase at a time over the Interactions API."""

import base64
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from os import getenv
from typing import Any, AsyncIterator, Dict, Optional

from agno.voice.base import TTSModel, TTSSession
from agno.voice.tts._phrases import _PhraseSession


@dataclass
class GeminiTTS(TTSModel):
    """Speak replies with a Gemini TTS model and a prebuilt or custom voice.

    Gemini TTS reads each request's text verbatim and needs the whole text up
    front, so replies are spoken phrase by phrase while the agent keeps
    generating. Streamed audio is raw PCM16 at 24 kHz, the pipe's format.
    ``style`` describes delivery for every phrase, for example
    "warm and unhurried". Reads ``GOOGLE_API_KEY`` or ``GEMINI_API_KEY``.
    """

    id: str = "gemini-3.8-flash-lite-tts"
    voice: str = "Kore"
    style: Optional[str] = None
    api_key: Optional[str] = field(default=None, repr=False)
    base_url: str = "https://generativelanguage.googleapis.com/v1beta/interactions"
    max_phrase_chars: int = 240
    max_phrase_delay_ms: int = 200
    timeout: float = 30.0

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.voice.strip():
            raise ValueError("Gemini speech model and voice must not be empty.")
        if self.max_phrase_chars < 16 or self.max_phrase_chars > 4096:
            raise ValueError("max_phrase_chars must be between 16 and 4096.")
        if self.max_phrase_delay_ms <= 0 or self.timeout <= 0:
            raise ValueError("Gemini phrase delay and timeout must be positive.")

    def _request(self, phrase: str) -> Dict[str, Any]:
        content: Dict[str, Any] = {"type": "text", "text": phrase}
        if self.style:
            content["annotations"] = [{"type": "speech_metadata", "style": self.style}]
        return {
            "model": self.id,
            "input": [{"type": "user_input", "content": [content]}],
            "response_format": {"type": "audio"},
            "generation_config": {"speech_config": [{"voice": self.voice}]},
            "stream": True,
        }

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[TTSSession]:
        import httpx

        api_key = self.api_key or getenv("GOOGLE_API_KEY") or getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Set GOOGLE_API_KEY or pass api_key to GeminiTTS.")
        async with httpx.AsyncClient(
            headers={"x-goog-api-key": api_key}, timeout=httpx.Timeout(self.timeout)
        ) as client:
            yield _GeminiSpeechSession(client, self)


class _GeminiSpeechSession(_PhraseSession):
    _provider = "Gemini"

    def __init__(self, client: Any, model: GeminiTTS) -> None:
        super().__init__(model.max_phrase_chars, model.max_phrase_delay_ms)
        self._client = client
        self._model = model

    async def _stream_phrase(self, phrase: str) -> AsyncIterator[bytes]:
        async with self._client.stream("POST", self._model.base_url, json=self._model._request(phrase)) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", "replace")
                raise RuntimeError(f"Gemini speech: HTTP {response.status_code}: {_error_message(body)}")
            # Server-sent events: each "data:" line carries one JSON event.
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                event = json.loads(data)
                kind = event.get("event_type")
                if kind == "error":
                    raise RuntimeError(f"Gemini speech: {_error_message(event)}")
                delta = event.get("delta") or {}
                if kind == "step.delta" and delta.get("type") == "audio" and delta.get("data"):
                    yield base64.b64decode(delta["data"], validate=True)


def _error_message(payload: Any) -> str:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return payload[:300] or "request failed"
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or error)
    return str(payload)[:300]
