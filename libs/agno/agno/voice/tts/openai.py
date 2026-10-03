"""OpenAI streaming audio output with bounded phrase buffering."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from agno.voice.base import TTSModel, TTSSession
from agno.voice.tts._phrases import _PhraseSession


@dataclass
class OpenAITTS(TTSModel):
    """Stream PCM speech for short phrases on a reused OpenAI SDK client.

    The Speech API accepts complete text per request, not incremental input.
    Phrases are bounded by punctuation, length, and time; CartesiaTTS can be
    used when streaming both text input and audio output is required.
    Playback alignment is phrase-level because this API has no word timings.
    """

    id: str = "gpt-4o-mini-tts"
    voice: str = "coral"
    instructions: Optional[str] = None
    speed: float = 1.0
    api_key: Optional[str] = field(default=None, repr=False)
    base_url: Optional[str] = None
    async_client: Optional[Any] = field(default=None, repr=False)
    max_phrase_chars: int = 160
    max_phrase_delay_ms: int = 200

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.voice.strip():
            raise ValueError("OpenAI speech model and voice must not be empty.")
        if not 0.25 <= self.speed <= 4:
            raise ValueError("speed must be between 0.25 and 4.")
        if self.max_phrase_chars < 16 or self.max_phrase_chars > 4096:
            raise ValueError("max_phrase_chars must be between 16 and 4096.")
        if self.max_phrase_delay_ms <= 0:
            raise ValueError("max_phrase_delay_ms must be positive.")

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[TTSSession]:
        client: Any = self.async_client
        owned = client is None
        if owned:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise ImportError("OpenAITTS requires `pip install 'agno[openai]'`.") from exc
            client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        try:
            yield _OpenAISpeechSession(client, self)
        finally:
            if owned:
                await client.close()


class _OpenAISpeechSession(_PhraseSession):
    _provider = "OpenAI"

    def __init__(self, client: Any, model: OpenAITTS) -> None:
        super().__init__(model.max_phrase_chars, model.max_phrase_delay_ms)
        self._client = client
        self._model = model

    async def _stream_phrase(self, phrase: str) -> AsyncIterator[bytes]:
        parameters = {
            "model": self._model.id,
            "voice": self._model.voice,
            "input": phrase,
            "response_format": "pcm",
            "speed": self._model.speed,
        }
        if self._model.instructions:
            parameters["instructions"] = self._model.instructions
        async with self._client.audio.speech.with_streaming_response.create(**parameters) as response:
            # Native network chunks avoid waiting to fill a large fixed
            # buffer before forwarding the first audible samples.
            async for data in response.iter_bytes():
                yield data
